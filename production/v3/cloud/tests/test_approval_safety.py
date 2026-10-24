"""Tests for approval safety features: duplicate prevention and expiry escalation."""

from datetime import datetime, timedelta, timezone
import unittest

from ..core.human_approval import HumanApprovalManager
from ..core.map_sync import MapSyncManager
from ..schema.models import EdgeRef, TicketStatus


class DuplicateTicketPreventionTests(unittest.TestCase):
    """Verify that only one PENDING ticket per edge is allowed."""

    def setUp(self):
        self.map_sync = MapSyncManager()
        self.approval = HumanApprovalManager(self.map_sync)
        self.edge = EdgeRef(from_node="B", to_node="C")

    def test_duplicate_pending_ticket_raises(self):
        """Creating a second PENDING ticket for the same edge raises ValueError."""
        self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        with self.assertRaises(ValueError) as ctx:
            self.approval.create_ticket(
                event_id="evt-002", edge=self.edge,
                detected_classes=["table"], measured_clearance_m=0.5,
                justification="Table now blocking same path.",
            )
        self.assertIn("PENDING ticket", str(ctx.exception))
        self.assertIn("B-C", str(ctx.exception))

    def test_duplicate_allowed_after_approval(self):
        """After first ticket is approved, a new ticket for the same edge is allowed."""
        t1 = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        self.approval.review_ticket(t1.ticket_id, "APPROVE", "staff-1")

        # Should succeed now
        t2 = self.approval.create_ticket(
            event_id="evt-002", edge=self.edge,
            detected_classes=["table"], measured_clearance_m=0.5,
            justification="Table now blocking same path.",
        )
        self.assertEqual(t2.status, TicketStatus.PENDING)

    def test_duplicate_allowed_after_rejection(self):
        """After first ticket is rejected, a new ticket for the same edge is allowed."""
        t1 = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        self.approval.review_ticket(t1.ticket_id, "REJECT", "staff-1")

        t2 = self.approval.create_ticket(
            event_id="evt-003", edge=self.edge,
            detected_classes=["box"], measured_clearance_m=0.55,
            justification="Box left in corridor again.",
        )
        self.assertEqual(t2.status, TicketStatus.PENDING)

    def test_different_edges_allowed_concurrently(self):
        """Separate PENDING tickets for different edges are fine."""
        edge_ef = EdgeRef(from_node="E", to_node="F")
        self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking B-C corridor.",
        )
        # Different edge — should succeed
        t2 = self.approval.create_ticket(
            event_id="evt-002", edge=edge_ef,
            detected_classes=["box"], measured_clearance_m=0.5,
            justification="Box blocking E-F corridor.",
        )
        self.assertEqual(t2.status, TicketStatus.PENDING)


class TicketExpiryEscalationTests(unittest.TestCase):
    """Verify that unreviewed tickets auto-escalate after 24 hours."""

    def setUp(self):
        self.map_sync = MapSyncManager()
        self.approval = HumanApprovalManager(self.map_sync)
        self.edge = EdgeRef(from_node="B", to_node="C")

    def test_ticket_not_expired_before_24_hours(self):
        """PENDING ticket remains PENDING if checked before 24 hours."""
        ticket = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        # Check at 23 hours
        future = ticket.created_at + timedelta(hours=23)
        escalated = self.approval.check_ticket_expiries(now=future)
        self.assertEqual(len(escalated), 0)
        self.assertEqual(ticket.status, TicketStatus.PENDING)

    def test_ticket_expired_after_24_hours(self):
        """PENDING ticket becomes EXPIRED after 24 hours with no review."""
        ticket = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        # Check at 25 hours
        future = ticket.created_at + timedelta(hours=25)
        escalated = self.approval.check_ticket_expiries(now=future)
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0].ticket_id, ticket.ticket_id)
        self.assertEqual(ticket.status, TicketStatus.EXPIRED)
        self.assertIn("Auto-escalated", ticket.resolution_notes)

    def test_expired_ticket_edge_stays_blocked(self):
        """After expiry escalation, the edge remains blocked (fail-safe extended)."""
        ticket = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        future = ticket.created_at + timedelta(hours=25)
        self.approval.check_ticket_expiries(now=future)
        # Edge must still be blocked
        self.assertTrue(self.map_sync.is_edge_blocked("B", "C", now=future))

    def test_already_resolved_ticket_not_escalated(self):
        """Approved or rejected tickets are not escalated."""
        ticket = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        self.approval.review_ticket(ticket.ticket_id, "APPROVE", "staff-1")
        future = ticket.created_at + timedelta(hours=48)
        escalated = self.approval.check_ticket_expiries(now=future)
        self.assertEqual(len(escalated), 0)
        self.assertEqual(ticket.status, TicketStatus.APPROVED)

    def test_new_ticket_allowed_after_expiry(self):
        """After a ticket expires, a new PENDING ticket for the same edge is allowed."""
        ticket = self.approval.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        future = ticket.created_at + timedelta(hours=25)
        self.approval.check_ticket_expiries(now=future)
        self.assertEqual(ticket.status, TicketStatus.EXPIRED)

        # Should be allowed now since the old ticket is EXPIRED, not PENDING
        t2 = self.approval.create_ticket(
            event_id="evt-002", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair still there after escalation.",
        )
        self.assertEqual(t2.status, TicketStatus.PENDING)


if __name__ == "__main__":
    unittest.main()
