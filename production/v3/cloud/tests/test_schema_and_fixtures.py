"""Tests for Blocked-Edge Event schema and fixture validation."""

import json
from pathlib import Path
import unittest

from ..core.validation import EventValidationError, validate_event_dict, validate_event_file
from ..schema.models import BlockedEdgeEventV1


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class SchemaAndFixturesTests(unittest.TestCase):
    def test_valid_temporary_fixture(self):
        file_path = FIXTURES_DIR / "event_temporary_person.json"
        event = validate_event_file(file_path)
        self.assertEqual(event.event_id, "evt-b-c-temp-001")
        self.assertEqual(event.edge.from_node, "B")
        self.assertEqual(event.edge.to_node, "C")
        self.assertTrue(event.observations.moving)
        self.assertTrue(event.privacy.people_blurred_on_device)
        self.assertFalse(event.privacy.face_recognition_used)

    def test_valid_uncertain_fixture(self):
        file_path = FIXTURES_DIR / "event_uncertain_chair.json"
        event = validate_event_file(file_path)
        self.assertEqual(event.event_id, "evt-b-c-uncertain-001")
        self.assertIn("chair", event.observations.obstacle_classes)

    def test_valid_lasting_fixtures_pair(self):
        f1 = validate_event_file(FIXTURES_DIR / "event_lasting_furniture_1.json")
        f2 = validate_event_file(FIXTURES_DIR / "event_lasting_furniture_2.json")
        self.assertEqual(f1.event_id, "evt-0193")
        self.assertEqual(f2.event_id, "evt-0205")
        self.assertEqual(f1.edge.edge_key, f2.edge.edge_key)
        # Check time interval
        diff_minutes = (f2.timestamp - f1.timestamp).total_seconds() / 60.0
        self.assertGreaterEqual(diff_minutes, 15.0)

    def test_conflicting_observation_fixture(self):
        event = validate_event_file(FIXTURES_DIR / "event_conflicting_observation.json")
        self.assertEqual(event.event_id, "evt-b-c-conflict-001")
        self.assertGreaterEqual(event.observations.ground_contact_distance_m, 1.20)

    def test_invalid_privacy_rejection(self):
        with self.assertRaises(EventValidationError) as ctx:
            validate_event_file(FIXTURES_DIR / "event_invalid_privacy.json")
        self.assertTrue(
            any("Privacy" in err or "privacy" in err.lower() for err in ctx.exception.errors)
            or "privacy" in str(ctx.exception).lower()
        )

    def test_invalid_schema_rejection(self):
        with self.assertRaises(EventValidationError):
            validate_event_file(FIXTURES_DIR / "event_invalid_schema.json")

    def test_invalid_node_and_edge_rejection(self):
        payload = {
            "schema_version": "1.0.0",
            "event_id": "evt-invalid-node",
            "client_id": "test-dev",
            "timestamp": "2026-10-24T03:00:00Z",
            "edge": {"from_node": "Z", "to_node": "B"},  # Z is invalid
            "current_node": "Z",
            "destination_node": "D",
            "local_reroute": ["B", "E", "D"],
            "observations": {
                "confidence": 0.8,
                "obstacle_classes": ["chair"],
                "distance_band": "near",
                "zone_occupancy": {"left": "clear", "centre": "occupied", "right": "clear"},
                "consecutive_blocked_frames": 6,
            },
            "map_version": 1,
        }
        with self.assertRaises(EventValidationError) as ctx:
            validate_event_dict(payload)
        self.assertIn("Invalid edge from_node: Z", str(ctx.exception.message))


if __name__ == "__main__":
    unittest.main()
