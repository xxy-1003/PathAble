"""AWS API emulator tests: these are NOT deployed AWS evidence."""
import base64
import importlib
import json

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from production.v3.cloud.fixed_camera.app import create_app
from production.v3.cloud.fixed_camera.storage import Conflict, DynamoStore, S3Photos
from .test_workflow import bc, jpeg, report, review


@pytest.fixture
def aws_storage(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-1")
        db.create_table(TableName="test-state", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}])
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-photos")
        yield DynamoStore("test-state"), S3Photos("test-photos")


def test_durable_adapter_reload_and_atomic_review(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    payload, result = report(client)
    assert result.status_code == 201
    assert review(client, payload["report_id"]).status_code == 200
    fresh = TestClient(create_app(DynamoStore("test-state"), S3Photos("test-photos")))
    assert bc(fresh)["blocked"] is True
    assert fresh.post("/api/v2/reports", json=payload).status_code == 200
    assert review(fresh, payload["report_id"]).json()["map_version"] == 2
    assert boto3.client("s3").get_object(Bucket="test-photos",
        Key=f'photos/{payload["photo_id"]}.jpg')["Body"].read() == jpeg()
    assert "test-photos" in fresh.get(
        f'/api/v2/reports/{payload["report_id"]}/photo').json()["url"]


def test_transaction_conflict_leaves_other_report_pending(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    first, _ = report(client)
    second, _ = report(client)
    assert review(client, first["report_id"]).status_code == 200
    assert review(client, second["report_id"]).status_code == 409
    assert store.get(f'REPORT#{second["report_id"]}')["status"] == "PENDING"
    assert review(client, second["report_id"], "REJECT", 2).status_code == 200
    assert bc(client)["blocked"]


def test_dynamo_cursor_keeps_all_reports(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    expected = {report(client)[0]["report_id"] for _ in range(3)}
    cursor = None
    received = set()
    for _ in range(20):
        params = {"limit": 1, "status": "PENDING"}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/api/v2/reports", params=params).json()
        received.update(r["report_id"] for r in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert received == expected


def test_database_transaction_rolls_back_stale_map_write(aws_storage):
    store, photos = aws_storage
    client = TestClient(create_app(store, photos))
    first, _ = report(client)
    second, _ = report(client)
    stale_map = store.get_map()
    stale_report = store.get(f'REPORT#{second["report_id"]}')
    stale_report["status"] = "APPROVED"
    stale_map["version"] = 2
    assert review(client, first["report_id"]).status_code == 200
    with pytest.raises(Conflict):
        store.review(f'REPORT#{second["report_id"]}', stale_report, 1, stale_map)
    assert store.get(f'REPORT#{second["report_id"]}')["status"] == "PENDING"
    assert store.get_map()["version"] == 2


def test_s3_photo_cannot_be_overwritten(aws_storage):
    from botocore.exceptions import ClientError
    _, photos = aws_storage
    photos.put("immutable", jpeg())
    with pytest.raises(ClientError):
        photos.put("immutable", b"replacement")


def test_presigned_photo_links_use_bucket_region(monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    monkeypatch.setenv("S3_REGIONAL_ENDPOINT", "https://s3.ap-southeast-2.amazonaws.com")
    with mock_aws():
        photos = S3Photos("regional-demo-photos")
        get_url = photos.url("example")
        put_url = photos.presign("example", 10, "0" * 64)["url"]
        for url in (get_url, put_url):
            parsed = urlsplit(url)
            assert parsed.hostname == "s3.ap-southeast-2.amazonaws.com"
            assert parsed.path == "/regional-demo-photos/photos/example.jpg"
            assert "/ap-southeast-2/s3/aws4_request" in parse_qs(parsed.query)["X-Amz-Credential"][0]


def test_lambda_jwt_scope_identity_and_http_adapter(aws_storage, monkeypatch):
    for key, value in {"STATE_TABLE": "test-state", "PHOTOS_BUCKET": "test-photos",
        "CAMERA_ID": "camera-b-01", "CAMERA_NODE": "B", "CAMERA_EDGE": "B-C",
        "CAMERA_SUBJECT": "camera-user",
        "DASHBOARD_ORIGIN": "https://review.example.test",
        "REVIEWER_SUBJECTS": "reviewer-user"}.items():
        monkeypatch.setenv(key, value)
    from production.v3.cloud.fixed_camera import lambda_handler
    importlib.reload(lambda_handler)

    def call(method, path, scope="pathable/map", sub="laptop-user", body=None):
        event = {"version": "2.0", "routeKey": "ANY /api/v2/{proxy+}",
            "rawPath": path, "rawQueryString": "", "headers": {"host": "example.test",
            "content-type": "application/json"}, "isBase64Encoded": False,
            "requestContext": {"http": {"method": method, "path": path,
            "sourceIp": "127.0.0.1", "protocol": "HTTP/1.1"},
            "authorizer": {"jwt": {"claims": {"sub": sub, "scope": scope},
                                    "scopes": scope.split()}}},
            "body": json.dumps(body) if body else None}
        return lambda_handler.handler(event, {})

    assert call("GET", "/api/v2/map")["statusCode"] == 200
    assert call("GET", "/api/v2/reports")["statusCode"] == 403
    assert call("GET", "/api/v2/map", scope="")["statusCode"] == 403
    photo_body = {"camera_id": "camera-b-01", "jpeg_base64": base64.b64encode(jpeg()).decode()}
    assert call("POST", "/api/v2/photos", scope="pathable/camera", body=photo_body)["statusCode"] == 403
    uploaded = call("POST", "/api/v2/photos", scope="pathable/camera", sub="camera-user", body=photo_body)
    assert uploaded["statusCode"] == 201
    assert call("GET", "/api/v2/reports", scope="pathable/reviewer", sub="reviewer-user")["statusCode"] == 200
    assert call("GET", "/api/v2/reports", scope="pathable/reviewer", sub="camera-user")["statusCode"] == 403
    from uuid import uuid4
    payload = {"report_id": str(uuid4()), "photo_id": json.loads(uploaded["body"])["photo_id"],
               "camera_id": "camera-b-01", "observed_at": "2026-10-25T09:00:00Z",
               "obstacle_class": "chair", "confidence": 0.85, "overlap_count": 6, "frame_count": 10}
    assert call("POST", "/api/v2/reports", scope="pathable/camera", sub="camera-user",
                body=payload)["statusCode"] == 201
    reviewed = call("POST", f'/api/v2/reports/{payload["report_id"]}/review',
                    scope="pathable/reviewer", sub="reviewer-user",
                    body={"action": "APPROVE", "expected_map_version": 1})
    assert reviewed["statusCode"] == 200
    assert json.loads(reviewed["body"])["report"]["review"]["reviewer_id"] == "reviewer-user"
