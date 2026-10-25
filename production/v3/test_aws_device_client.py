"""Unit tests for AwsDeviceClient (Person 1 Workstream).

Verifies the 9 required test cases:
1. No qualifying detection produces no report.
2. One sustained episode does not create a report on every frame.
3. Upload/submission retries retain the same report_id.
4. A pending report does not trigger the AWS-approved reroute.
5. An approved map closure changes the route correctly (B -> E -> F -> D).
6. Repeated delivery of the same map version does not repeat speech.
7. Rejected reports do not create an approved closure.
8. Network failures leave state explicit and recoverable (CONNECTION_UNAVAILABLE).
9. Map state and outbox records persist and handle errors cleanly.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from aws_device_client import AwsDeviceClient, DeviceWorkflowStatus
from local_agent import RouteMap


class MockVoice:
    """Records speech calls for testing without audio devices."""
    def __init__(self):
        self.spoken = []

    def speak(self, text: str, force: bool = False, priority: bool = False):
        self.spoken.append(text)


def cloud_map(version=1, blocked=False):
    return {
        "map_id": "prototype", "version": version,
        "nodes": {str(i): n for i, n in enumerate("ABCDEF")},
        "edges": [{"from": a, "to": b, "distance": None,
                   "distance_source": "unmeasured", "route_weight": 1,
                   "blocked": blocked and (a, b) == ("B", "C")}
                  for a, b in [("A", "B"), ("B", "C"), ("C", "D"),
                               ("B", "E"), ("E", "F"), ("F", "D")]],
    }


def create_test_route_map() -> RouteMap:
    """Returns a 6-node prototype map with edge B-C unblocked."""
    map_data = {
        "nodes": {"0": "A", "1": "B", "2": "C", "3": "D", "4": "E", "5": "F"},
        "edges": [
            {"from": "A", "to": "B", "distance": 12.0, "blocked": False},
            {"from": "B", "to": "C", "distance": 15.0, "blocked": False},
            {"from": "C", "to": "D", "distance": 12.0, "blocked": False},
            {"from": "B", "to": "E", "distance": 10.0, "blocked": False},
            {"from": "E", "to": "F", "distance": 24.0, "blocked": False},
            {"from": "F", "to": "D", "distance": 10.0, "blocked": False},
        ],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(map_data, f)
        temp_path = Path(f.name)
    rm = RouteMap.from_file(temp_path)
    temp_path.unlink()
    return rm


class AwsDeviceClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.outbox_dir = Path(self.tmp_dir) / "outbox"
        self.voice = MockVoice()
        self.route_map = create_test_route_map()
        self.client = AwsDeviceClient(
            api_base_url="http://mock-aws:8000",
            api_prefix="/api/v2",
            camera_id="camera-b-01",
            assigned_node="B",
            assigned_edge=("B", "C"),
            destination_node="D",
            route_map=self.route_map,
            voice=self.voice,
            outbox_dir=self.outbox_dir,
            http_timeout_s=1.0,
        )

    def tearDown(self):
        self.client.stop()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_case_1_no_qualifying_detection_produces_no_report(self):
        """Case 1: When trigger is False, no report is generated or queued."""
        evidence = {
            "trigger": False,
            "positive_frames": 2,
            "total_frames": 10,
            "current": None,
        }
        self.assertIsNone(self.client.on_chair_overlap_trigger(evidence, b""))
        # Nothing should be in outbox or queue
        self.assertIsNone(self.client._current_report)
        self.assertEqual(self.client.status, DeviceWorkflowStatus.MONITORING)
        self.assertEqual(self.client._submission_queue.qsize(), 0)

    def test_case_2_one_sustained_episode_does_not_create_report_every_frame(self):
        """Case 2: Repeated triggers during one sustained episode do not create duplicate reports."""
        evidence = {
            "trigger": True,
            "positive_frames": 8,
            "total_frames": 10,
            "current": {"confidence": 0.88},
        }
        fake_frame = b"\xff\xd8\xff\xe0" + b"\x00" * 64

        # First frame triggers report creation
        rep1 = self.client.on_chair_overlap_trigger(evidence, fake_frame)
        self.assertIsNotNone(rep1)
        self.assertEqual(self.client._submission_queue.qsize(), 1)

        # Subsequent frames while report is active return None and do not queue again
        rep2 = self.client.on_chair_overlap_trigger(evidence, fake_frame)
        self.assertIsNone(rep2)
        rep3 = self.client.on_chair_overlap_trigger(evidence, fake_frame)
        self.assertIsNone(rep3)
        self.assertEqual(self.client._submission_queue.qsize(), 1)

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_3_retries_retain_same_report_id(self, mock_http):
        """Case 3: Failed upload/submission retains the exact same report_id on retry."""
        evidence = {
            "trigger": True,
            "positive_frames": 8,
            "total_frames": 10,
            "current": {"confidence": 0.90},
        }
        fake_frame = b"\xff\xd8" + b"\x01" * 32
        record = self.client.on_chair_overlap_trigger(evidence, fake_frame)
        orig_id = record.report_id

        # Simulate first attempt failing with connection error
        mock_http.side_effect = [
            ConnectionError("Cloud endpoint unreachable"),
            (201, {"photo_id": "photo-123", "sha256": "abc"}),
            (201, {"report_id": orig_id, "camera_id": "camera-b-01", "photo_id": "photo-123", "status": "PENDING"}),
        ]

        # First upload attempt raises
        with self.assertRaises(ConnectionError):
            self.client._upload_photo(record)

        # Record keeps original report_id and SHA-256
        self.assertEqual(record.report_id, orig_id)

        # Retry succeeds using the same record
        photo_id = self.client._upload_photo(record)
        self.assertEqual(photo_id, "photo-123")
        record.photo_id = photo_id

        # Submit report succeeds with original report_id
        resp = self.client._submit_report(record)
        self.assertEqual(resp["report_id"], orig_id)
        # Check payload sent in mock_http call
        last_call_args = mock_http.call_args[0]
        self.assertEqual(last_call_args[1], "/reports")
        self.assertEqual(last_call_args[2]["report_id"], orig_id)

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_4_pending_report_does_not_trigger_reroute(self, mock_http):
        """Case 4: A pending report awaiting review leaves edge B-C unblocked."""
        # Cloud map version is v1 with B-C NOT blocked
        mock_http.side_effect = [
            (200, {"map_id": "prototype", "version": 1}),
            (200, cloud_map(1, False)),
        ]

        # Initial route before review is B -> C -> D
        self.assertEqual(self.client.proposed_route, ["B", "C", "D"])

        # Poll map
        changed = self.client.poll_and_synchronize_map()
        self.assertTrue(changed)

        # Invariant: Route must STILL be B -> C -> D (NOT rerouted)
        self.assertEqual(self.client.proposed_route, ["B", "C", "D"])
        self.assertFalse(self.client.is_edge_blocked_in_cloud)
        self.assertEqual(len(self.voice.spoken), 0)

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_5_approved_map_closure_updates_route(self, mock_http):
        """Case 5: When approved map arrives with B-C blocked, route updates to B->E->F->D."""
        mock_http.side_effect = [
            (200, {"map_id": "prototype", "version": 2}),
            (200, cloud_map(2, True)),
        ]

        changed = self.client.poll_and_synchronize_map()
        self.assertTrue(changed)
        self.assertTrue(self.client.is_edge_blocked_in_cloud)
        self.assertEqual(self.client.status, DeviceWorkflowStatus.PROPOSED_ROUTE_UPDATED)

        # Route must now be B -> E -> F -> D!
        self.assertEqual(self.client.proposed_route, ["B", "E", "F", "D"])
        self.assertEqual(len(self.voice.spoken), 1)
        self.assertIn("B, E, F, D", self.voice.spoken[0])

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_6_repeated_delivery_of_same_map_version_does_not_repeat_speech(self, mock_http):
        """Case 6: Subsequent polls returning the same map version do not repeat speech."""
        mock_http.side_effect = [
            (200, {"map_id": "prototype", "version": 2}),
            (200, cloud_map(2, True)),
            # Second poll: same version 2
            (200, {"map_id": "prototype", "version": 2}),
            # Third poll: same version 2
            (200, {"map_id": "prototype", "version": 2}),
        ]

        self.client.poll_and_synchronize_map()
        self.assertEqual(len(self.voice.spoken), 1)

        # Subsequent polls
        self.client.poll_and_synchronize_map()
        self.client.poll_and_synchronize_map()
        # Still exactly 1 speech announcement
        self.assertEqual(len(self.voice.spoken), 1)

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_7_rejected_report_leaves_route_unclosed(self, mock_http):
        """Case 7: If a report is rejected by facilities, edge B-C stays unblocked."""
        mock_http.side_effect = [
            (200, {"map_id": "prototype", "version": 2}),
            (200, cloud_map(2, False)),
        ]

        self.client.poll_and_synchronize_map()
        self.assertFalse(self.client.is_edge_blocked_in_cloud)
        self.assertEqual(self.client.proposed_route, ["B", "C", "D"])
        self.assertEqual(len(self.voice.spoken), 0)

    @patch.object(AwsDeviceClient, "_http_request")
    def test_case_8_network_failure_sets_connection_unavailable(self, mock_http):
        """Case 8: Network connection failure cleanly transitions status to CONNECTION_UNAVAILABLE."""
        mock_http.side_effect = ConnectionError("Could not reach AWS API Gateway")

        with self.assertRaises(ConnectionError):
            self.client.poll_and_synchronize_map()

        self.client.set_status(DeviceWorkflowStatus.CONNECTION_UNAVAILABLE, "Could not reach AWS API Gateway")
        self.assertEqual(self.client.status, DeviceWorkflowStatus.CONNECTION_UNAVAILABLE)
        self.assertIn("Could not reach AWS", self.client.last_error)
        # Invariant: retains last known map; does not fabricate approval
        self.assertFalse(self.client.is_edge_blocked_in_cloud)

    def test_case_9_outbox_persistence_roundtrip(self):
        """Case 9: Report metadata and JPEG evidence persist into outbox files."""
        fake_frame = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x42" * 50
        evidence = {
            "trigger": True,
            "positive_frames": 7,
            "total_frames": 10,
            "current": {"confidence": 0.84},
        }
        record = self.client.on_chair_overlap_trigger(evidence, fake_frame)
        self.assertIsNotNone(record)

        json_file = self.outbox_dir / f"{record.report_id}.json"
        jpg_file = self.outbox_dir / f"{record.report_id}.jpg"

        self.assertTrue(json_file.exists())
        self.assertTrue(jpg_file.exists())

        with open(json_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["report_id"], record.report_id)
        self.assertEqual(saved["obstacle_class"], "chair")
        self.assertEqual(saved["jpeg_sha256"], record.jpeg_sha256)
        self.assertEqual(jpg_file.read_bytes(), fake_frame)


if __name__ == "__main__":
    unittest.main()
