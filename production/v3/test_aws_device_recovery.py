"""Regression cases for the reviewed Person 1 failures; synthetic local data only."""
import copy
import json
import threading
from unittest.mock import Mock

import pytest

from aws_device_client import AwsDeviceClient, DeviceWorkflowStatus, RequestRejected
from test_aws_device_client import cloud_map, create_test_route_map, MockVoice


EVIDENCE = {"trigger": True, "positive_frames": 8, "total_frames": 10,
            "current": {"confidence": 0.88}}
JPEG = b"synthetic-byte-transport-test-only"


@pytest.fixture
def client(tmp_path):
    return AwsDeviceClient(route_map=create_test_route_map(), voice=MockVoice(), outbox_dir=tmp_path)


def report_response(record, status="PENDING"):
    return {"report_id": record.report_id, "camera_id": record.camera_id,
            "photo_id": record.photo_id, "status": status}


def poll(client, body, advertised=None):
    responses = iter([(200, {"map_id": "prototype", "version": advertised or body["version"]}), (200, body)])
    client._http_request = lambda *args: next(responses)
    return client.poll_and_synchronize_map()


def test_restart_recovers_same_report_photo_checksum_and_queue(client):
    original = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    original.photo_id = "persisted-photo"
    client._persist_outbox_record(original)
    recovered = AwsDeviceClient(route_map=create_test_route_map(), outbox_dir=client.outbox_dir)
    queued = recovered._submission_queue.get_nowait()
    assert queued.report_id == original.report_id
    assert queued.photo_id == "persisted-photo"
    assert queued.jpeg_bytes == JPEG and queued.jpeg_sha256 == original.jpeg_sha256
    assert recovered.on_chair_overlap_trigger(EVIDENCE, JPEG) is None


def test_submitted_pending_report_is_restored_for_status_polling_not_resubmission(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "persisted-photo"
    client._accept_report_response(record, report_response(record))
    recovered = AwsDeviceClient(outbox_dir=client.outbox_dir)
    assert recovered._submission_queue.empty()
    assert recovered._current_report.report_id == record.report_id
    assert recovered.status == DeviceWorkflowStatus.AWAITING_REVIEW


@pytest.mark.parametrize("damage", ["json", "jpeg", "context", "state"])
def test_corrupt_or_wrong_project_outbox_is_preserved_and_blocks_new_reports(client, damage):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    path = client.outbox_dir / ("client-state.json" if damage == "state" else record.report_id + ".json")
    if damage in ("json", "state"):
        path.write_text("broken", encoding="utf-8")
    elif damage == "jpeg":
        (client.outbox_dir / (record.report_id + ".jpg")).write_bytes(b"changed")
    else:
        data = json.loads(path.read_text()); data["context"]["api_base_url"] = "https://different-project.invalid"
        path.write_text(json.dumps(data))
    before = path.read_bytes()
    recovered = AwsDeviceClient(outbox_dir=client.outbox_dir)
    assert recovered.status == DeviceWorkflowStatus.CONNECTION_UNAVAILABLE
    assert recovered._submission_queue.empty()
    assert recovered.on_chair_overlap_trigger({"trigger": False}, b"") is None
    assert recovered.on_chair_overlap_trigger(EVIDENCE, JPEG) is None
    recovered.start()
    assert recovered._worker_thread is None and path.read_bytes() == before


def test_disk_failure_does_not_acknowledge_unrecoverable_event(client):
    client._atomic_write = Mock(side_effect=OSError("disk full"))
    with pytest.raises(OSError): client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    assert client._current_report is None and client._submission_queue.empty()


def test_retry_checkpoint_disk_failure_does_not_silently_lose_queue_task(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "photo"
    client._http_request = Mock(return_value=(503, {}))
    client._persist_outbox_record = Mock(side_effect=OSError("disk full"))
    run_worker_batch(client)
    assert client._recovery_error and client._submission_queue.unfinished_tasks == 0
    assert client.status == DeviceWorkflowStatus.CONNECTION_UNAVAILABLE
    assert client.on_chair_overlap_trigger(EVIDENCE, JPEG) is None


def test_stop_after_photo_upload_preserves_reference_without_starting_report_request(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    def upload(*args):
        client._stop_event.set()
        return 201, {"photo_id": "saved-photo"}
    client._http_request = Mock(side_effect=upload)
    client._run_outbox_worker()
    assert client._http_request.call_count == 1
    recovered = AwsDeviceClient(outbox_dir=client.outbox_dir)
    assert recovered._submission_queue.get_nowait().photo_id == "saved-photo"


def test_payload_conflict_is_not_success_or_automatic_retry(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "photo"
    client._http_request = Mock(return_value=(409, {"detail": "sensitive error text"}))
    with pytest.raises(RequestRejected, match="409") as error: client._submit_report(record)
    assert "sensitive" not in str(error.value)
    assert record.submitted_at is None and record.status == "PENDING"


def run_worker_batch(client):
    worker = threading.Thread(target=client._run_outbox_worker)
    # Avoid backoff delays in these synthetic tests.
    client._stop_event.wait = Mock(return_value=False)
    worker.start()
    client._submission_queue.join()
    client._stop_event.set()
    worker.join(timeout=2)
    assert not worker.is_alive()


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (409, 1), (422, 1), (503, 3)])
def test_submission_retry_budget_and_permanent_failures_are_recoverable(client, status, attempts):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "photo"
    client._http_request = Mock(return_value=(status, {}))
    run_worker_batch(client)
    assert client._http_request.call_count == attempts
    assert client.status == DeviceWorkflowStatus.CONNECTION_UNAVAILABLE
    assert record.submitted_at is None
    saved = json.loads((client.outbox_dir / (record.report_id + ".json")).read_text())
    assert saved["last_error"] and saved["report_id"] == record.report_id


@pytest.mark.parametrize("damage", ["missing", "duplicate", "wrong-id", "bool-version", "stale", "blocked-type", "measurements"])
def test_invalid_full_map_retains_previous_graph_and_version(client, damage):
    poll(client, cloud_map(1))
    previous_graph = client.route_map
    body = cloud_map(2, True)
    if damage == "missing": body["edges"].pop()
    elif damage == "duplicate": body["edges"][-1] = copy.deepcopy(body["edges"][0])
    elif damage == "wrong-id": body["map_id"] = "other-project"
    elif damage == "bool-version": body["version"] = True
    elif damage == "stale": body["version"] = 1
    elif damage == "blocked-type": body["edges"][1]["blocked"] = "true"
    else: body["edges"][1]["distance"] = 0.0
    with pytest.raises(ConnectionError): poll(client, body, advertised=2)
    assert client.last_applied_version == 1 and client.known_map_version == 1
    assert client.route_map is previous_graph and not client.map_synchronized
    assert client.proposed_route == ["B", "C", "D"] and not client.voice.spoken


def test_newer_full_map_uses_its_own_version_not_earlier_version_probe(client):
    assert poll(client, cloud_map(3, True), advertised=2)
    assert client.last_applied_version == client.known_map_version == 3


def test_full_map_closure_on_alternative_edge_prevents_routing_through_it(client):
    body = cloud_map(2, True)
    next(e for e in body["edges"] if (e["from"], e["to"]) == ("B", "E"))["blocked"] = True
    poll(client, body)
    assert client.proposed_route == []
    assert "No proposed route" in client.voice.spoken[0]


def test_cloud_weights_are_used_as_costs_without_inventing_metres(client):
    body = cloud_map(1)
    body["edges"][1]["route_weight"] = 10
    poll(client, body)
    assert client.proposed_route == ["B", "E", "F", "D"]
    assert all(e["distance"] is None for e in client._cloud_map["edges"])
    assert not client.voice.spoken  # No approved B-C closure.


def test_unchanged_route_does_not_repeat_speech_on_another_version_or_restart(client):
    poll(client, cloud_map(2, True)); poll(client, cloud_map(3, True))
    assert len(client.voice.spoken) == 1
    voice = MockVoice()
    restarted = AwsDeviceClient(voice=voice, outbox_dir=client.outbox_dir)
    assert restarted.last_applied_version == 3 and not restarted.map_synchronized
    poll(restarted, cloud_map(3, True))
    assert restarted.map_synchronized and not voice.spoken


def test_rejection_is_polled_when_map_version_is_unchanged_and_next_episode_rearms(client):
    poll(client, cloud_map(1))
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "photo"
    client._accept_report_response(record, report_response(record))
    client._http_request = Mock(side_effect=[(200, {"map_id": "prototype", "version": 1}),
                                            (200, report_response(record, "REJECTED"))])
    assert not client.poll_and_synchronize_map()
    assert record.status == "REJECTED" and client._current_report is None
    assert client.proposed_route == ["B", "C", "D"] and not client.voice.spoken
    assert client.on_chair_overlap_trigger(EVIDENCE, JPEG) is None  # Same sustained episode.
    client.on_chair_overlap_trigger({"trigger": False}, b"")
    fresh = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    assert fresh is not None and fresh.report_id != record.report_id


def test_report_approval_alone_never_mutates_the_route(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    record.photo_id = "photo"
    client._accept_report_response(record, report_response(record, "APPROVED"))
    assert client._current_report is None and not client.is_edge_blocked_in_cloud
    assert client.proposed_route == ["B", "C", "D"] and not client.voice.spoken


def test_successful_report_response_must_match_queued_identity(client):
    record = client.on_chair_overlap_trigger(EVIDENCE, JPEG)
    client._http_request = Mock(return_value=(201, {"report_id": "other", "status": "PENDING"}))
    with pytest.raises(ConnectionError): client._submit_report(record)
    assert record.submitted_at is None


def test_nonqualifying_or_missing_evidence_cannot_fabricate_detection_fields(client):
    assert client.on_chair_overlap_trigger({"trigger": False}, b"") is None
    with pytest.raises(ValueError): client.on_chair_overlap_trigger({"trigger": True}, JPEG)
    assert client._current_report is None


def test_map_announcement_does_not_clear_queued_camera_stop(client):
    client.voice = Mock()
    poll(client, cloud_map(2, True))
    assert client.voice.speak.call_args.kwargs["priority"] is False
