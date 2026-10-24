"""Tests for Graviton / OpenCV 5 Re-check tools."""

from pathlib import Path
import unittest

from ..core.recheck_tools import CloudRecheckTools
from ..schema.models import EdgeRef


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "keyframes"


class RecheckToolsTests(unittest.TestCase):
    def setUp(self):
        self.tools = CloudRecheckTools()
        self.edge = EdgeRef(from_node="B", to_node="C")

    def test_motion_optical_flow_on_test_keyframes(self):
        f1 = FIXTURES_DIR / "chair_table_b_c_1.jpg"
        f2 = FIXTURES_DIR / "chair_table_b_c_2.jpg"
        if f1.exists() and f2.exists():
            motion_res = self.tools.motion([f1, f2])
            self.assertIn(motion_res.motion_type, ("static", "moving"))
            self.assertGreaterEqual(motion_res.average_flow_magnitude, 0.0)

    def test_clearance_calculation_fully_blocked(self):
        zones = {"left": "occupied", "centre": "occupied", "right": "occupied"}
        res = self.tools.clearance(occupied_zones=zones)
        self.assertIsNone(res.free_clearance_m)
        self.assertIsNone(res.meets_ms1184_standard)
        self.assertEqual(res.evidence_status, "unknown")

    def test_clearance_calculation_clear_path(self):
        zones = {"left": "clear", "centre": "clear", "right": "occupied"}
        res = self.tools.clearance(occupied_zones=zones)
        self.assertIsNone(res.free_clearance_m)
        self.assertIsNone(res.meets_ms1184_standard)

    def test_missing_frames_do_not_become_fallback_detections_or_static_motion(self):
        detection = self.tools.detect([], fallback_classes=["chair"], fallback_confidence=0.99)
        self.assertEqual(detection.classes, [])
        self.assertEqual(detection.evidence_status, "unknown")
        self.assertIsNone(detection.mask_coverage_percent)
        motion = self.tools.motion([], fallback_is_moving=False)
        self.assertEqual(motion.motion_type, "undetermined")
        self.assertIsNone(motion.average_flow_magnitude)


if __name__ == "__main__":
    unittest.main()
