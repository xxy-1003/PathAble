"""Run locally with local_server.py; Lambda entrypoint is lambda_handler.handler."""
import base64
import binascii
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    CameraAssignment, CanonicalReportInput, CanonicalReviewResult, CanonicalReportRecord,
    PhotoUpload, PresignRequest, PresignResponse,
    ReportInput, ReviewInput, PhotoCreated, ReportRecord,
    ReportPage, TicketPage, ReviewResult, PhotoLink, MapVersion, SharedMap, Health,
)
from .storage import Conflict, DynamoStore, MemoryPhotos, MemoryStore, S3Photos


def now():
    return datetime.now(timezone.utc).isoformat()


def create_app(store=None, photos=None, *, aws=False, assignment=None, camera_subject=None,
               reviewer_subjects=(), allowed_origins=()):
    if aws and (store is None or photos is None or not camera_subject or not reviewer_subjects):
        raise RuntimeError("AWS mode requires durable storage and a configured camera subject")
    if aws and camera_subject in reviewer_subjects:
        raise RuntimeError("Camera and reviewer identities must be separate")
    store = store if store is not None else MemoryStore()
    photos = photos if photos is not None else MemoryPhotos()
    assignment = assignment or CameraAssignment()
    camera_id = assignment.camera_id
    app = FastAPI(title="PathAble Fixed Camera API", version="2.0.0")
    app.state.store = store
    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(allowed_origins),
                           allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Authorization", "Content-Type",
                                          "Content-Length", "If-None-Match",
                                          "x-amz-checksum-sha256",
                                          "x-amz-server-side-encryption"])

    def permission(*scopes):
        def authenticate(request: Request):
            if not aws:
                return "local-reviewer"
            jwt = request.scope.get("aws.event", {}).get("requestContext", {}).get(
                "authorizer", {}).get("jwt", {})
            claims = jwt.get("claims", {})
            subject = claims.get("sub")
            granted = set(jwt.get("scopes", [])) | set(claims.get("scope", "").split())
            if not subject:
                raise HTTPException(401, "Authenticated JWT context required")
            if not granted.intersection(scopes):
                raise HTTPException(403, "Required scope missing")
            if scopes == ("pathable/camera",) and subject != camera_subject:
                raise HTTPException(403, "Camera identity does not match configured subject")
            if "pathable/reviewer" in scopes and "pathable/reviewer" in granted and subject not in reviewer_subjects:
                raise HTTPException(403, "Reviewer identity is not authorised")
            return subject
        return authenticate

    camera = Depends(permission("pathable/camera"))
    reviewer = Depends(permission("pathable/reviewer"))
    reader = Depends(permission("pathable/map", "pathable/reviewer"))
    anyone = Depends(permission("pathable/camera", "pathable/reviewer", "pathable/map"))

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def storage_error(request, exc):
        # Never expose SDK errors, tokens, photo bodies or signed URLs.
        return JSONResponse(status_code=503, content={"detail": "Service unavailable; retry with backoff"})

    def configured_camera(value):
        if value != camera_id:
            raise HTTPException(422, "Camera is not assigned to B / B-C")

    def report_or_404(report_id):
        report = store.get(f"REPORT#{report_id}")
        if report is None:
            raise HTTPException(404, "Report not found")
        return report

    def _validate_jpeg(data: bytes) -> None:
        from io import BytesIO
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format != "JPEG" or image.width * image.height > 20_000_000:
                    raise ValueError("Expected JPEG up to 20 megapixels")
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(422, "Invalid or oversized JPEG image")

    def _verify_photo_ownership(photo_id, sha256=None):
        """Return photo metadata or raise 422. Optionally verify sha256 checksum."""
        photo = store.get(f"PHOTO#{photo_id}")
        if (not photo or photo["camera_id"] != camera_id or
                photo["expires_at"] <= datetime.now(timezone.utc).timestamp()):
            raise HTTPException(422, "Upload a photo for this camera first")
        if sha256 is not None and photo["sha256"] != sha256:
            raise HTTPException(422, "Photo checksum does not match the report")
        return photo

    def _ensure_canonical_photo(photo_id, sha256):
        """Verify a direct-upload slot and object, then register its private photo.

        In AWS mode the PUT goes directly to S3, so the API must promote the
        pending slot into PHOTO metadata after checking the actual stored bytes.
        """
        existing = store.get(f"PHOTO#{photo_id}")
        if existing is not None:
            _verify_photo_ownership(photo_id, sha256=sha256)
            return

        slot = store.get(f"SLOT#{photo_id}")
        now_ts = datetime.now(timezone.utc).timestamp()
        if (not slot or slot.get("camera_id") != camera_id or
                slot.get("expires_at", 0) <= now_ts or slot.get("sha256") != sha256):
            raise HTTPException(422, "Upload a matching photo for this camera first")

        data = photos.verify_uploaded(photo_id, sha256, slot["size_bytes"])
        if data is None:
            raise HTTPException(422, "Uploaded photo is missing or failed integrity validation")
        _validate_jpeg(data)
        record = {
            "photo_id": photo_id, "camera_id": camera_id, "sha256": sha256,
            "created_at": slot.get("created_at", now()),
            "expires_at": slot["expires_at"],
        }
        try:
            store.put_new(f"PHOTO#{photo_id}", record)
        except Conflict:
            # Another identical submission may have promoted the same object.
            _verify_photo_ownership(photo_id, sha256=sha256)

    # â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.get("/api/v2/health", response_model=Health)
    def health(subject=anyone):
        return {"status": "healthy", "storage": store.mode,
                "map_version": store.get_map()["version"]}

    # â”€â”€ Legacy base64 photo upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.post("/api/v2/photos", status_code=201, response_model=PhotoCreated)
    def upload_photo(body: PhotoUpload, subject=camera):
        configured_camera(body.camera_id)
        try:
            data = base64.b64decode(body.jpeg_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Invalid base64")
        if len(data) > 512 * 1024:
            raise HTTPException(413, "JPEG exceeds 512 KiB")
        _validate_jpeg(data)
        photo_id = str(uuid4())
        digest = hashlib.sha256(data).hexdigest()
        photos.put(photo_id, data)
        store.put_new(f"PHOTO#{photo_id}", {"photo_id": photo_id, "camera_id": camera_id,
                      "sha256": digest, "created_at": now(),
                      "expires_at": int(datetime.now(timezone.utc).timestamp()) + 7 * 86400})
        return {"photo_id": photo_id, "sha256": digest}

    # â”€â”€ v1.1 presigned direct upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.post("/api/v2/uploads/presign", status_code=201, response_model=PresignResponse)
    def presign_upload(body: PresignRequest, subject=camera):
        configured_camera(body.client_id)
        if body.size_bytes > 512 * 1024:
            raise HTTPException(413, "Declared size exceeds 512 KiB")
        photo_id = str(uuid4())
        slot = photos.presign(photo_id, body.sha256, body.size_bytes, body.content_type)
        # Store a pending slot so /reports can verify the upload occurred
        store.put_new(f"SLOT#{photo_id}", {
            "photo_id": photo_id, "camera_id": camera_id,
            "sha256": body.sha256, "size_bytes": body.size_bytes,
            "created_at": now(),
            "expires_at": int(datetime.now(timezone.utc).timestamp()) + 7 * 86400,
        })
        return slot

    # â”€â”€ Local-only direct PUT receiver (mirrors what S3 would do) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    if not aws:
        @app.put("/api/v2/uploads/{photo_id}", include_in_schema=False)
        async def local_direct_put(photo_id: UUID, request: Request):
            data = await request.body()
            slot = store.get(f"SLOT#{str(photo_id)}")
            if slot is None:
                raise HTTPException(404, "No presign slot found for this photo")
            if len(data) != slot["size_bytes"]:
                raise HTTPException(400, "Content-Length does not match declared size")
            if hashlib.sha256(data).hexdigest() != slot["sha256"]:
                raise HTTPException(400, "SHA-256 checksum mismatch")
            _validate_jpeg(data)
            digest = slot["sha256"]
            photos.put(str(photo_id), data)
            # Promote slot to a proper PHOTO record
            try:
                store.put_new(f"PHOTO#{str(photo_id)}", {
                    "photo_id": str(photo_id), "camera_id": slot["camera_id"],
                    "sha256": digest, "created_at": now(),
                    "expires_at": slot["expires_at"],
                })
            except Conflict:
                pass  # Already promoted (idempotent retry)
            return Response(status_code=200)

        @app.get("/api/v2/photos/{photo_id}/content", include_in_schema=False)
        def local_photo(photo_id: UUID, subject=reviewer):
            data = photos.photos.get(str(photo_id))
            if data is None:
                raise HTTPException(404, "Photo not found")
            return Response(content=data, media_type="image/jpeg")

    # â”€â”€ Legacy compact report submission â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # â”€â”€ Report submission: legacy compact and canonical v1.1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _submit_canonical_report(body: CanonicalReportInput, response: Response):
        configured_camera(body.client_id)
        key = f"REPORT#{body.event_id}"
        payload = body.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        def existing_result():
            existing = store.get(key)
            if existing and existing.get("payload_sha256") == digest:
                response.status_code = 200
                return existing
            raise Conflict("Event ID already used with a different payload")

        if store.get(key):
            return existing_result()

        photo_id = str(body.image.photo_id)
        _ensure_canonical_photo(photo_id, body.image.sha256)
        ticket_id = f"T-{body.event_id}"
        created = {
            **payload,
            "payload_sha256": digest,
            "received_at": now(),
            "ticket_id": ticket_id,
            # Legacy compact aliases keep older reviewer tooling compatible.
            "report_id": str(body.event_id),
            "camera_id": body.client_id,
            "photo_id": photo_id,
            "observed_at": body.timestamp.isoformat(),
            "obstacle_class": body.detection_evidence.obstacle_class,
            "confidence": body.detection_evidence.confidence,
            "overlap_count": body.detection_evidence.overlap_count,
            "frame_count": body.detection_evidence.frame_count,
            "node": assignment.node,
            "edge_key": assignment.edge_key,
            "status": "PENDING",
            "expected_map_version": store.get_map()["version"],
            "review": None,
        }
        try:
            store.put_new(key, created)
        except Conflict:
            return existing_result()
        return created

    @app.post("/api/v2/reports", status_code=201)
    def submit_report(body: ReportInput | CanonicalReportInput, response: Response, subject=camera):
        # The canonical v1.1 schema is the preferred format; the compact schema
        # remains accepted for compatibility with the earlier camera client.
        if isinstance(body, CanonicalReportInput):
            return _submit_canonical_report(body, response)

        configured_camera(body.camera_id)
        payload = body.model_dump(mode="json")
        key = f"REPORT#{body.report_id}"
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        def existing_result():
            existing = store.get(key)
            if existing and existing["payload_sha256"] == digest:
                response.status_code = 200
                return existing
            raise Conflict("Report ID already used with a different payload")

        if store.get(key):
            return existing_result()
        _verify_photo_ownership(str(body.photo_id))
        created = {**payload, "payload_sha256": digest, "received_at": now(),
                   "node": assignment.node, "edge_key": assignment.edge_key, "status": "PENDING",
                   "expected_map_version": store.get_map()["version"], "review": None}
        try:
            store.put_new(key, created)
        except Conflict:
            return existing_result()
        return created

    # Retain the early v1.1 path as an alias for clients already using it.
    @app.post("/api/v2/events", status_code=201)
    def submit_canonical_event(body: CanonicalReportInput, response: Response, subject=camera):
        return _submit_canonical_report(body, response)

    # â”€â”€ Report reads â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.get("/api/v2/reports", response_model=ReportPage)
    def list_reports(status: Literal["PENDING", "APPROVED", "REJECTED"] | None = None,
                     limit: int = Query(50, ge=1, le=100),
                     cursor: str | None = Query(None, max_length=100), subject=reviewer):
        if cursor and not cursor.startswith(("REPORT#", "MAP#", "PHOTO#")):
            raise HTTPException(422, "Invalid cursor")
        return store.list_reports(status, limit, cursor)

    @app.get("/api/v2/reports/{report_id}", response_model=ReportRecord | CanonicalReportRecord)
    def get_report(report_id: UUID, subject=reviewer):
        return report_or_404(report_id)

    @app.get("/api/v2/reports/{report_id}/photo", response_model=PhotoLink)
    def get_photo_url(report_id: UUID, subject=reviewer):
        report = report_or_404(report_id)
        photo_id = report.get("photo_id") or (report.get("image") or {}).get("photo_id")
        photo = store.get(f"PHOTO#{photo_id}")
        if not photo or photo["expires_at"] <= datetime.now(timezone.utc).timestamp():
            raise HTTPException(410, "Photo retention period ended")
        return {"url": photos.url(photo_id), "expires_in": 300}

    # â”€â”€ v1.1 Ticket aliases â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.get("/api/v2/tickets", response_model=TicketPage)
    def list_tickets(status: Literal["PENDING", "APPROVED", "REJECTED"] | None = None,
                     limit: int = Query(50, ge=1, le=100),
                     cursor: str | None = Query(None, max_length=100), subject=reviewer):
        """Alias for GET /reports; returns the same records with ticket_id included."""
        if cursor and not cursor.startswith(("REPORT#", "MAP#", "PHOTO#")):
            raise HTTPException(422, "Invalid cursor")
        return store.list_reports(status, limit, cursor)

    @app.get("/api/v2/tickets/T-{event_id}", response_model=dict)
    def get_ticket(event_id: UUID, subject=reviewer):
        """Alias for GET /reports/{report_id}."""
        return report_or_404(event_id)

    @app.post("/api/v2/tickets/T-{event_id}/review")
    def review_ticket(event_id: UUID, body: ReviewInput, subject=reviewer):
        """Alias for POST /reports/{report_id}/review. Returns CanonicalReviewResult."""
        return _do_review(event_id, body, subject)

    # â”€â”€ Review (shared logic) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.post("/api/v2/reports/{report_id}/review", response_model=ReviewResult)
    def review_report(report_id: UUID, body: ReviewInput, subject=reviewer):
        return _do_review(report_id, body, subject)

    def _do_review(report_id, body: ReviewInput, subject: str):
        key = f"REPORT#{report_id}"

        def repeated(report):
            prior = report["review"]
            if prior and all(prior[k] == value for k, value in {
                "action": body.action, "expected_map_version": body.expected_map_version,
                "notes": body.notes, "reviewer_id": subject}.items()):
                return {"report": report, "map_version": prior["map_version"]}
            raise Conflict("Report already reviewed with a different decision")

        report = report_or_404(report_id)
        if report["status"] != "PENDING":
            return repeated(report)
        current = store.get_map()
        if current["version"] != body.expected_map_version:
            raise Conflict("Map version changed; refresh before reviewing")
        updated_map = None
        if body.action == "APPROVE":
            current["version"] += 1
            for edge in current["edges"]:
                if {edge["from"], edge["to"]} == {"B", "C"}:
                    edge["blocked"] = True
            updated_map = current
        report["status"] = "APPROVED" if body.action == "APPROVE" else "REJECTED"
        report["review"] = {**body.model_dump(), "reviewer_id": subject,
                            "reviewed_at": now(), "map_version": current["version"]}
        try:
            store.review(key, report, body.expected_map_version, updated_map)
        except Conflict:
            latest = report_or_404(report_id)
            if latest["status"] != "PENDING":
                return repeated(latest)
            raise
        return {"report": report, "map_version": current["version"]}

    # â”€â”€ Map reads â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @app.get("/api/v2/map/version", response_model=MapVersion)
    def map_version(subject=reader):
        current = store.get_map()
        return {"map_id": current["map_id"], "version": current["version"]}

    @app.get("/api/v2/map", response_model=SharedMap)
    def get_map(subject=reader):
        return store.get_map()

    return app


def aws_app():
    return create_app(DynamoStore(os.environ["STATE_TABLE"]),
                      S3Photos(os.environ["PHOTOS_BUCKET"]), aws=True,
                      assignment=CameraAssignment(camera_id=os.environ["CAMERA_ID"],
                          node=os.environ["CAMERA_NODE"], edge_key=os.environ["CAMERA_EDGE"]),
                      camera_subject=os.environ["CAMERA_SUBJECT"],
                      reviewer_subjects=os.environ["REVIEWER_SUBJECTS"].split(","),
                      allowed_origins=[os.environ["DASHBOARD_ORIGIN"]])
