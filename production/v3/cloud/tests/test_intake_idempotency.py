"""Tests for idempotent event intake and deduplication."""

import json
from pathlib import Path
import unittest

from ..core.intake import IdempotentIntakeStore
from ..core.validation import EventValidationError


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class IntakeIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.store = IdempotentIntakeStore()
        with open(FIXTURES_DIR / "event_temporary_person.json", "r", encoding="utf-8") as f:
            self.temp_payload = json.load(f)

    def test_first_ingest_succeeds(self):
        event, is_duplicate, cached = self.store.ingest(self.temp_payload)
        self.assertFalse(is_duplicate)
        self.assertIsNone(cached)
        self.assertEqual(event.event_id, "evt-b-c-temp-001")
        self.assertEqual(self.store.count(), 1)

    def test_duplicate_ingest_returns_cached_record(self):
        # First ingest
        event1, is_duplicate1, _ = self.store.ingest(self.temp_payload)
        self.assertFalse(is_duplicate1)

        # Record a result
        mock_result = {"outcome": "TEMPORARY", "expiry_minutes": 10}
        self.store.record_result(event1.event_id, mock_result)

        # Retry ingest with same payload
        event2, is_duplicate2, cached = self.store.ingest(self.temp_payload)
        self.assertTrue(is_duplicate2)
        self.assertEqual(cached, mock_result)
        self.assertEqual(self.store.count(), 1)

    def test_conflicting_payload_same_id_rejected(self):
        # First ingest
        self.store.ingest(self.temp_payload)

        # Modified payload with same event_id
        conflicting_payload = dict(self.temp_payload)
        conflicting_payload["client_id"] = "different-attacker-client"

        with self.assertRaises(EventValidationError) as ctx:
            self.store.ingest(conflicting_payload)
        self.assertIn("Conflict: Event evt-b-c-temp-001 already exists", str(ctx.exception.message))

    def test_query_events_by_edge(self):
        self.store.ingest(self.temp_payload)
        events_bc = self.store.get_events_for_edge("B-C")
        self.assertEqual(len(events_bc), 1)
        self.assertEqual(events_bc[0].event_id, "evt-b-c-temp-001")

        events_ef = self.store.get_events_for_edge("E-F")
        self.assertEqual(len(events_ef), 0)


if __name__ == "__main__":
    unittest.main()
