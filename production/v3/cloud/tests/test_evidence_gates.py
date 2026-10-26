"""Generated test objects exercise boundaries; they are never trial evidence."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from ..core.orchestrator import SlowLoopOrchestrator
from ..core.recheck_tools import CloudRecheckTools
from ..core.simulated_recheck_tools import SimulatedRecheckTools
from ..core.state_rules import CloudStateRulesEngine
from ..schema.models import BlockedEdgeEventV1, ClearanceResult, EdgeRef, OutcomeType
try:
    from ...vision import Obstacle, VisionResult
except ImportError:  # unittest/pytest may load cloud as the top-level package
    from vision import Obstacle, VisionResult


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class EvidenceGateTests(unittest.TestCase):
    def test_unconfigured_cloud_does_not_turn_client_person_label_into_temporary_evidence(self):
        payload = json.loads((FIXTURES / "event_temporary_person.json").read_text(encoding="utf-8"))
        service = SlowLoopOrchestrator()
        result = service.process_event(payload)
        self.assertEqual(result["outcome"], "UNCERTAIN")
        self.assertEqual(result["evidence_mode"], "unavailable")
        self.assertIsNone(result["recheck"]["clearance"]["free_clearance_m"])
        self.assertTrue(service.map_sync.is_edge_blocked("B", "C",
                        now=datetime.now(timezone.utc) + timedelta(days=30)))

    def test_simulator_requires_explicit_rule_opt_in(self):
        event = BlockedEdgeEventV1(**json.loads(
            (FIXTURES / "event_temporary_person.json").read_text(encoding="utf-8")))
        output = SimulatedRecheckTools().execute_all(event.event_id, event.edge, [], event.observations)
        result, needs_model = CloudStateRulesEngine.evaluate(output)
        self.assertEqual(result.outcome, OutcomeType.UNCERTAIN)
        self.assertFalse(needs_model)
        self.assertEqual(output.evidence_mode, "simulated")

    def test_injected_detector_is_called_instead_of_using_client_classes(self):
        class Detector:
            calls = 0
            def detect(self, frame):
                self.calls += 1
                return VisionResult((Obstacle("backpack", 0.7, (1, 1, 8, 8), (4, 7), (0, 0.3, 0)),),
                                    (0, 0.3, 0), 1.0)
        detector = Detector()
        tool = CloudRecheckTools(detector=detector)
        result = tool.detect([FIXTURES / "keyframes/chair_table_b_c_1.jpg"],
                             fallback_classes=["chair"], fallback_confidence=1.0)
        self.assertEqual(detector.calls, 1)
        self.assertEqual(result.classes, ["backpack"])
        self.assertEqual(result.evidence_status, "observed")
        self.assertAlmostEqual(result.mask_coverage_percent, 30.0)

    def test_clearance_requires_a_source_and_recomputes_threshold(self):
        tool = CloudRecheckTools(clearance_provider=lambda paths: ClearanceResult(
            evidence_status="observed", measurement_source="unit-test surveyed log", free_clearance_m=0.95,
            meets_ms1184_standard=True))
        result = tool.clearance(keyframe_paths=["test-recording"])
        self.assertEqual(result.free_clearance_m, 0.95)
        self.assertFalse(result.meets_ms1184_standard)

    def test_evidence_cannot_be_read_outside_configured_root(self):
        class Detector:
            def detect(self, frame):
                raise AssertionError("detector must not receive an escaped path")
        tool = CloudRecheckTools(detector=Detector(), keyframe_root=FIXTURES / "keyframes")
        result = tool.execute_all("test-path", EdgeRef(from_node="B", to_node="C"),
                                  ["../event_temporary_person.json"], None)
        self.assertEqual(result.evidence_mode, "unavailable")
        self.assertEqual(result.detection.classes, [])

    def test_temporary_report_cannot_expire_an_approved_closure(self):
        service = SlowLoopOrchestrator()
        now = datetime.now(timezone.utc)
        service.map_sync.apply_lasting_closure("B", "C", "test-ticket")
        service.map_sync.apply_temporary_block("B", "C", expiry_minutes=10, now=now)
        self.assertTrue(service.map_sync.is_edge_blocked("B", "C", now=now + timedelta(days=30)))
