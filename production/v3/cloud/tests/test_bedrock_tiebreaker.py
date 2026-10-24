"""Tests for Bedrock tie-breaker and Lambda hard-rule validator."""

from datetime import datetime, timezone
import unittest

from ..core.bedrock_tiebreaker import BedrockTieBreaker, LambdaHardRuleValidator
from ..schema.models import (
    AgentProposal,
    ClearanceResult,
    DetectionResult,
    EdgeHistoryEntry,
    EdgeRef,
    MotionResult,
    OutcomeType,
    RecheckToolsOutput,
)


class BedrockTieBreakerTests(unittest.TestCase):
    def setUp(self):
        self.edge = EdgeRef(from_node="B", to_node="C")
        self.tools_output = RecheckToolsOutput(
            event_id="evt-tiebreak",
            edge=self.edge,
            detection=DetectionResult(classes=["chair"], confidence=0.65, mask_coverage_percent=20.0),
            motion=MotionResult(is_moving=False, average_flow_magnitude=0.1, motion_type="static"),
            clearance=ClearanceResult(corridor_width_m=2.4, free_clearance_m=1.60, meets_ms1184_standard=True),
            history=[],
        )
        self.tiebreaker = BedrockTieBreaker()
        self.validator = LambdaHardRuleValidator()

    def test_offline_tiebreaker_returns_valid_proposal(self):
        proposal = self.tiebreaker.resolve_conflict(self.tools_output)
        self.assertEqual(proposal.outcome, OutcomeType.UNCERTAIN)
        self.assertTrue(proposal.tiebreaker_used)
        self.assertIn("clearance", proposal.justification)

    def test_validator_enforces_human_approval_for_lasting_proposal(self):
        # LLM proposes LASTING without facilities review flag
        bad_llm_proposal = AgentProposal(
            outcome=OutcomeType.LASTING,
            expiry_minutes=None,
            justification="Persistent furniture observed.",
            requires_facilities_approval=False,  # Violation!
            tiebreaker_used=True,
        )
        sanitized = self.validator.validate_and_sanitize(bad_llm_proposal, self.tools_output)
        self.assertTrue(sanitized.requires_facilities_approval)

    def test_validator_rejects_llm_reopening_chronically_blocked_corridor(self):
        # Tools show chronic physical blockage
        restricted_output = RecheckToolsOutput(
            event_id="evt-chronic",
            edge=self.edge,
            detection=DetectionResult(classes=["table", "chairs"], confidence=0.85, mask_coverage_percent=60.0),
            motion=MotionResult(is_moving=False, average_flow_magnitude=0.0, motion_type="static"),
            clearance=ClearanceResult(corridor_width_m=2.4, free_clearance_m=0.50, meets_ms1184_standard=False),
            history=[
                EdgeHistoryEntry(
                    timestamp=datetime(2026, 10, 24, 2, 0, 0, tzinfo=timezone.utc),
                    event_id="evt-prior",
                    outcome=OutcomeType.LASTING,
                    clearance_m=0.5,
                )
            ],
        )

        # Flawed LLM proposal tries to mark it as TEMPORARY
        flawed_llm_proposal = AgentProposal(
            outcome=OutcomeType.TEMPORARY,
            expiry_minutes=5,
            justification="Looks like someone might move it soon.",
            requires_facilities_approval=False,
            tiebreaker_used=True,
        )

        # Validator MUST override and enforce LASTING with facilities approval!
        sanitized = self.validator.validate_and_sanitize(flawed_llm_proposal, restricted_output)
        self.assertEqual(sanitized.outcome, OutcomeType.LASTING)
        self.assertTrue(sanitized.requires_facilities_approval)
        self.assertIn("Validator override", sanitized.justification)


if __name__ == "__main__":
    unittest.main()
