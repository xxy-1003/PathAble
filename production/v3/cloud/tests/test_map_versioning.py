"""Tests for Map synchronization, version bumping, and automatic expiry."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from ..core.map_sync import MapSyncManager


MAP_PATH = Path(__file__).resolve().parents[4] / "production" / "map_graph.json"


class MapVersioningTests(unittest.TestCase):
    def setUp(self):
        self.mgr = MapSyncManager(initial_map_path=MAP_PATH if MAP_PATH.exists() else None)

    def test_initial_state(self):
        self.assertEqual(self.mgr.version, 1)
        self.assertFalse(self.mgr.is_edge_blocked("B", "C"))

    def test_apply_temporary_block_bumps_version(self):
        v = self.mgr.apply_temporary_block("B", "C", expiry_minutes=10)
        self.assertEqual(v, 2)
        self.assertTrue(self.mgr.is_edge_blocked("B", "C"))

    def test_temporary_block_auto_expiry_reopens_edge(self):
        now = datetime(2026, 10, 24, 3, 0, 0, tzinfo=timezone.utc)
        self.mgr.apply_temporary_block("B", "C", expiry_minutes=10, now=now)
        self.assertTrue(self.mgr.is_edge_blocked("B", "C", now=now))

        # Fast-forward 11 minutes
        future = now + timedelta(minutes=11)
        reopened = self.mgr.check_expiries(future)
        self.assertTrue(reopened)
        self.assertFalse(self.mgr.is_edge_blocked("B", "C", now=future))
        self.assertEqual(self.mgr.version, 3)

    def test_lasting_closure_and_reopen(self):
        v_close = self.mgr.apply_lasting_closure("B", "C", ticket_id="T-17")
        self.assertEqual(v_close, 2)
        self.assertTrue(self.mgr.is_edge_blocked("B", "C"))

        v_reopen = self.mgr.reopen_edge("B", "C", reason="Maintenance complete")
        self.assertEqual(v_reopen, 3)
        self.assertFalse(self.mgr.is_edge_blocked("B", "C"))


if __name__ == "__main__":
    unittest.main()
