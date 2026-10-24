"""End-to-end Cloud Orchestrator for PathAble Slow Loop.

Coordinates intake, re-check tools, rule evaluation, Bedrock tie-breaker,
Lambda hard-rule validation, map sync, human approval, and CloudWatch audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..schema.models import (
    AgentProposal,
    BlockedEdgeEventV1,
    EdgeHistoryEntry,
    OutcomeType,
    RecheckToolsOutput,
)
from .audit_logger import CloudAuditLogger
from .bedrock_tiebreaker import BedrockTieBreaker, LambdaHardRuleValidator
from .human_approval import HumanApprovalManager
from .intake import IdempotentIntakeStore
from .map_sync import MapSyncManager
from .recheck_tools import CloudRecheckTools
from .state_rules import CloudStateRulesEngine


logger = logging.getLogger("pathable.cloud.orchestrator")


class SlowLoopOrchestrator:
    """The central cloud agent orchestrating AWS slow-loop workflows."""

    def __init__(
        self,
        initial_map_path: Optional[str | Path] = None,
        bedrock_client=None,
    ):
        self.audit = CloudAuditLogger()
        self.intake_store = IdempotentIntakeStore()
        self.map_sync = MapSyncManager(initial_map_path)
        self.approval_mgr = HumanApprovalManager(self.map_sync)
        self.edge_history: Dict[str, List[EdgeHistoryEntry]] = {}

        self.recheck_tools = CloudRecheckTools(history_provider=self._get_history_for_edge)
        self.state_rules = CloudStateRulesEngine()
        self.tiebreaker = BedrockTieBreaker(aws_client=bedrock_client)
        self.validator = LambdaHardRuleValidator()

    def _get_history_for_edge(self, edge_key: str) -> List[EdgeHistoryEntry]:
        return self.edge_history.get(edge_key, [])

    def process_event(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for processing a blocked-edge event payload."""
        # 1. Idempotent Intake & Schema Validation
        event, is_duplicate, cached_result = self.intake_store.ingest(raw_payload)

        if is_duplicate and cached_result is not None:
            self.audit.log(
                event.event_id,
                "INTAKE",
                "DUPLICATE_RETURNED",
                {"cached_outcome": cached_result.get("outcome")},
            )
            return {
                "status": "DUPLICATE",
                "message": "Event already processed (idempotent response)",
                "result": cached_result,
            }

        self.audit.log(
            event.event_id,
            "INTAKE",
            "ACCEPTED",
            {
                "edge": event.edge.edge_key,
                "client_id": event.client_id,
                "classes": event.observations.obstacle_classes,
                "confidence": event.observations.confidence,
            },
        )

        # 2. Keyframes resolution
        keyframe_paths = [kf.filename for kf in event.keyframes]

        # 3. Execute Graviton / OpenCV 5 Re-check Tools
        tools_output = self.recheck_tools.execute_all(
            event_id=event.event_id,
            edge=event.edge,
            keyframe_paths=keyframe_paths,
            observations_summary=event.observations,
        )

        self.audit.log(
            event.event_id,
            "RECHECK_TOOLS",
            "COMPLETED",
            {
                "motion": tools_output.motion.motion_type,
                "flow_magnitude": round(tools_output.motion.average_flow_magnitude, 2),
                "clearance_m": tools_output.clearance.free_clearance_m,
                "meets_ms1184": tools_output.clearance.meets_ms1184_standard,
                "prior_reports": len(tools_output.history),
            },
        )

        # 4. Evaluate Cloud State Rules
        proposal, needs_tiebreaker = self.state_rules.evaluate(
            tools_output, current_time=event.timestamp
        )

        # 5. Language Model Tie-Breaker if tools conflict (Section 9.4)
        if needs_tiebreaker:
            self.audit.log(
                event.event_id,
                "BEDROCK",
                "INVOKING_TIEBREAKER",
                {"reason": "Tool conflict between occupancy and measured clearance"},
            )
            raw_proposal = self.tiebreaker.resolve_conflict(tools_output)
            # Lambda Hard Rule Validator check
            proposal = self.validator.validate_and_sanitize(raw_proposal, tools_output)
            self.audit.log(
                event.event_id,
                "VALIDATOR",
                "PROPOSAL_SANITIZED",
                {"outcome": proposal.outcome.value, "justification": proposal.justification},
            )

        # 6. Apply Outcome & Update Shared State
        ticket_id = None
        current_map_version = self.map_sync.version

        if proposal.outcome == OutcomeType.TEMPORARY:
            expiry = proposal.expiry_minutes or 10
            current_map_version = self.map_sync.apply_temporary_block(
                event.edge.from_node, event.edge.to_node, expiry_minutes=expiry, now=event.timestamp
            )
            self.audit.log(
                event.event_id,
                "MAP_SYNC",
                "TEMPORARY_BLOCK_APPLIED",
                {"expiry_minutes": expiry, "map_version": current_map_version},
            )

        elif proposal.outcome == OutcomeType.LASTING:
            # Create human approval ticket (fail-safe holds edge blocked)
            ticket = self.approval_mgr.create_ticket(
                event_id=event.event_id,
                edge=event.edge,
                detected_classes=tools_output.detection.classes,
                measured_clearance_m=tools_output.clearance.free_clearance_m,
                justification=proposal.justification,
                keyframes=[kf.filename for kf in event.keyframes],
            )
            ticket_id = ticket.ticket_id
            current_map_version = self.map_sync.version
            self.audit.log(
                event.event_id,
                "APPROVAL",
                "TICKET_GENERATED",
                {"ticket_id": ticket_id, "clearance_m": tools_output.clearance.free_clearance_m},
            )

        elif proposal.outcome == OutcomeType.UNCERTAIN:
            # Fail-safe: edge remains blocked for safety; recheck on next report
            current_map_version = self.map_sync.apply_temporary_block(
                event.edge.from_node, event.edge.to_node, expiry_minutes=60, now=event.timestamp
            )
            self.audit.log(
                event.event_id,
                "MAP_SYNC",
                "UNCERTAIN_FAILSAFE_HOLD",
                {"map_version": current_map_version},
            )

        # 7. Record to edge history for subsequent reports
        history_entry = EdgeHistoryEntry(
            timestamp=event.timestamp,
            event_id=event.event_id,
            outcome=proposal.outcome,
            clearance_m=tools_output.clearance.free_clearance_m,
            classes=tools_output.detection.classes,
        )
        self.edge_history.setdefault(event.edge.edge_key, []).append(history_entry)

        # 8. Store result in idempotent intake store
        response_data = {
            "status": "PROCESSED",
            "event_id": event.event_id,
            "edge": event.edge.edge_key,
            "outcome": proposal.outcome.value,
            "expiry_minutes": proposal.expiry_minutes,
            "ticket_id": ticket_id,
            "justification": proposal.justification,
            "map_version": current_map_version,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.intake_store.record_result(event.event_id, response_data)

        return response_data
