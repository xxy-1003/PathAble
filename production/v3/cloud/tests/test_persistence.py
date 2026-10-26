"""Tests for shared-map persistence and approval ticket persistence.

Verifies that MapSyncManager and HumanApprovalManager state survives
round-trip save/load cycles and that corrupted files are handled gracefully.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ..core.map_sync import MapSyncManager
from ..core.human_approval import HumanApprovalManager
from ..schema.models import EdgeRef, TicketStatus


class MapPersistenceTests(unittest.TestCase):
    """MapSyncManager persistence round-trip tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.persist_file = Path(self._tmpdir) / "map_state.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_restore_basic(self):
        """Version, nodes, edges survive a restart."""
        mgr = MapSyncManager(persistence_path=self.persist_file)
        mgr.apply_temporary_block("B", "C", expiry_minutes=10)
        self.assertEqual(mgr.version, 2)
        self.assertTrue(self.persist_file.exists())

        # Simulate restart
        mgr2 = MapSyncManager(persistence_path=self.persist_file)
        self.assertEqual(mgr2.version, 2)
        self.assertTrue(mgr2.is_edge_blocked("B", "C"))

    def test_temporary_expiry_survives_restart(self):
        """Temporary block expiry datetime is persisted and correctly restored."""
        now = datetime(2026, 10, 24, 6, 0, 0, tzinfo=timezone.utc)
        mgr = MapSyncManager(persistence_path=self.persist_file)
        mgr.apply_temporary_block("B", "C", expiry_minutes=10, now=now)

        # Restart
        mgr2 = MapSyncManager(persistence_path=self.persist_file)
        # Still blocked before expiry
        self.assertTrue(mgr2.is_edge_blocked("B", "C", now=now + timedelta(minutes=5)))
        # Unblocked after expiry
        self.assertFalse(mgr2.is_edge_blocked("B", "C", now=now + timedelta(minutes=11)))

    def test_lasting_closure_metadata_survives_restart(self):
        """Edge metadata from lasting closure persists across restarts."""
        mgr = MapSyncManager(persistence_path=self.persist_file)
        mgr.apply_lasting_closure("B", "C", ticket_id="T-17")
        self.assertTrue(mgr.is_edge_blocked("B", "C"))
        self.assertEqual(mgr.version, 2)

        # Restart
        mgr2 = MapSyncManager(persistence_path=self.persist_file)
        self.assertTrue(mgr2.is_edge_blocked("B", "C"))
        self.assertEqual(mgr2.version, 2)
        self.assertIn("B-C", mgr2._edge_metadata)

    def test_corrupted_file_falls_back_to_defaults(self):
        """Corrupted JSON file doesn't crash — falls back to fresh state."""
        self.persist_file.write_text("NOT VALID JSON {{{{", encoding="utf-8")
        mgr = MapSyncManager(persistence_path=self.persist_file)
        # Should fall through to defaults
        self.assertEqual(mgr.version, 1)
        self.assertFalse(mgr.is_edge_blocked("B", "C"))

    def test_no_persistence_path_works_normally(self):
        """Without persistence_path, MapSyncManager works as before (in-memory)."""
        mgr = MapSyncManager()
        mgr.apply_temporary_block("B", "C", expiry_minutes=10)
        self.assertEqual(mgr.version, 2)
        self.assertFalse(self.persist_file.exists())

    def test_reopen_clears_persisted_metadata(self):
        """Reopen edge removes metadata, persisted correctly."""
        mgr = MapSyncManager(persistence_path=self.persist_file)
        mgr.apply_lasting_closure("B", "C", ticket_id="T-17")
        mgr.reopen_edge("B", "C", reason="cleared")

        mgr2 = MapSyncManager(persistence_path=self.persist_file)
        self.assertFalse(mgr2.is_edge_blocked("B", "C"))
        self.assertNotIn("B-C", mgr2._edge_metadata)


class TicketPersistenceTests(unittest.TestCase):
    """HumanApprovalManager persistence round-trip tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.map_persist = Path(self._tmpdir) / "map_state.json"
        self.ticket_persist = Path(self._tmpdir) / "tickets.json"
        self.edge = EdgeRef(from_node="B", to_node="C")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_ticket_survives_restart(self):
        """PENDING ticket is persisted and restored on restart."""
        ms = MapSyncManager(persistence_path=self.map_persist)
        mgr = HumanApprovalManager(ms, persistence_path=self.ticket_persist)
        ticket = mgr.create_ticket(
            event_id="evt-001",
            edge=self.edge,
            detected_classes=["chair"],
            measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        self.assertTrue(self.ticket_persist.exists())

        # Restart
        ms2 = MapSyncManager(persistence_path=self.map_persist)
        mgr2 = HumanApprovalManager(ms2, persistence_path=self.ticket_persist)
        restored = mgr2.get_ticket(ticket.ticket_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, TicketStatus.PENDING)
        self.assertEqual(restored.event_id, "evt-001")

    def test_counter_persists(self):
        """Ticket counter continues from where it left off after restart."""
        ms = MapSyncManager(persistence_path=self.map_persist)
        mgr = HumanApprovalManager(ms, persistence_path=self.ticket_persist)
        t1 = mgr.create_ticket(
            event_id="evt-001", edge=self.edge,
            detected_classes=["chair"], measured_clearance_m=0.6,
            justification="Chair blocking path.",
        )
        # Approve so we can create another for the same edge
        mgr.review_ticket(t1.ticket_id, "APPROVE", "staff-1")

        # Restart and create another ticket on a different edge
        ms2 = MapSyncManager(persistence_path=self.map_persist)
        mgr2 = HumanApprovalManager(ms2, persistence_path=self.ticket_persist)
        edge2 = EdgeRef(from_node="E", to_node="F")
        t2 = mgr2.create_ticket(
            event_id="evt-002", edge=edge2,
            detected_classes=["box"], measured_clearance_m=0.5,
            justification="Box on corridor floor.",
        )
        # Should be T-18, not T-17 again
        self.assertNotEqual(t2.ticket_id, t1.ticket_id)
        self.assertEqual(t2.ticket_id, "T-18")

    def test_corrupted_ticket_file_handled_gracefully(self):
        """Corrupted tickets file doesn't crash — starts with empty tickets."""
        self.ticket_persist.write_text("{bad json", encoding="utf-8")
        ms = MapSyncManager()
        mgr = HumanApprovalManager(ms, persistence_path=self.ticket_persist)
        self.assertEqual(len(mgr.list_tickets()), 0)


if __name__ == "__main__":
    unittest.main()
