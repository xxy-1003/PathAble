"""Tests for Cloud State Rules (TEMPORARY, UNCERTAIN, LASTING)."""

from datetime import datetime, timedelta, timezone
import unittest

from ..core.state_rules import CloudStateRulesEngine
from ..schema.models import (
    ClearanceResult,
    DetectionResult,
    EdgeHistoryEntry,
    EdgeRef,
    MotionResult,
    OutcomeType,
    RecheckToolsOutput,
)


class StateRulesTests(unittest.TestCase):
    def setUp(self):
        self.edge = EdgeRef(from_node="B", to_node="C")

    def test_temporary_rule_moving_person(self):
        output = RecheckToolsOutput(
            event_id="evt-1",
            edge=self.edge,
            detection=DetectionResult(evidence_status="observed", classes=["person"], confidence=0.88, mask_coverage_percent=40.0),
            motion=MotionResult(evidence_status="observed", is_moving=True, average_flow_magnitude=3.2, motion_type="moving"),
            clearance=ClearanceResult(evidence_status="observed", corridor_width_m=2.4, free_clearance_m=0.8, meets_ms1184_standard=False),
            history=[],
        )
        proposal, needs_tiebreaker = CloudStateRulesEngine.evaluate(output)
        self.assertEqual(proposal.outcome, OutcomeType.TEMPORARY)
        self.assertEqual(proposal.expiry_minutes, 10)
        self.assertFalse(proposal.requires_facilities_approval)
        self.assertFalse(needs_tiebreaker)

    def test_uncertain_rule_single_static_chair_without_history(self):
        output = RecheckToolsOutput(
            event_id="evt-2",
            edge=self.edge,
            detection=DetectionResult(evidence_status="observed", classes=["chair"], confidence=0.75, mask_coverage_percent=35.0),
            motion=MotionResult(evidence_status="observed", is_moving=False, average_flow_magnitude=0.1, motion_type="static"),
            clearance=ClearanceResult(evidence_status="observed", corridor_width_m=2.4, free_clearance_m=0.75, meets_ms1184_standard=False),
            history=[],  # No prior report
        )
        proposal, needs_tiebreaker = CloudStateRulesEngine.evaluate(output)
        self.assertEqual(proposal.outcome, OutcomeType.UNCERTAIN)
        self.assertIsNone(proposal.expiry_minutes)
        self.assertFalse(proposal.requires_facilities_approval)
        self.assertFalse(needs_tiebreaker)

    def test_lasting_rule_static_object_across_multiple_reports_spaced_over_15_mins(self):
        t0 = datetime(2026, 10, 24, 3, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 24, 3, 22, 0, tzinfo=timezone.utc)  # 22 mins later

        prior_entry = EdgeHistoryEntry(evidence_mode="recorded",
            timestamp=t0,
            event_id="evt-0193",
            outcome=OutcomeType.UNCERTAIN,
            clearance_m=0.6,
            classes=["chair", "dining table"],
        )
        output = RecheckToolsOutput(
            event_id="evt-0205",
            edge=self.edge,
            detection=DetectionResult(evidence_status="observed", classes=["chair", "dining table"], confidence=0.85, mask_coverage_percent=55.0),
            motion=MotionResult(evidence_status="observed", is_moving=False, average_flow_magnitude=0.05, motion_type="static"),
            clearance=ClearanceResult(evidence_status="observed", corridor_width_m=2.4, free_clearance_m=0.6, meets_ms1184_standard=False),
            history=[prior_entry],
        )
        proposal, needs_tiebreaker = CloudStateRulesEngine.evaluate(output, current_time=t1)
        self.assertEqual(proposal.outcome, OutcomeType.LASTING)
        self.assertTrue(proposal.requires_facilities_approval)
        self.assertFalse(needs_tiebreaker)

    def test_tool_conflict_triggers_tiebreaker(self):
        # Static chair, but clearance is 1.6m (meets MS 1184 >= 1.20m)
        output = RecheckToolsOutput(
            event_id="evt-conf",
            edge=self.edge,
            detection=DetectionResult(evidence_status="observed", classes=["chair"], confidence=0.65, mask_coverage_percent=25.0),
            motion=MotionResult(evidence_status="observed", is_moving=False, average_flow_magnitude=0.1, motion_type="static"),
            clearance=ClearanceResult(evidence_status="observed", corridor_width_m=2.4, free_clearance_m=1.60, meets_ms1184_standard=True),
            history=[],
        )
        proposal, needs_tiebreaker = CloudStateRulesEngine.evaluate(output)
        self.assertTrue(needs_tiebreaker)


if __name__ == "__main__":
    unittest.main()
