import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from production.v3.cloud.fixed_camera.app import create_app
from production.v3.cloud.fixed_camera.storage import MemoryStore, MemoryPhotos


def jpeg():
    output = BytesIO()
    Image.new("RGB", (8, 8), "gray").save(output, format="JPEG")
    return output.getvalue()


def report(client, **changes):
    photo = client.post("/api/v2/photos", json={"camera_id": "camera-b-01",
        "jpeg_base64": base64.b64encode(jpeg()).decode()})
    assert photo.status_code == 201, photo.text
    payload = {"report_id": str(uuid4()), "photo_id": photo.json()["photo_id"],
        "camera_id": "camera-b-01", "observed_at": "2026-10-25T09:00:00Z",
        "obstacle_class": "chair", "confidence": 0.85, "overlap_count": 6,
        "frame_count": 10, "distance_m": None, "clearance_m": None,
        "measurement_source": None, **changes}
    result = client.post("/api/v2/reports", json=payload)
    return payload, result


def review(client, report_id, action="APPROVE", version=1, notes="checked photo"):
    return client.post(f"/api/v2/reports/{report_id}/review", json={
        "action": action, "expected_map_version": version, "notes": notes})


def bc(client):
    return next(e for e in client.get("/api/v2/map").json()["edges"] if
                {e["from"], e["to"]} == {"B", "C"})


def test_pending_approval_retry_and_unknown_metrics():
    client = TestClient(create_app())
    payload, response = report(client)
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert response.json()["clearance_m"] is None
    assert bc(client)["blocked"] is False
    assert bc(client)["distance"] is None
    assert client.post("/api/v2/reports", json=payload).status_code == 200
    changed = {**payload, "confidence": 0.4}
    assert client.post("/api/v2/reports", json=changed).status_code == 409
    first = review(client, payload["report_id"])
    assert first.status_code == 200, first.text
    assert first.json()["map_version"] == 2
    assert bc(client)["blocked"] is True
    assert review(client, payload["report_id"]).json() == first.json()
    assert review(client, payload["report_id"], "REJECT").status_code == 409
    assert client.get("/api/v2/map/version").json()["version"] == 2


@pytest.mark.parametrize("changes", [
    {"distance_m": 0.1}, {"clearance_m": 1.2}, {"measurement_source": "guessed"},
    {"camera_id": "other"}, {"overlap_count": 11}, {"confidence": 1.1},
    {"confidence": "NaN"}, {"observed_at": "2026-10-25T09:00:00"},
    {"node": "C"}, {"overlap_count": True}])
def test_invalid_or_fabricated_evidence_rejected(changes):
    client = TestClient(create_app())
    assert report(client, **changes)[1].status_code == 422


def test_reject_does_not_reopen_and_stale_review_conflicts():
    client = TestClient(create_app())
    p1, _ = report(client)
    p2, _ = report(client)
    assert review(client, p1["report_id"]).status_code == 200
    assert review(client, p2["report_id"], "REJECT").status_code == 409
    assert review(client, p2["report_id"], "REJECT", version=2).status_code == 200
    assert bc(client)["blocked"] is True
    assert client.get("/api/v2/map/version").json()["version"] == 2


def test_private_photo_and_missing_photo():
    client = TestClient(create_app())
    payload, _ = report(client)
    url = client.get(f'/api/v2/reports/{payload["report_id"]}/photo').json()["url"]
    assert client.get(url).content == jpeg()
    assert report(client, photo_id=str(uuid4()))[1].status_code == 422
    assert client.post("/api/v2/photos", json={"camera_id": "camera-b-01",
        "jpeg_base64": base64.b64encode(b"not an image").decode()}).status_code == 422


def test_report_list_pagination():
    client = TestClient(create_app())
    for _ in range(3):
        report(client)
    first = client.get("/api/v2/reports?status=PENDING&limit=2").json()
    second = client.get("/api/v2/reports", params={"cursor": first["next_cursor"]}).json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not second["next_cursor"]


def test_parallel_reviews_only_one_map_commit():
    client = TestClient(create_app())
    reports = [report(client)[0] for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda p: review(client, p["report_id"]).status_code, reports))
    assert sorted(results) == [200, 409]
    assert client.get("/api/v2/map/version").json()["version"] == 2
    assert sum(r["status"] == "APPROVED" for r in
               client.get("/api/v2/reports").json()["items"]) == 1


def test_aws_mode_fails_closed_and_does_not_trust_body_identity():
    with pytest.raises(RuntimeError):
        create_app(aws=True)
    with pytest.raises(RuntimeError):
        create_app(MemoryStore(), MemoryPhotos(), aws=True,
                   camera_subject="same-user", reviewer_subjects=["same-user"])
    client = TestClient(create_app(MemoryStore(), MemoryPhotos(), aws=True,
                                   camera_subject="camera-user", reviewer_subjects=["reviewer-user"]))
    assert client.get("/api/v2/map").status_code == 401


def test_storage_failure_does_not_return_success():
    class BrokenStore(MemoryStore):
        def review(self, *args):
            raise RuntimeError("secret SDK error")
    client = TestClient(create_app(BrokenStore()), raise_server_exceptions=False)
    payload, _ = report(client)
    response = review(client, payload["report_id"])
    assert response.status_code == 503
    assert "secret" not in response.text
    assert bc(client)["blocked"] is False
    assert client.get(f'/api/v2/reports/{payload["report_id"]}').json()["status"] == "PENDING"


def test_photo_retention_and_review_identity_cannot_be_supplied_by_client():
    store = MemoryStore()
    client = TestClient(create_app(store))
    payload, _ = report(client)
    bad_review = {"action": "APPROVE", "expected_map_version": 1,
                  "reviewer_id": "pretend-admin"}
    assert client.post(f'/api/v2/reports/{payload["report_id"]}/review', json=bad_review).status_code == 422
    photo = store.items[f'PHOTO#{payload["photo_id"]}']
    photo["expires_at"] = 1
    assert client.get(f'/api/v2/reports/{payload["report_id"]}/photo').status_code == 410
    assert report(client, photo_id=payload["photo_id"])[1].status_code == 422


def test_configured_placement_and_generated_contract_are_valid():
    import json
    from pathlib import Path
    from pydantic import ValidationError
    from production.v3.cloud.fixed_camera.models import CameraAssignment
    from production.v3.cloud.fixed_camera.export_openapi import contract
    with pytest.raises(ValidationError):
        CameraAssignment(node="C", edge_key="C-D")
    saved = Path(__file__).parents[1] / "openapi.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == contract()


def test_canonical_presigned_upload_then_report_uses_canonical_reports_route():
    import hashlib
    from uuid import uuid4

    store, photos = MemoryStore(), MemoryPhotos()
    client = TestClient(create_app(store, photos))
    image = jpeg()
    digest = hashlib.sha256(image).hexdigest()
    slot = client.post("/api/v2/uploads/presign", json={
        "client_id": "camera-b-01", "content_type": "image/jpeg",
        "size_bytes": len(image), "sha256": digest,
    })
    assert slot.status_code == 201, slot.text
    photo_id = slot.json()["photo_id"]
    # Simulate a successful direct-to-S3 PUT: the API has a SLOT record,
    # but no PHOTO record until report intake verifies the actual object bytes.
    photos.put(photo_id, image)
    assert store.get(f"PHOTO#{photo_id}") is None

    event_id = str(uuid4())
    canonical = {
        "schema_id": "pathable.human-review.report.v1",
        "event_id": event_id,
        "client_id": "camera-b-01",
        "timestamp": "2026-10-25T09:00:00Z",
        "edge_key": "B-C",
        "junction": "B",
        "destination": "D",
        "detection_evidence": {
            "obstacle_class": "chair", "confidence": 0.85,
            "overlap_count": 6, "frame_count": 10,
            "evidence_status": "client_reported",
        },
        "image": {"photo_id": photo_id, "sha256": digest},
        "distance_m": None, "clearance_m": None, "measurement_source": None,
    }
    submitted = client.post("/api/v2/reports", json=canonical)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "PENDING"
    assert submitted.json()["ticket_id"] == f"T-{event_id}"
    assert submitted.json()["event_id"] == event_id
    assert client.post("/api/v2/reports", json=canonical).status_code == 200
    assert client.get(f"/api/v2/tickets/T-{event_id}").status_code == 200
    assert client.get(f"/api/v2/reports/{event_id}").status_code == 200
    reviewed = client.post(f"/api/v2/tickets/T-{event_id}/review", json={
        "action": "APPROVE", "expected_map_version": 1, "notes": "verified test image",
    })
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["map_version"] == 2
    assert reviewed.json()["report"]["status"] == "APPROVED"
