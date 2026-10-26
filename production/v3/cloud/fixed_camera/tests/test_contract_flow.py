"""Canonical fixtures, ticket flow, durable local restart and private direct uploads."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
import requests

from production.v3.cloud.fixed_camera.app import create_app
from production.v3.cloud.fixed_camera.local_storage import SQLiteStore, FilePhotos
from production.v3.cloud.fixed_camera.models import HumanReportInput, ReportRecord, ReviewResult
from production.v3.cloud.fixed_camera.storage import MemoryStore, MemoryPhotos
from .test_aws_adapters import aws_storage


FIXTURES = Path(__file__).parents[1] / "fixtures"


def fixtures():
    return json.loads((FIXTURES / "examples.json").read_text(encoding="utf-8"))


def canonical_report(client):
    sample = fixtures()
    upload = client.post("/api/v2/uploads/presign", json=sample["presign_request"])
    assert upload.status_code == 200, upload.text
    slot = upload.json()
    data = (FIXTURES / "synthetic-evidence.jpg").read_bytes()
    result = client.put(slot["url"], content=data, headers=slot["headers"])
    assert result.status_code == 200, result.text
    report = copy.deepcopy(sample["report_request"])
    report["event_id"] = str(uuid4())
    report["image"]["photo_id"] = slot["photo_id"]
    return report, client.post("/api/v2/reports", json=report)


@pytest.mark.parametrize("durable", [False, True])
def test_canonical_flow_pending_ticket_idempotency_approval(tmp_path, durable):
    app = create_app(SQLiteStore(tmp_path / "state.db"), FilePhotos(tmp_path / "photos")) if durable else create_app()
    client = TestClient(app)
    payload, response = canonical_report(client)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["event_id"] == payload["event_id"]
    assert created["image"] == payload["image"]
    assert created["ticket_id"] == f'T-{payload["event_id"]}'
    assert created["detection_evidence"]["evidence_status"] == "client_reported"
    assert created["distance_m"] is None and created["clearance_m"] is None
    assert client.get("/api/v2/map").json() == fixtures()["map_before"]
    assert client.post("/api/v2/reports", json=payload).status_code == 200
    tickets = client.get("/api/v2/tickets?status=PENDING").json()["items"]
    assert len(tickets) == 1 and tickets[0]["ticket_id"] == created["ticket_id"]
    assert client.get(f'/api/v2/tickets/{created["ticket_id"]}').json() == created
    url = f'/api/v2/tickets/{created["ticket_id"]}/review'
    approved = client.post(url, json=fixtures()["review_request"])
    assert approved.status_code == 200, approved.text
    assert client.post(url, json=fixtures()["review_request"]).json() == approved.json()
    assert client.get("/api/v2/map").json() == fixtures()["map_after_approval"]


def test_slot_is_not_ticket_and_missing_invalid_or_changed_image_is_rejected():
    client = TestClient(create_app())
    sample = fixtures()
    slot = client.post("/api/v2/uploads/presign", json=sample["presign_request"]).json()
    payload = copy.deepcopy(sample["report_request"])
    payload["image"]["photo_id"] = slot["photo_id"]
    assert not client.get("/api/v2/tickets").json()["items"]
    assert client.post("/api/v2/reports", json=payload).status_code == 422
    assert client.put(slot["url"], content=b"invalid", headers=slot["headers"]).status_code == 422
    data = (FIXTURES / "synthetic-evidence.jpg").read_bytes()
    assert client.put(slot["url"], content=data, headers=slot["headers"]).status_code == 200
    assert client.put(slot["url"], content=data, headers=slot["headers"]).status_code == 412
    payload["image"]["sha256"] = "0" * 64
    assert client.post("/api/v2/reports", json=payload).status_code == 422
    assert not client.get("/api/v2/tickets").json()["items"]


@pytest.mark.parametrize("change", [
    {"schema_id": "unknown"}, {"edge_key": "C-D"}, {"junction": "C"},
    {"destination": "E"}, {"distance_m": 0.4}, {"clearance_m": 1.1},
    {"measurement_source": "invented"}, {"timestamp": "2026-10-25T09:00:00+08:00"},
    {"client_id": "another-camera"}, {"image": {"photo_id": str(uuid4()), "sha256": "not-a-checksum"}}])
def test_required_schema_and_assigned_location_are_validated(change):
    client = TestClient(create_app())
    payload = {**fixtures()["report_request"], **change}
    assert client.post("/api/v2/reports", json=payload).status_code == 422


def test_new_local_process_reads_persisted_report_map_and_photo(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db"), FilePhotos(tmp_path / "photos")))
    payload, result = canonical_report(client)
    assert result.status_code == 201
    ticket = result.json()["ticket_id"]
    assert client.post(f"/api/v2/tickets/{ticket}/review", json=fixtures()["review_request"]).status_code == 200
    # A distinct interpreter constructs the API after the first adapter is gone.
    del client
    source = '''
import hashlib,json,sys
from pathlib import Path
from fastapi.testclient import TestClient
from production.v3.cloud.fixed_camera.app import create_app
from production.v3.cloud.fixed_camera.local_storage import SQLiteStore,FilePhotos
root=Path(sys.argv[1]); photos=FilePhotos(root/'photos')
with TestClient(create_app(SQLiteStore(root/'state.db'), photos)) as client:
 report=client.get('/api/v2/reports/'+sys.argv[2]).json()
 print(json.dumps({'status':report['status'],'map':client.get('/api/v2/map').json(),'sha256':hashlib.sha256(photos.get(report['image']['photo_id'])).hexdigest()}))
'''
    result = subprocess.run([sys.executable, "-c", source, str(tmp_path), payload["event_id"]],
                            capture_output=True, text=True, check=True, timeout=30)
    persisted = json.loads(result.stdout)
    assert persisted["status"] == "APPROVED"
    assert persisted["map"] == fixtures()["map_after_approval"]
    assert persisted["sha256"] == payload["image"]["sha256"]


def test_operational_logs_do_not_include_photo_urls_bytes_or_reviewer_notes(caplog):
    client = TestClient(create_app())
    payload, result = canonical_report(client)
    body = {**fixtures()["review_request"], "notes": "PRIVATE_REVIEW_NOTE"}
    assert client.post(f'/api/v2/tickets/{result.json()["ticket_id"]}/review', json=body).status_code == 200
    records = [json.loads(r.message) for r in caplog.records if r.name == "pathable.fixed_camera.audit"]
    assert {"UPLOAD_SLOT_CREATED", "REPORT_PENDING", "REVIEW_COMMITTED", "MAP_UPDATED"} <= {r["action"] for r in records}
    assert "PRIVATE_REVIEW_NOTE" not in caplog.text
    assert "jpeg_base64" not in caplog.text and "X-Amz-Signature" not in caplog.text


def test_published_fixture_schema_and_checksum():
    sample = fixtures()
    HumanReportInput.model_validate(sample["report_request"])
    ReportRecord.model_validate(sample["pending_response"])
    ReviewResult.model_validate(sample["review_response"])
    assert hashlib.sha256((FIXTURES / "synthetic-evidence.jpg").read_bytes()).hexdigest() == sample["presign_request"]["sha256"]


def test_s3_presign_restricts_object_and_report_verifies_uploaded_bytes(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    sample = fixtures()
    slot = client.post("/api/v2/uploads/presign", json=sample["presign_request"]).json()
    query = parse_qs(urlparse(slot["url"]).query)
    signed = query["X-Amz-SignedHeaders"][0].split(";")
    assert {"if-none-match", "content-type", "content-length", "x-amz-checksum-sha256"} <= set(signed)
    assert query["X-Amz-Expires"] == ["300"]
    payload = copy.deepcopy(sample["report_request"])
    payload["image"]["photo_id"] = slot["photo_id"]
    assert client.post("/api/v2/reports", json=payload).status_code == 422
    uploaded = requests.put(slot["url"], data=(FIXTURES / "synthetic-evidence.jpg").read_bytes(),
                            headers=slot["headers"], timeout=10)
    assert uploaded.status_code == 200
    submitted = client.post("/api/v2/reports", json=payload)
    assert submitted.status_code == 201, submitted.text
    assert client.get("/api/v2/tickets").json()["items"][0]["event_id"] == payload["event_id"]


def test_existing_s3_object_with_wrong_checksum_is_rejected(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    sample = fixtures()
    slot = client.post("/api/v2/uploads/presign", json=sample["presign_request"]).json()
    # Simulate an object placed through some other storage path. The report
    # must inspect its bytes, not merely trust the upload metadata.
    photos.put(slot["photo_id"], b"invalid substituted content")
    payload = copy.deepcopy(sample["report_request"])
    payload["image"]["photo_id"] = slot["photo_id"]
    assert client.post("/api/v2/reports", json=payload).status_code == 422
    assert not client.get("/api/v2/tickets").json()["items"]


def test_local_upload_expiry_and_invalid_slot_size():
    store = MemoryStore()
    client = TestClient(create_app(store))
    sample = fixtures()
    assert client.post("/api/v2/uploads/presign", json={**sample["presign_request"],
                                                      "size_bytes": 524289}).status_code == 422
    slot = client.post("/api/v2/uploads/presign", json=sample["presign_request"]).json()
    store.items[f'PHOTO#{slot["photo_id"]}']["upload_until"] = 0
    assert client.put(slot["url"], content=(FIXTURES / "synthetic-evidence.jpg").read_bytes()).status_code == 403


def test_canonical_camera_status_and_reviewer_authorization_via_lambda():
    from mangum import Mangum
    app = create_app(MemoryStore(), MemoryPhotos(), aws=True,
                     camera_subject="camera-user", reviewer_subjects=["reviewer-user"])
    adapter = Mangum(app, lifespan="off")

    def call(method, path, scope, sub, body=None):
        event = {"version": "2.0", "rawPath": path, "rawQueryString": "",
            "headers": {"host": "example.test", "content-type": "application/json"},
            "requestContext": {"http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
                               "authorizer": {"jwt": {"claims": {"sub": sub, "scope": scope}}}},
            "body": json.dumps(body) if body else None, "isBase64Encoded": False}
        return adapter(event, {})

    sample = fixtures()
    assert call("POST", "/api/v2/uploads/presign", "pathable/camera", "wrong-camera",
                sample["presign_request"])["statusCode"] == 403
    # Upload through the already-published compact image endpoint; canonical
    # report intake and ticket review use the same authenticated Lambda adapter.
    import base64
    uploaded = call("POST", "/api/v2/photos", "pathable/camera", "camera-user", {
        "camera_id": "camera-b-01", "jpeg_base64": base64.b64encode(
            (FIXTURES / "synthetic-evidence.jpg").read_bytes()).decode()})
    assert uploaded["statusCode"] == 201
    payload = copy.deepcopy(sample["report_request"])
    payload["image"]["photo_id"] = json.loads(uploaded["body"])["photo_id"]
    assert call("POST", "/api/v2/reports", "pathable/camera", "camera-user", payload)["statusCode"] == 201
    path = f'/api/v2/reports/{payload["event_id"]}'
    assert call("GET", path, "pathable/camera", "camera-user")["statusCode"] == 200
    assert call("GET", path, "pathable/camera", "wrong-camera")["statusCode"] == 403
    ticket_review = f'/api/v2/tickets/T-{payload["event_id"]}/review'
    assert call("POST", ticket_review, "pathable/camera pathable/reviewer", "camera-user",
                sample["review_request"])["statusCode"] == 403
    assert call("POST", ticket_review, "pathable/reviewer", "reviewer-user",
                sample["review_request"])["statusCode"] == 200
    assert TestClient(app).get(path, headers={"Authorization": "Bearer forged"}).status_code == 401
