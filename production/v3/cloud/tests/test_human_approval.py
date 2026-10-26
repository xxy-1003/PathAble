"""Tests for Facilities Human Approval workflow (Proposal Section 9.5)."""

import unittest

from ..core.human_approval import HumanApprovalManager
from ..core.map_sync import MapSyncManager
from ..schema.models import EdgeRef, TicketStatus


class HumanApprovalTests(unittest.TestCase):
    def setUp(self):
        self.map_sync = MapSyncManager()
        self.approval = HumanApprovalManager(self.map_sync)
        self.edge = EdgeRef(from_node="B", to_node="C")

    def test_ticket_creation_and_failsafe_block(self):
        ticket = self.approval.create_ticket(
            event_id="evt-0205",
            edge=self.edge,
            detected_classes=["chair", "dining table"],
            measured_clearance_m=0.60,
            justification="Persistent furniture across multiple runs.",
        )
        self.assertEqual(ticket.ticket_id, "T-17")
        self.assertEqual(ticket.status, TicketStatus.PENDING)
        # Invariant: edge must be blocked under fail-safe hold
        self.assertTrue(self.map_sync.is_edge_blocked("B", "C"))

    def test_approve_closes_edge_permanently(self):
        ticket = self.approval.create_ticket(
            event_id="evt-0205",
            edge=self.edge,
            detected_classes=["table"],
            measured_clearance_m=0.55,
            justification="Clearance 0.55m below MS 1184 minimum.",
        )
        resolved_ticket, new_version = self.approval.review_ticket(
            ticket_id=ticket.ticket_id,
            action="APPROVE",
            reviewer_id="facilities-lead-01",
            notes="Closing corridor section for scheduled maintenance",
        )
        self.assertEqual(resolved_ticket.status, TicketStatus.APPROVED)
        self.assertEqual(resolved_ticket.resolved_by, "facilities-lead-01")
        self.assertTrue(self.map_sync.is_edge_blocked("B", "C"))
        self.assertGreater(new_version, 1)

    def test_reject_reopens_edge(self):
        ticket = self.approval.create_ticket(
            event_id="evt-0205",
            edge=self.edge,
            detected_classes=["table"],
            measured_clearance_m=0.70,
            justification="Furniture reported blocking path.",
        )
        resolved_ticket, new_version = self.approval.review_ticket(
            ticket_id=ticket.ticket_id,
            action="REJECT",
            reviewer_id="facilities-inspector-02",
            notes="Physical inspection shows corridor is now cleared",
        )
        self.assertEqual(resolved_ticket.status, TicketStatus.REJECTED)
        # Edge should be reopened
        self.assertFalse(self.map_sync.is_edge_blocked("B", "C"))

    def test_double_review_rejected(self):
        ticket = self.approval.create_ticket(
            event_id="evt-double",
            edge=self.edge,
            detected_classes=["box"],
            measured_clearance_m=0.6,
            justification="Box on floor.",
        )
        self.approval.review_ticket(ticket.ticket_id, "APPROVE", "staff-1")
        with self.assertRaises(ValueError) as ctx:
            self.approval.review_ticket(ticket.ticket_id, "REJECT", "staff-2")
        self.assertIn("already resolved", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
