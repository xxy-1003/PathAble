"""Cloud State Rules engine (Proposal Section 9.3).

Applies the deterministic cloud decision rules based on evidence from the four re-check tools:
- TEMPORARY: Moving object or transient obstruction (10-minute auto-expiry; no human needed)
- UNCERTAIN: Static object, single report / no history, clearance near threshold (remains blocked, await next report)
- LASTING: Static object in >=2 reports >=15 mins apart, clearance < 1.20m MS 1184 (generates human approval ticket)

Also identifies tool conflicts that require language model tie-breaking (Section 9.4).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from ..schema.models import (
    AgentProposal,
    ClearanceResult,
    DetectionResult,
    EdgeRef,
    MotionResult,
    OutcomeType,
    RecheckToolsOutput,
)


logger = logging.getLogger("pathable.cloud.state_rules")

TEMPORARY_EXPIRY_MINUTES = 10
LASTING_MIN_REPORT_INTERVAL_MINUTES = 15.0
MS_1184_MIN_CLEAR_WIDTH_M = 1.20


class CloudStateRulesEngine:
    """Evaluates re-check evidence against Section 9.3 decision rules."""

    @staticmethod
    def evaluate(
        tools_output: RecheckToolsOutput,
        current_time: Optional[datetime] = None,
        *, allow_simulated: bool = False,
    ) -> Tuple[AgentProposal, bool]:
        """Evaluates tools output and returns (proposal, needs_tiebreaker).

        Returns:
            proposal: The generated proposal with outcome, expiry, and justification.
            needs_tiebreaker: True if tool outputs conflict and Bedrock tie-breaker is required.
        """
        now = current_time or datetime.now(timezone.utc)
        motion = tools_output.motion
        detection = tools_output.detection
        clearance = tools_output.clearance
        history = tools_output.history

        allowed = {"observed", "simulated"} if allow_simulated else {"observed"}
        if (any(item.evidence_status not in allowed for item in (detection, motion, clearance))
                or clearance.free_clearance_m is None
                or motion.average_flow_magnitude is None or motion.motion_type == "undetermined"
                or not detection.has_blocking_objects or detection.confidence < 0.60):
            return (AgentProposal(outcome=OutcomeType.UNCERTAIN,
                                  justification="Re-check evidence is unavailable or simulated. "
                                                "Keep the edge blocked pending recorded measurement or human review."), False)

        # 1. TEMPORARY Rule:
        # Moving object (e.g. person, trolley, moving obstacle)
        if motion.is_moving or "person" in detection.classes:
            justification = (
                f"Obstacle ({', '.join(detection.classes) or 'moving object'}) was identified as transient motion. "
                f"Edge is temporarily blocked with automatic {TEMPORARY_EXPIRY_MINUTES}-minute expiry."
            )
            return (
                AgentProposal(
                    outcome=OutcomeType.TEMPORARY,
                    expiry_minutes=TEMPORARY_EXPIRY_MINUTES,
                    justification=justification,
                    requires_facilities_approval=False,
                    tiebreaker_used=False,
                ),
                False,
            )

        # 2. Tool Conflict Check (Section 9.4):
        # Example: static object with adequate clearance (>= 1.20m), but local device reported it blocked.
        if not motion.is_moving and clearance.meets_ms1184_standard and clearance.free_clearance_m >= 1.20:
            logger.info("Tool conflict detected: static object with adequate clearance (%.2fm)", clearance.free_clearance_m)
            justification = (
                f"Perception reported blockage but clearance measurement shows {clearance.free_clearance_m}m "
                f"which meets MS 1184 standards. Bedrock tie-breaker consultation required."
            )
            return (
                AgentProposal(
                    outcome=OutcomeType.UNCERTAIN,
                    expiry_minutes=None,
                    justification=justification,
                    requires_facilities_approval=False,
                    tiebreaker_used=True,
                ),
                True,  # Needs tie-breaker
            )

        # 3. LASTING Rule:
        # Static object seen in at least 2 reports at least 15 minutes apart,
        # with clearance below MS 1184:2014 minimum width (< 1.20m)
        if not clearance.meets_ms1184_standard:
            # Check history for a previous report >= 15 minutes apart
            qualifying_prior_report = False
            for entry in history:
                expected_mode = "simulated" if allow_simulated else "recorded"
                if entry.evidence_mode != expected_mode:
                    continue
                if (entry.outcome == OutcomeType.TEMPORARY or entry.clearance_m is None
                        or entry.clearance_m >= MS_1184_MIN_CLEAR_WIDTH_M
                        or not set(entry.classes).intersection(detection.classes)):
                    continue
                delta_minutes = (now - entry.timestamp).total_seconds() / 60.0
                if delta_minutes >= LASTING_MIN_REPORT_INTERVAL_MINUTES:
                    qualifying_prior_report = True
                    break

            if qualifying_prior_report:
                justification = (
                    f"Persistent obstruction ({', '.join(detection.classes) or 'furniture'}) confirmed across multiple reports "
                    f"spaced over {int(LASTING_MIN_REPORT_INTERVAL_MINUTES)} minutes with restricted clearance of {clearance.free_clearance_m}m. "
                    f"Approval request submitted to facilities staff."
                )
                return (
                    AgentProposal(
                        outcome=OutcomeType.LASTING,
                        expiry_minutes=None,
                        justification=justification,
                        requires_facilities_approval=True,
                        tiebreaker_used=False,
                    ),
                    False,
                )

        # 4. UNCERTAIN Rule (Default for static without 15-min history):
        # Static object, no history yet, or clearance constrained
        justification = (
            f"Static obstacle ({', '.join(detection.classes) or 'object'}) detected without historical confirmation. "
            f"Edge remains blocked pending subsequent passage or facilities inspection; never directing user to look."
        )
        return (
            AgentProposal(
                outcome=OutcomeType.UNCERTAIN,
                expiry_minutes=None,
                justification=justification,
                requires_facilities_approval=False,
                tiebreaker_used=False,
            ),
            False,
        )
