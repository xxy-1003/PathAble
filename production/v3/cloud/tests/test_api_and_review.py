"""End-to-End API and Human Review integration tests."""

import json
from pathlib import Path
import unittest

from fastapi import HTTPException

from ..api.app import (
    get_decision_traces,
    get_health,
    get_map_version,
    get_shared_map,
    get_ticket,
    ingest_event,
    list_tickets,
    orchestrator,
    review_ticket,
)
from ..schema.models import HumanReviewAction


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class ApiAndReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        from ..core.intake import IdempotentIntakeStore
        from ..core.map_sync import MapSyncManager
        from ..core.human_approval import HumanApprovalManager
        from ..core.audit_logger import CloudAuditLogger

        orchestrator.intake_store = IdempotentIntakeStore()
        orchestrator.map_sync = MapSyncManager()
        orchestrator.approval_mgr = HumanApprovalManager(orchestrator.map_sync)
        orchestrator.audit = CloudAuditLogger()
        orchestrator.edge_history.clear()
    def test_health_check(self):
        data = get_health()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "pathable-slow-loop")

    def test_map_sync_endpoints(self):
        map_data = get_shared_map()
        self.assertIn("version", map_data)
        self.assertIn("edges", map_data)

        v_data = get_map_version()
        self.assertEqual(v_data["version"], map_data["version"])

    def test_temporary_event_ingestion_and_idempotency(self):
        with open(FIXTURES_DIR / "event_temporary_person.json", "r", encoding="utf-8") as f:
            payload = json.load(f)

        data = ingest_event(payload)
        self.assertEqual(data["status"], "PROCESSED")
        self.assertEqual(data["outcome"], "TEMPORARY")
        self.assertEqual(data["expiry_minutes"], 10)

        # Idempotent retry check
        retry_data = ingest_event(payload)
        self.assertEqual(retry_data["status"], "DUPLICATE")

    def test_lasting_event_sequence_creates_ticket_and_human_review(self):
        # Event 1 (T=0)
        with open(FIXTURES_DIR / "event_lasting_furniture_1.json", "r", encoding="utf-8") as f:
            payload1 = json.load(f)
        data1 = ingest_event(payload1)
        self.assertEqual(data1["outcome"], "UNCERTAIN")

        # Event 2 (T=22m later)
        with open(FIXTURES_DIR / "event_lasting_furniture_2.json", "r", encoding="utf-8") as f:
            payload2 = json.load(f)
        data2 = ingest_event(payload2)
        self.assertEqual(data2["outcome"], "LASTING")
        ticket_id = data2["ticket_id"]
        self.assertIsNotNone(ticket_id)

        # Verify ticket in list
        tickets = list_tickets(status_filter="PENDING")
        self.assertTrue(any(t["ticket_id"] == ticket_id for t in tickets))

        # Check get_ticket
        ticket = get_ticket(ticket_id)
        self.assertEqual(ticket["ticket_id"], ticket_id)

        # Human Review: APPROVE
        review_res = review_ticket(
            ticket_id=ticket_id,
            review=HumanReviewAction(
                action="APPROVE",
                reviewer_id="facilities-supervisor-01",
                notes="Confirmed corridor B-C requires furniture removal.",
            ),
        )
        self.assertEqual(review_res["ticket"]["status"], "APPROVED")

        # Verify edge in map is permanently blocked
        map_data = get_shared_map()
        edges = map_data["edges"]
        bc_edge = next(e for e in edges if e["from"] == "B" and e["to"] == "C")
        self.assertTrue(bc_edge["blocked"])

    def test_invalid_event_raises_http_exception(self):
        with open(FIXTURES_DIR / "event_invalid_schema.json", "r", encoding="utf-8") as f:
            invalid_payload = json.load(f)
        with self.assertRaises(HTTPException) as ctx:
            ingest_event(invalid_payload)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_decision_traces_endpoint(self):
        with open(FIXTURES_DIR / "event_temporary_person.json", "r", encoding="utf-8") as f:
            payload = json.load(f)
        ingest_event(payload)
        traces = get_decision_traces(limit=20)
        self.assertIsInstance(traces, list)
        self.assertGreater(len(traces), 0)


if __name__ == "__main__":
    unittest.main()
