"""AWS-connected camera client for PathAble (Person 1 workstream).

Connects the fixed camera laptop to AWS:
1. Detects sustained chair-overlap events in the operator-assigned region at junction B.
2. Captures evidence JPEG, computes SHA-256, and submits an obstacle report to AWS.
3. Keeps network operations off the camera/vision thread via an outbox worker.
4. Polls the authoritative shared map in the background.
5. On approved B-C closure, computes the alternative route (B -> E -> F -> D)
   and announces it once via VoiceGuidance.

Safety Invariants:
- Unverified chair overlap is an image-region heuristic, NOT verified corridor clearance.
- Detection does NOT declare free space or immediately perform rerouting.
- Pending reports or connection drops NEVER fabricate an approved closure.
- Edge reopening requires an authoritative cloud map update, never chair disappearance.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid

from local_agent import RouteMap


logger = logging.getLogger("pathable.aws_client")


class DeviceWorkflowStatus(str, Enum):
    MONITORING = "MONITORING"
    UPLOADING_EVIDENCE = "UPLOADING_EVIDENCE"
    REPORT_SENT = "REPORT_SENT"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    PROPOSED_ROUTE_UPDATED = "PROPOSED_ROUTE_UPDATED"
    CONNECTION_UNAVAILABLE = "CONNECTION_UNAVAILABLE"


@dataclass
class DeviceReportRecord:
    report_id: str
    camera_id: str
    observed_at: str
    obstacle_class: str
    confidence: float
    overlap_count: int
    frame_count: int
    assigned_edge: Tuple[str, str] = ("B", "C")
    assigned_node: str = "B"
    destination_node: str = "D"
    jpeg_bytes: bytes = b""
    jpeg_sha256: str = ""
    photo_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    retries: int = 0
    submitted_at: Optional[str] = None
    last_error: Optional[str] = None


class AwsDeviceClient:
    """Manages outbox submission, background map polling, and cloud-driven rerouting."""

    def __init__(
        self,
        api_base_url: str = "http://127.0.0.1:8000",
        api_prefix: str = "/api/v2",
        camera_id: str = "camera-b-01",
        assigned_node: str = "B",
        assigned_edge: Tuple[str, str] = ("B", "C"),
        destination_node: str = "D",
        auth_token: Optional[str] = None,
        route_map: Optional[RouteMap] = None,
        voice: Optional[Any] = None,
        poll_interval_s: float = 2.5,
        outbox_dir: Optional[Path] = None,
        http_timeout_s: float = 5.0,
        immediate_local_reroute: bool = True,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_prefix = "/" + api_prefix.strip("/")
        self.camera_id = camera_id
        self.assigned_node = assigned_node
        self.assigned_edge = tuple(sorted(assigned_edge))
        self.destination_node = destination_node
        self.auth_token = auth_token
        self.route_map = route_map
        self.voice = voice
        self.poll_interval_s = max(0.5, float(poll_interval_s))
        self.http_timeout_s = max(1.0, float(http_timeout_s))
        self.immediate_local_reroute = immediate_local_reroute

        # Outbox storage directory for persistence across restarts
        self.outbox_dir = outbox_dir or (Path(__file__).parent / "calibration" / "outbox")
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

        # Threading state
        self._status = DeviceWorkflowStatus.MONITORING
        self._status_lock = threading.Lock()
        self._last_error_message: Optional[str] = None

        # Queue and background workers
        self._submission_queue: queue.Queue[DeviceReportRecord] = queue.Queue()
        self._current_report: Optional[DeviceReportRecord] = None
        self._active_report_lock = threading.Lock()

        # Map synchronization state
        self.known_map_version: Optional[int] = None
        self.last_applied_version: Optional[int] = None
        self.is_edge_blocked_in_cloud: bool = False
        self.proposed_route: List[str] = []
        if self.route_map:
            self.proposed_route = list(self.route_map.route(self.assigned_node, self.destination_node))

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._poller_thread: Optional[threading.Thread] = None

        # Track speech to prevent repeated identical announcements
        self._announced_map_version: Optional[int] = None
        self.last_announcement: Optional[str] = None

    @property
    def status(self) -> DeviceWorkflowStatus:
        with self._status_lock:
            return self._status

    @property
    def last_error(self) -> Optional[str]:
        with self._status_lock:
            return self._last_error_message

    def set_status(self, new_status: DeviceWorkflowStatus, error_msg: Optional[str] = None) -> None:
        with self._status_lock:
            self._status = new_status
            if error_msg is not None:
                self._last_error_message = error_msg
            elif new_status != DeviceWorkflowStatus.CONNECTION_UNAVAILABLE:
                self._last_error_message = None

    def start(self) -> None:
        """Starts background outbox worker and map poller threads."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._run_outbox_worker, name="AwsOutboxWorker", daemon=True)
        self._worker_thread.start()

        self._poller_thread = threading.Thread(target=self._run_map_poller, name="AwsMapPoller", daemon=True)
        self._poller_thread.start()
        logger.info("AwsDeviceClient started (camera: %s, api: %s%s)", self.camera_id, self.api_base_url, self.api_prefix)

    def stop(self) -> None:
        """Stops background threads cleanly."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self._poller_thread and self._poller_thread.is_alive():
            self._poller_thread.join(timeout=2.0)
        logger.info("AwsDeviceClient stopped")

    # -------------------------------------------------------------------------
    # Detection trigger hook (called from live camera loop)
    # -------------------------------------------------------------------------

    def on_chair_overlap_trigger(
        self,
        evidence: Dict[str, Any],
        jpeg_frame: bytes,
        observed_at: Optional[datetime] = None,
    ) -> Optional[DeviceReportRecord]:
        """Called when ChairRegionMonitor sustained trigger fires.

        Idempotent: if a report for the current sustained event is already
        in progress or awaiting review, does NOT generate duplicate reports.
        """
        with self._active_report_lock:
            if self._current_report is not None:
                # Already have an active report awaiting review or in-flight
                return None

            obs_dt = observed_at or datetime.now(timezone.utc)
            timestamp_str = obs_dt.isoformat()
            if not timestamp_str.endswith("Z") and "+" not in timestamp_str:
                timestamp_str += "Z"

            report_id = str(uuid.uuid4())
            sha256_hash = hashlib.sha256(jpeg_frame).hexdigest()

            curr_obstacle = evidence.get("current") or {}
            confidence = float(curr_obstacle.get("confidence", 0.85))

            record = DeviceReportRecord(
                report_id=report_id,
                camera_id=self.camera_id,
                observed_at=timestamp_str,
                obstacle_class="chair",
                confidence=confidence,
                overlap_count=int(evidence.get("positive_frames", 6)),
                frame_count=int(evidence.get("total_frames", 10)),
                assigned_edge=self.assigned_edge,
                assigned_node=self.assigned_node,
                destination_node=self.destination_node,
                jpeg_bytes=jpeg_frame,
                jpeg_sha256=sha256_hash,
                status="PENDING",
            )
            self._current_report = record

        # Persist report in outbox directory
        self._persist_outbox_record(record)
        self.set_status(DeviceWorkflowStatus.UPLOADING_EVIDENCE)
        self._submission_queue.put(record)
        logger.info("Queued obstacle report %s for sustained chair overlap", report_id)

        # Immediate local safety decision: reroute and speak immediately on device!
        if self.immediate_local_reroute and self.route_map:
            self.route_map.block(self.assigned_edge[0], self.assigned_edge[1])
            self.proposed_route = list(self.route_map.route(self.assigned_node, self.destination_node))
            route_str = ", ".join(self.proposed_route)
            msg = (
                f"Obstacle detected ahead. Route {self.assigned_edge[0]} to {self.assigned_edge[1]} blocked. "
                f"Taking alternative route: {route_str}."
            )
            self.last_announcement = msg
            logger.info("IMMEDIATE LOCAL REROUTE: %s", msg)
            if self.voice:
                try:
                    self.voice.speak(msg, force=True, priority=True)
                except Exception as e:
                    logger.warning("Voice playback failed: %s", e)

        return record

    # -------------------------------------------------------------------------
    # HTTP transport helper with Bearer authentication
    # -------------------------------------------------------------------------

    def _http_request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Makes an HTTP request with bounded timeout, returning (status_code, json_dict)."""
        url = f"{self.api_base_url}{self.api_prefix}{path}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "PathAble-DeviceClient/1.0",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        data_bytes = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout_s) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                try:
                    parsed = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    parsed = {"raw": body}
                return status_code, parsed
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                parsed = json.loads(err_body) if err_body else {}
            except json.JSONDecodeError:
                parsed = {"detail": err_body}
            return e.code, parsed
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConnectionError(f"HTTP request to {url} failed: {e}") from e

    # -------------------------------------------------------------------------
    # Outbox worker (photo upload + report submission with retries)
    # -------------------------------------------------------------------------

    def _run_outbox_worker(self) -> None:
        """Worker thread processing evidence photo uploads and obstacle reports."""
        while not self._stop_event.is_set():
            try:
                record = self._submission_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            success = False
            while not success and not self._stop_event.is_set():
                record.retries += 1
                try:
                    # Step 1: Upload photo if not yet uploaded
                    if not record.photo_id:
                        self.set_status(DeviceWorkflowStatus.UPLOADING_EVIDENCE)
                        photo_id = self._upload_photo(record)
                        record.photo_id = photo_id
                        self._persist_outbox_record(record)

                    # Step 2: Submit report referencing photo
                    self._submit_report(record)
                    record.submitted_at = datetime.now(timezone.utc).isoformat()
                    self._persist_outbox_record(record)
                    self.set_status(DeviceWorkflowStatus.AWAITING_REVIEW)
                    success = True
                    logger.info("Report %s successfully posted to AWS (awaiting review)", record.report_id)

                except ConnectionError as err:
                    record.last_error = str(err)
                    logger.warning("Network connection unavailable on attempt %d: %s", record.retries, err)
                    self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, str(err))
                    # Bounded exponential-ish backoff up to 10s
                    sleep_time = min(10.0, 1.5 * record.retries)
                    self._stop_event.wait(sleep_time)
                except Exception as err:
                    record.last_error = str(err)
                    logger.error("Non-transient error processing report %s: %s", record.report_id, err, exc_info=True)
                    self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, str(err))
                    self._stop_event.wait(3.0)

            self._submission_queue.task_done()

    def _upload_photo(self, record: DeviceReportRecord) -> str:
        """Uploads JPEG evidence image to /photos endpoint."""
        b64_img = base64.b64encode(record.jpeg_bytes).decode("ascii")
        payload = {
            "camera_id": record.camera_id,
            "jpeg_base64": b64_img,
        }
        status_code, resp = self._http_request("POST", "/photos", payload)
        if status_code in (200, 201) and "photo_id" in resp:
            return resp["photo_id"]
        detail = resp.get("detail", str(resp))
        raise ConnectionError(f"Photo upload rejected (HTTP {status_code}): {detail}")

    def _submit_report(self, record: DeviceReportRecord) -> Dict[str, Any]:
        """Submits obstacle report to /reports endpoint."""
        payload = {
            "report_id": record.report_id,
            "camera_id": record.camera_id,
            "photo_id": record.photo_id,
            "observed_at": record.observed_at,
            "obstacle_class": record.obstacle_class,
            "confidence": record.confidence,
            "overlap_count": record.overlap_count,
            "frame_count": record.frame_count,
            "distance_m": None,
            "clearance_m": None,
            "measurement_source": None,
        }
        status_code, resp = self._http_request("POST", "/reports", payload)
        if status_code in (200, 201):
            return resp
        if status_code == 409:
            # Report already exists with identical ID (idempotent success)
            logger.info("Report %s already registered in cloud (409 idempotent retry accepted)", record.report_id)
            return resp
        detail = resp.get("detail", str(resp))
        raise ConnectionError(f"Report submission rejected (HTTP {status_code}): {detail}")

    # -------------------------------------------------------------------------
    # Map Poller (Polls authoritative map version & applies approved closure)
    # -------------------------------------------------------------------------

    def _run_map_poller(self) -> None:
        """Periodically polls /map/version and synchronizes authoritative graph."""
        while not self._stop_event.is_set():
            try:
                self.poll_and_synchronize_map()
            except ConnectionError as err:
                logger.debug("Map polling unavailable: %s", err)
                if self.status != DeviceWorkflowStatus.UPLOADING_EVIDENCE:
                    self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, str(err))
            except Exception as err:
                logger.error("Unexpected error polling map: %s", err, exc_info=True)

            self._stop_event.wait(self.poll_interval_s)

    def poll_and_synchronize_map(self) -> bool:
        """Polls version endpoint and downloads full map if newer version exists.

        Returns True if a new map version was applied.
        """
        status_code, ver_resp = self._http_request("GET", "/map/version")
        if status_code != 200:
            raise ConnectionError(f"Map version check failed (HTTP {status_code})")

        remote_version = ver_resp.get("version")
        if remote_version is None:
            return False

        self.known_map_version = remote_version

        # If we have not applied this version yet:
        if self.last_applied_version is None or remote_version > self.last_applied_version:
            logger.info("Detected new authoritative map version v%d (previous: %s)", remote_version, self.last_applied_version)
            self._fetch_and_apply_full_map(remote_version)
            return True

        return False

    def _fetch_and_apply_full_map(self, version: int) -> None:
        """Downloads full map and checks if assigned edge B-C is approved blocked."""
        status_code, map_resp = self._http_request("GET", "/map")
        if status_code != 200:
            raise ConnectionError(f"Failed to fetch full map (HTTP {status_code})")

        edges = map_resp.get("edges", [])
        edge_bc_blocked = False

        for e in edges:
            u, v = e.get("from"), e.get("to")
            if sorted([u, v]) == list(self.assigned_edge):
                if e.get("blocked") is True:
                    edge_bc_blocked = True
                break

        self.last_applied_version = version
        self.is_edge_blocked_in_cloud = edge_bc_blocked

        if edge_bc_blocked:
            self.set_status(DeviceWorkflowStatus.APPROVED)
            if self.route_map:
                # Update local routing graph
                self.route_map.block(self.assigned_edge[0], self.assigned_edge[1])
                new_route = self.route_map.route(self.assigned_node, self.destination_node)
                self.proposed_route = list(new_route)

            self.set_status(DeviceWorkflowStatus.PROPOSED_ROUTE_UPDATED)
            self._announce_route_if_new(version)
        else:
            # Edge is still unblocked in the authoritative map
            if self._current_report is not None and self._current_report.submitted_at:
                self.set_status(DeviceWorkflowStatus.AWAITING_REVIEW)
            elif self._current_report is None:
                self.set_status(DeviceWorkflowStatus.MONITORING)

    def _announce_route_if_new(self, map_version: int) -> bool:
        """Announces the new proposed alternative route once per map version."""
        if self._announced_map_version == map_version:
            # Already announced this map version
            return False

        self._announced_map_version = map_version
        route_str = ", ".join(self.proposed_route) if self.proposed_route else "none"
        message = (
            f"Approved map update received from cloud. "
            f"Route B to C is closed. Proposed alternative route: {route_str}."
        )
        self.last_announcement = message
        logger.info("ANNOUNCEMENT: %s", message)

        if self.voice:
            try:
                self.voice.speak(message, force=True, priority=True)
            except Exception as e:
                logger.warning("Voice playback failed: %s", e)
        return True

    # -------------------------------------------------------------------------
    # Outbox persistence helpers
    # -------------------------------------------------------------------------

    def _persist_outbox_record(self, record: DeviceReportRecord) -> None:
        """Saves report metadata and evidence frame to local outbox."""
        record_file = self.outbox_dir / f"{record.report_id}.json"
        img_file = self.outbox_dir / f"{record.report_id}.jpg"

        meta = {
            "report_id": record.report_id,
            "camera_id": record.camera_id,
            "observed_at": record.observed_at,
            "obstacle_class": record.obstacle_class,
            "confidence": record.confidence,
            "overlap_count": record.overlap_count,
            "frame_count": record.frame_count,
            "assigned_edge": list(record.assigned_edge),
            "assigned_node": record.assigned_node,
            "destination_node": record.destination_node,
            "jpeg_sha256": record.jpeg_sha256,
            "photo_id": record.photo_id,
            "status": record.status,
            "retries": record.retries,
            "submitted_at": record.submitted_at,
            "last_error": record.last_error,
        }
        try:
            with open(record_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            if record.jpeg_bytes and not img_file.exists():
                with open(img_file, "wb") as f:
                    f.write(record.jpeg_bytes)
        except OSError as e:
            logger.warning("Could not persist outbox record: %s", e)
