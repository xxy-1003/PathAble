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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import queue
import threading
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
import uuid

from local_agent import RouteMap


logger = logging.getLogger("pathable.aws_client")

PROTOTYPE_PAIRS = {frozenset(pair) for pair in
                   (("A", "B"), ("B", "C"), ("C", "D"), ("B", "E"), ("E", "F"), ("F", "D"))}


class RequestRejected(ConnectionError):
    """An API response that must not be retried blindly."""


def validated_cloud_map(data, minimum_version=1):
    """Convert abstract route_weight into RouteMap's internal cost field, not metres."""
    if (not isinstance(data, dict) or data.get("map_id") != "prototype" or
            type(data.get("version")) is not int or data["version"] < minimum_version or
            not isinstance(data.get("nodes"), dict) or len(data["nodes"]) != 6 or
            not all(isinstance(n, str) for n in data["nodes"].values()) or
            set(data["nodes"].values()) != set("ABCDEF") or
            not isinstance(data.get("edges"), list)):
        raise ConnectionError("Invalid or stale authoritative map; retained previous map")
    seen, translated = set(), []
    for edge in data["edges"]:
        if not isinstance(edge, dict):
            raise ConnectionError("Invalid map edge")
        a, b = edge.get("from"), edge.get("to")
        if not isinstance(a, str) or not isinstance(b, str):
            raise ConnectionError("Invalid map endpoints")
        key = frozenset((a, b))
        if (key not in PROTOTYPE_PAIRS or key in seen or type(edge.get("blocked")) is not bool or
                type(edge.get("route_weight")) is not int or edge["route_weight"] < 1 or
                "distance" not in edge or edge["distance"] is not None or
                edge.get("distance_source") != "unmeasured"):
            raise ConnectionError("Invalid map edge or unverified measurement")
        seen.add(key)
        translated.append({"from": a, "to": b, "distance": edge["route_weight"],
                           "blocked": edge["blocked"]})
    if seen != PROTOTYPE_PAIRS:
        raise ConnectionError("Incomplete authoritative map; retained previous map")
    return RouteMap({"version": data["version"], "nodes": data["nodes"], "edges": translated})


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
        max_submission_attempts: int = 3,
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
        self.max_submission_attempts = max(1, int(max_submission_attempts))

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
        self._active_report_lock = threading.RLock()
        self._persistence_lock = threading.RLock()
        self._reports: Dict[str, DeviceReportRecord] = {}
        self._episode_active = False
        self._recovery_error = False

        # Map synchronization state
        self.known_map_version: Optional[int] = None
        self.last_applied_version: Optional[int] = None
        self.is_edge_blocked_in_cloud: bool = False
        self.map_synchronized = False
        self.proposed_route: List[str] = []
        if self.route_map:
            self.proposed_route = list(self.route_map.route(self.assigned_node, self.destination_node))

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._poller_thread: Optional[threading.Thread] = None

        # Track speech to prevent repeated identical announcements
        self._announced_map_version: Optional[int] = None
        self.last_announcement: Optional[str] = None
        self._cloud_map = None
        self._restore_state()
        self._restore_outbox()

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
        if any(t and t.is_alive() for t in (self._worker_thread, self._poller_thread)):
            return
        if self._recovery_error:
            self._refresh_status()
            return
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
            self._worker_thread.join(timeout=self.http_timeout_s + 1)
        if self._poller_thread and self._poller_thread.is_alive():
            self._poller_thread.join(timeout=self.http_timeout_s + 1)
        logger.info("AwsDeviceClient stopped")

    # -------------------------------------------------------------------------
    # Detection trigger hook (called from live camera loop)
    # -------------------------------------------------------------------------

    @property
    def needs_evidence(self):
        with self._active_report_lock:
            return not (self._current_report or self._episode_active or self._recovery_error)

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
            if self._recovery_error:
                return None
            if evidence.get("trigger") is not True:
                if self._episode_active:
                    self._episode_active = False
                    self._persist_state()
                return None
            if self._current_report is not None or self._episode_active or self._recovery_error:
                return None

            obs_dt = observed_at or datetime.now(timezone.utc)
            if obs_dt.tzinfo is None or obs_dt.utcoffset() is None:
                raise ValueError("Observation time must include a timezone")
            timestamp_str = obs_dt.astimezone(timezone.utc).isoformat()

            report_id = str(uuid.uuid4())
            sha256_hash = hashlib.sha256(jpeg_frame).hexdigest()

            curr_obstacle = evidence.get("current") or {}
            confidence = curr_obstacle.get("confidence")
            positives, frames = evidence.get("positive_frames"), evidence.get("total_frames")
            if (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or
                    not math.isfinite(confidence) or not 0 <= confidence <= 1 or
                    type(positives) is not int or type(frames) is not int or
                    not 1 <= positives <= frames <= 10000 or not jpeg_frame):
                raise ValueError("Actual detection counts, confidence and image are required")

            record = DeviceReportRecord(
                report_id=report_id,
                camera_id=self.camera_id,
                observed_at=timestamp_str,
                obstacle_class="chair",
                confidence=confidence,
                overlap_count=positives,
                frame_count=frames,
                assigned_edge=self.assigned_edge,
                assigned_node=self.assigned_node,
                destination_node=self.destination_node,
                jpeg_bytes=jpeg_frame,
                jpeg_sha256=sha256_hash,
                status="PENDING",
            )
            # Commit evidence before acknowledging/queuing it; failed disk writes
            # must not create a supposedly recoverable in-memory-only event.
            self._persist_outbox_record(record)
            self._reports[record.report_id] = record
            self._current_report = record
            self._episode_active = True
            self._persist_state()

        # Persist report in outbox directory
        self.set_status(DeviceWorkflowStatus.UPLOADING_EVIDENCE)
        self._submission_queue.put(record)
        logger.info("Queued obstacle report %s for sustained chair overlap", report_id)

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
        while not self._stop_event.is_set() and not self._recovery_error:
            try:
                record = self._submission_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            for attempt in range(self.max_submission_attempts):
                if self._stop_event.is_set():
                    break
                record.retries += 1
                try:
                    # Step 1: Upload photo if not yet uploaded
                    if not record.photo_id:
                        self.set_status(DeviceWorkflowStatus.UPLOADING_EVIDENCE)
                        photo_id = self._upload_photo(record)
                        record.photo_id = photo_id
                        self._persist_outbox_record(record)
                    if self._stop_event.is_set():
                        break

                    # Step 2: Submit report referencing photo
                    response = self._submit_report(record)
                    self._accept_report_response(record, response)
                    logger.info("Report %s confirmed by configured API", record.report_id)
                    break
                except RequestRejected as err:
                    self._save_failure(record, str(err))
                    break
                except ConnectionError as err:
                    if not self._save_failure(record, str(err)):
                        break
                    if attempt + 1 < self.max_submission_attempts:
                        self._stop_event.wait(min(10.0, 1.5 * (attempt + 1)))
                except Exception as err:
                    record.last_error = "Local processing/persistence failed; inspect outbox before retry"
                    self._recovery_error = True
                    logger.error("Report %s processing failed (%s)", record.report_id, type(err).__name__)
                    self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, record.last_error)
                    break

            self._submission_queue.task_done()

    def _save_failure(self, record, message):
        record.last_error = message
        try:
            self._persist_outbox_record(record)
        except OSError:
            self._recovery_error = True
            record.last_error = "Could not save retry state; inspect outbox before continuing"
        self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, record.last_error)
        return not self._recovery_error

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
        self._raise_api_error("Photo upload", status_code)

    @staticmethod
    def _raise_api_error(operation, status):
        # Server bodies can contain private values; do not copy them to logs/outbox.
        error = ConnectionError if status in (408, 429, 500, 502, 503, 504) else RequestRejected
        raise error(f"{operation} failed (HTTP {status}); reconcile state or correct configuration before restarting retries")

    @staticmethod
    def _validate_report_response(record, response):
        if (not isinstance(response, dict) or response.get("report_id") != record.report_id or
                response.get("camera_id") != record.camera_id or
                response.get("photo_id") != record.photo_id or
                response.get("status") not in ("PENDING", "APPROVED", "REJECTED")):
            raise ConnectionError("Invalid report response; submission/review outcome is unconfirmed")
        return response

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
            return self._validate_report_response(record, resp)
        # The contract returns 200 for an identical retry. 409 is a changed-payload
        # conflict, never evidence that this exact report was accepted.
        self._raise_api_error("Report submission", status_code)

    def _accept_report_response(self, record, response):
        self._validate_report_response(record, response)
        with self._active_report_lock:
            record.status = response["status"]
            record.submitted_at = record.submitted_at or datetime.now(timezone.utc).isoformat()
            record.last_error = None
            self._persist_outbox_record(record)
            self._current_report = next((r for r in self._reports.values() if r.status == "PENDING"), None)
            self._refresh_status()

    def _poll_report_statuses(self):
        with self._active_report_lock:
            reports = [r for r in self._reports.values() if r.status == "PENDING" and r.submitted_at]
        for record in reports:
            if self._stop_event.is_set():
                return
            code, result = self._http_request("GET", "/reports/" + record.report_id)
            if code != 200:
                self._raise_api_error("Report status check", code)
            self._accept_report_response(record, result)

    def _refresh_status(self):
        if self._recovery_error:
            self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, "Local recovery requires attention; no new report will be created")
        elif self._current_report:
            record = self._current_report
            if record.last_error:
                self.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, record.last_error)
            else:
                self.set_status(DeviceWorkflowStatus.AWAITING_REVIEW if record.submitted_at else DeviceWorkflowStatus.UPLOADING_EVIDENCE)
        else:
            self.set_status(DeviceWorkflowStatus.PROPOSED_ROUTE_UPDATED if self.is_edge_blocked_in_cloud
                            else DeviceWorkflowStatus.MONITORING)

    # -------------------------------------------------------------------------
    # Map Poller (Polls authoritative map version & applies approved closure)
    # -------------------------------------------------------------------------

    def _run_map_poller(self) -> None:
        """Periodically polls /map/version and synchronizes authoritative graph."""
        while not self._stop_event.is_set():
            try:
                self.poll_and_synchronize_map()
            except ConnectionError as err:
                self.map_synchronized = False
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
        if self._recovery_error:
            raise RequestRejected("Resolve local recovery errors before polling")
        self.map_synchronized = False
        status_code, ver_resp = self._http_request("GET", "/map/version")
        if status_code != 200:
            raise ConnectionError(f"Map version check failed (HTTP {status_code})")

        if not isinstance(ver_resp, dict):
            raise ConnectionError("Invalid map version response")
        remote_version = ver_resp.get("version")
        if (ver_resp.get("map_id") != "prototype" or type(remote_version) is not int or remote_version < 1 or
                (self.last_applied_version is not None and remote_version < self.last_applied_version)):
            raise ConnectionError("Invalid or rolled-back map version; retained previous map")

        # If we have not applied this version yet:
        if self.last_applied_version is None or remote_version > self.last_applied_version or self.known_map_version is None:
            logger.info("Detected new authoritative map version v%d (previous: %s)", remote_version, self.last_applied_version)
            self._fetch_and_apply_full_map(remote_version)
            changed = True
        else:
            changed = False
        # Rejection does not change the map version. Poll the report independently.
        self._poll_report_statuses()
        self.map_synchronized = True
        self._refresh_status()
        return changed

    def _fetch_and_apply_full_map(self, version: int) -> None:
        """Downloads full map and checks if assigned edge B-C is approved blocked."""
        status_code, map_resp = self._http_request("GET", "/map")
        if status_code != 200:
            raise ConnectionError(f"Failed to fetch full map (HTTP {status_code})")

        graph = validated_cloud_map(map_resp, version)
        new_route = list(graph.route(self.assigned_node, self.destination_node))
        blocked = frozenset(self.assigned_edge) in graph.blocked
        route_changed = new_route != self.proposed_route or blocked != self.is_edge_blocked_in_cloud
        # Persist first, then replace the complete graph atomically from the
        # camera's perspective. Missing edges never inherit old local costs.
        self._persist_state(cloud_map=map_resp)
        self._cloud_map = map_resp
        self.route_map = graph
        self.proposed_route = new_route
        self.last_applied_version = map_resp["version"]
        self.known_map_version = map_resp["version"]
        self.is_edge_blocked_in_cloud = blocked
        if route_changed and blocked:
            self._announce_route_if_new(map_resp["version"])

    def _announce_route_if_new(self, map_version: int) -> bool:
        """Announces the new proposed alternative route once per map version."""
        if self._announced_map_version == map_version:
            # Already announced this map version
            return False

        self._persist_state(announced_version=map_version)
        self._announced_map_version = map_version
        route_str = ", ".join(self.proposed_route) if self.proposed_route else "none"
        message = (f"Approved map update received from configured service. "
                   f"Route B to C is closed. Proposed alternative route: {route_str}."
                   if self.proposed_route else
                   "Approved map update received. No proposed route is available. Please remain stopped.")
        self.last_announcement = message
        logger.info("ANNOUNCEMENT: %s", message)

        if self.voice:
            try:
                # A map proposal must never clear queued camera STOP warnings.
                self.voice.speak(message, force=True, priority=False)
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
        meta = asdict(record)
        meta.pop("jpeg_bytes")
        meta["context"] = self._context()
        with self._persistence_lock:
            if record.jpeg_bytes:
                if img_file.exists():
                    if hashlib.sha256(img_file.read_bytes()).hexdigest() != record.jpeg_sha256:
                        raise OSError("Saved evidence checksum mismatch")
                else:
                    self._atomic_write(img_file, record.jpeg_bytes)
            self._atomic_write(record_file, json.dumps(meta, indent=2).encode("utf-8"))

    @staticmethod
    def _atomic_write(path, content):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)

    def _context(self):
        return {"api_base_url": self.api_base_url, "api_prefix": self.api_prefix,
                "camera_id": self.camera_id, "assigned_node": self.assigned_node,
                "assigned_edge": list(self.assigned_edge), "destination_node": self.destination_node}

    def _persist_state(self, cloud_map=None, announced_version=None):
        with self._persistence_lock:
            current_map = self._cloud_map if cloud_map is None else cloud_map
            state = {"context": self._context(), "map": current_map,
                     "episode_active": self._episode_active,
                     "announced_map_version": self._announced_map_version if announced_version is None else announced_version}
            self._atomic_write(self.outbox_dir / "client-state.json", json.dumps(state).encode("utf-8"))
            if cloud_map is not None:
                self._cloud_map = cloud_map

    def _restore_state(self):
        path = self.outbox_dir / "client-state.json"
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["context"] != self._context() or type(state["episode_active"]) is not bool:
                raise ValueError("Client context changed")
            announced = state["announced_map_version"]
            if announced is not None and (type(announced) is not int or announced < 1):
                raise ValueError("Invalid announcement checkpoint")
            if state["map"] is not None:
                graph = validated_cloud_map(state["map"])
                if announced is not None and announced > graph.version:
                    raise ValueError("Announcement ahead of stored map")
                self._cloud_map = state["map"]
                self.route_map = graph
                self.last_applied_version = graph.version
                # A disk cache is useful offline, but isn't a fresh server read.
                self.proposed_route = list(graph.route(self.assigned_node, self.destination_node))
                self.is_edge_blocked_in_cloud = frozenset(self.assigned_edge) in graph.blocked
            self._announced_map_version = announced
            self._episode_active = state["episode_active"]
        except (OSError, ValueError, KeyError, TypeError):
            self._recovery_error = True

    def _restore_outbox(self):
        recovered = []
        for path in sorted(self.outbox_dir.glob("*.json")):
            if path.name == "client-state.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.pop("context") != self._context() or str(uuid.UUID(data["report_id"])) != path.stem:
                    raise ValueError("Invalid report context or ID")
                data["assigned_edge"] = tuple(data["assigned_edge"])
                if (data["status"] not in ("PENDING", "APPROVED", "REJECTED") or
                        data["camera_id"] != self.camera_id or data["assigned_edge"] != self.assigned_edge or
                        data["assigned_node"] != self.assigned_node or data["destination_node"] != self.destination_node):
                    raise ValueError("Invalid assignment")
                image = path.with_suffix(".jpg")
                jpeg = image.read_bytes() if image.exists() else b""
                if (not jpeg and data["status"] == "PENDING") or (
                        jpeg and hashlib.sha256(jpeg).hexdigest() != data["jpeg_sha256"]):
                    raise ValueError("Saved evidence missing or changed")
                record = DeviceReportRecord(**data, jpeg_bytes=jpeg)
                self._reports[record.report_id] = record
                if record.status == "PENDING" and not record.submitted_at:
                    recovered.append(record)
            except (OSError, ValueError, TypeError, KeyError):
                # Preserve the files for deliberate reconciliation. Never silently
                # skip a damaged report and mint a replacement event ID.
                self._recovery_error = True
                logger.error("Outbox recovery needs attention for %s", path.name)
        self._current_report = next((r for r in self._reports.values() if r.status == "PENDING"), None)
        if self._current_report:
            self._episode_active = True
        if not self._recovery_error:
            for record in recovered:
                self._submission_queue.put(record)
        self._refresh_status()
