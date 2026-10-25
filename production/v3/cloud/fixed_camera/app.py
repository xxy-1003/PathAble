"""Run locally with local_server.py; Lambda entrypoint is lambda_handler.handler."""
import base64
import binascii
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (CameraAssignment, PhotoUpload, ReportInput, ReviewInput, PhotoCreated, ReportRecord,
                     ReportPage, ReviewResult, PhotoLink, MapVersion, SharedMap, Health,
                     HumanReportInput, PresignInput, PresignResult)
from .storage import Conflict, DynamoStore, MemoryPhotos, MemoryStore, S3Photos
from .evidence import verify_jpeg


audit_logger = logging.getLogger("pathable.fixed_camera.audit")
audit_logger.setLevel(logging.INFO)


def audit(action, **fields):
    # Callers supply only operational identifiers, actions and version numbers.
    audit_logger.info(json.dumps({"action": action, "timestamp": now(), **fields}, sort_keys=True))


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
    app = FastAPI(title="PathAble Fixed Camera API", version="2.1.0")
    app.state.store = store
    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(allowed_origins),
                           allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

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
            eligible = granted.intersection(scopes)
            if subject != camera_subject:
                eligible.discard("pathable/camera")
            if subject not in reviewer_subjects:
                eligible.discard("pathable/reviewer")
            if not eligible:
                raise HTTPException(403, "Required scope or authorised identity missing")
            return subject
        return authenticate

    camera = Depends(permission("pathable/camera"))
    reviewer = Depends(permission("pathable/reviewer"))
    reporter_or_reviewer = Depends(permission("pathable/camera", "pathable/reviewer"))
    reader = Depends(permission("pathable/map", "pathable/reviewer"))
    anyone = Depends(permission("pathable/camera", "pathable/reviewer", "pathable/map"))

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def storage_error(request, exc):
        # Never expose SDK errors, tokens, photo bodies or signed URLs.
        audit("SERVICE_ERROR", error_type=type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Service unavailable; retry with backoff"})

    def configured_camera(value):
        if value != camera_id:
            raise HTTPException(422, "Camera is not assigned to B / B-C")

    def report_or_404(report_id):
        report = store.get(f"REPORT#{report_id}")
        if report is None:
            raise HTTPException(404, "Report not found")
        return report

    def ticket_event_id(ticket_id):
        try:
            if not ticket_id.startswith("T-"):
                raise ValueError()
            return UUID(ticket_id[2:])
        except ValueError:
            raise HTTPException(422, "Invalid ticket ID")

    def photo_metadata(photo_id):
        photo = store.get(f"PHOTO#{photo_id}")
        if (not photo or photo["camera_id"] != camera_id or
                photo["expires_at"] <= datetime.now(timezone.utc).timestamp()):
            raise HTTPException(422, "Upload a photo for this camera first")
        return photo

    @app.post("/api/v2/uploads/presign", response_model=PresignResult)
    def presign_upload(body: PresignInput, subject=camera):
        configured_camera(body.client_id)
        photo_id = str(uuid4())
        timestamp = int(datetime.now(timezone.utc).timestamp())
        store.put_new(f"PHOTO#{photo_id}", {"photo_id": photo_id, "camera_id": camera_id,
            "sha256": body.sha256, "size_bytes": body.size_bytes, "created_at": now(),
            "upload_until": timestamp + 300, "expires_at": timestamp + 7 * 86400})
        result = photos.presign(photo_id, body.size_bytes, body.sha256)
        audit("UPLOAD_SLOT_CREATED", photo_id=photo_id, client_id=camera_id)
        return result

    @app.get("/api/v2/health", response_model=Health)
    def health(subject=anyone):
        return {"status": "healthy", "storage": store.mode,
                "map_version": store.get_map()["version"]}

    @app.post("/api/v2/photos", status_code=201, response_model=PhotoCreated)
    def upload_photo(body: PhotoUpload, subject=camera):
        configured_camera(body.camera_id)
        try:
            data = base64.b64decode(body.jpeg_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Invalid base64")
        if len(data) > 512 * 1024:
            raise HTTPException(413, "JPEG exceeds 512 KiB")
        try:
            digest = verify_jpeg(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        photo_id = str(uuid4())
        photos.put(photo_id, data)
        store.put_new(f"PHOTO#{photo_id}", {"photo_id": photo_id, "camera_id": camera_id,
                      "sha256": digest, "size_bytes": len(data), "created_at": now(),
                      "expires_at": int(datetime.now(timezone.utc).timestamp()) + 7 * 86400})
        audit("PHOTO_STORED", photo_id=photo_id, client_id=camera_id)
        return {"photo_id": photo_id, "sha256": digest}

    @app.post("/api/v2/reports", status_code=201, response_model=ReportRecord)
    def submit_report(body: HumanReportInput | ReportInput, response: Response, subject=camera):
        canonical = body if isinstance(body, HumanReportInput) else None
        if canonical:
            body = canonical.compact()
        configured_camera(body.camera_id)
        payload = body.model_dump(mode="json")
        key = f"REPORT#{body.report_id}"
        hash_payload = canonical.model_dump(mode="json") if canonical else payload
        digest = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()

        def existing_result():
            existing = store.get(key)
            if existing and existing["payload_sha256"] == digest:
                response.status_code = 200
                audit("REPORT_DUPLICATE", event_id=str(body.report_id), ticket_id=existing["ticket_id"])
                return existing
            raise Conflict("Report ID already used with a different payload")

        if store.get(key):
            return existing_result()
        photo = photo_metadata(body.photo_id)
        if canonical and canonical.image.sha256 != photo["sha256"]:
            raise HTTPException(422, "Report image checksum does not match upload slot")
        try:
            verify_jpeg(photos.get(str(body.photo_id)), sha256=photo["sha256"],
                        size_bytes=photo.get("size_bytes"))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        created = {**payload, "payload_sha256": digest, "received_at": now(),
                   "node": assignment.node, "edge_key": assignment.edge_key, "status": "PENDING",
                   "expected_map_version": store.get_map()["version"], "review": None,
                   "schema_id": canonical.schema_id if canonical else "pathable.fixed-camera.compact.v1",
                   "event_id": str(body.report_id), "client_id": body.camera_id,
                   "timestamp": body.observed_at.isoformat(), "junction": assignment.node,
                   "destination": "D", "ticket_id": f"T-{body.report_id}",
                   "image": {"photo_id": str(body.photo_id), "sha256": photo["sha256"]},
                   "detection_evidence": {k: payload[k] for k in
                       ("obstacle_class", "confidence", "overlap_count", "frame_count")}}
        created["detection_evidence"]["evidence_status"] = "client_reported"
        try:
            store.put_new(key, created)
        except Conflict:
            return existing_result()
        audit("REPORT_PENDING", event_id=str(body.report_id), ticket_id=created["ticket_id"],
              client_id=camera_id, map_version=created["expected_map_version"])
        return created

    @app.get("/api/v2/tickets", response_model=ReportPage)
    @app.get("/api/v2/reports", response_model=ReportPage)
    def list_reports(status: Literal["PENDING", "APPROVED", "REJECTED"] | None = None,
                     limit: int = Query(50, ge=1, le=100),
                     cursor: str | None = Query(None, max_length=100), subject=reviewer):
        if cursor and not cursor.startswith(("REPORT#", "MAP#", "PHOTO#")):
            raise HTTPException(422, "Invalid cursor")
        return store.list_reports(status, limit, cursor)

    @app.get("/api/v2/reports/{report_id}", response_model=ReportRecord)
    def get_report(report_id: UUID, subject=reporter_or_reviewer):
        return report_or_404(report_id)

    @app.get("/api/v2/tickets/{ticket_id}", response_model=ReportRecord)
    def get_ticket(ticket_id: str, subject=reviewer):
        return report_or_404(ticket_event_id(ticket_id))

    @app.get("/api/v2/reports/{report_id}/photo", response_model=PhotoLink)
    def get_photo_url(report_id: UUID, subject=reviewer):
        report = report_or_404(report_id)
        photo = store.get(f'PHOTO#{report["photo_id"]}')
        if not photo or photo["expires_at"] <= datetime.now(timezone.utc).timestamp():
            raise HTTPException(410, "Photo retention period ended")
        return {"url": photos.url(report["photo_id"]), "expires_in": 300}

    if not aws and isinstance(photos, MemoryPhotos):
        @app.put("/api/v2/uploads/{photo_id}/content", include_in_schema=False)
        async def local_upload(photo_id: UUID, request: Request, subject=camera):
            photo = photo_metadata(photo_id)
            if photo.get("upload_until", 0) <= datetime.now(timezone.utc).timestamp():
                raise HTTPException(403, "Upload slot expired")
            data = await request.body()
            try:
                verify_jpeg(data, sha256=photo["sha256"], size_bytes=photo["size_bytes"])
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            try:
                photos.put(str(photo_id), data)
            except Conflict:
                raise HTTPException(412, "Photo already uploaded")
            return Response(status_code=200)

        @app.get("/api/v2/photos/{photo_id}/content", include_in_schema=False)
        def local_photo(photo_id: UUID, subject=reviewer):
            photo_metadata(photo_id)
            try:
                data = photos.get(str(photo_id))
            except ValueError:
                raise HTTPException(404, "Photo not found")
            return Response(content=data, media_type="image/jpeg")

    @app.get("/api/v2/map/version", response_model=MapVersion)
    def map_version(subject=reader):
        current = store.get_map()
        return {"map_id": current["map_id"], "version": current["version"]}

    @app.get("/api/v2/map", response_model=SharedMap)
    def get_map(subject=reader):
        return store.get_map()

    @app.post("/api/v2/reports/{report_id}/review", response_model=ReviewResult)
    def review_report(report_id: UUID, body: ReviewInput, subject=reviewer):
        key = f"REPORT#{report_id}"

        def repeated(report):
            prior = report["review"]
            if prior and all(prior[k] == value for k, value in {
                "action": body.action, "expected_map_version": body.expected_map_version,
                "notes": body.notes, "reviewer_id": subject}.items()):
                audit("REVIEW_DUPLICATE", event_id=str(report_id), ticket_id=report["ticket_id"],
                      map_version=prior["map_version"])
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
        audit("REVIEW_COMMITTED", event_id=str(report_id), ticket_id=report["ticket_id"],
              decision=body.action, reviewer_id=subject, map_version=current["version"])
        if updated_map is not None:
            audit("MAP_UPDATED", event_id=str(report_id), edge_key=assignment.edge_key,
                  previous_version=body.expected_map_version, map_version=current["version"])
        return {"report": report, "map_version": current["version"]}

    @app.post("/api/v2/tickets/{ticket_id}/review", response_model=ReviewResult)
    def review_ticket(ticket_id: str, body: ReviewInput, subject=reviewer):
        return review_report(ticket_event_id(ticket_id), body, subject)

    return app


def aws_app():
    return create_app(DynamoStore(os.environ["STATE_TABLE"]),
                      S3Photos(os.environ["PHOTOS_BUCKET"]), aws=True,
                      assignment=CameraAssignment(camera_id=os.environ["CAMERA_ID"],
                          node=os.environ["CAMERA_NODE"], edge_key=os.environ["CAMERA_EDGE"]),
                      camera_subject=os.environ["CAMERA_SUBJECT"],
                      reviewer_subjects=os.environ["REVIEWER_SUBJECTS"].split(","),
                      allowed_origins=[os.environ["DASHBOARD_ORIGIN"]])
