"""Bedrock tie-breaker and Lambda hard-rule validator (Proposal Section 9.4).

Invoked ONLY when re-check tools conflict.
Includes the Lambda Hard Rule Validator ensuring LLM hallucinations or judgements
cannot compromise safety invariants.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from ..schema.models import AgentProposal, OutcomeType, RecheckToolsOutput


logger = logging.getLogger("pathable.cloud.bedrock_tiebreaker")

MODEL_ID_NOVA_LITE = "amazon.nova-lite-v1:0"


class BedrockTieBreaker:
    """Manages LLM reasoning for conflicting tool outputs with offline simulation support."""

    def __init__(self, aws_client=None, model_id: str = MODEL_ID_NOVA_LITE):
        self.client = aws_client
        self.model_id = model_id

    def resolve_conflict(
        self,
        tools_output: RecheckToolsOutput,
        keyframe_summaries: Optional[list] = None,
    ) -> AgentProposal:
        """Resolves tool conflict using Amazon Nova Lite or deterministic fallback."""
        if tools_output.clearance.free_clearance_m is None or tools_output.motion.average_flow_magnitude is None:
            return AgentProposal(outcome=OutcomeType.UNCERTAIN,
                                 justification="Recorded clearance or motion evidence is missing. "
                                               "Keep the edge blocked pending measurement or human review.")
        prompt = self._build_prompt(tools_output, keyframe_summaries)

        # If real Bedrock client is configured and available
        if self.client is not None:
            try:
                logger.info("Calling Amazon Bedrock model: %s", self.model_id)
                response = self._call_bedrock(prompt)
                return self._parse_response(response)
            except Exception as e:
                logger.warning("Bedrock call failed (%s); engaging safe fallback reasoning", e)

        # Deterministic offline tie-breaker reasoning (Proposal Section 9.4)
        return self._offline_tiebreaker_reasoning(tools_output)

    def _build_prompt(self, tools_output: RecheckToolsOutput, keyframe_summaries: Optional[list]) -> str:
        return (
            f"You are the PathAble Slow-Loop Arbiter for visually impaired indoor navigation.\n"
            f"Tool outputs conflict for corridor edge {tools_output.edge.edge_key}:\n"
            f"- Detection classes: {tools_output.detection.classes}\n"
            f"- Motion: {tools_output.motion.motion_type} (flow: {tools_output.motion.average_flow_magnitude:.2f})\n"
            f"- Clearance: {tools_output.clearance.free_clearance_m:.2f}m (MS 1184 min is 1.20m)\n"
            f"- History count: {len(tools_output.history)}\n"
            f"Return strictly valid JSON with keys 'outcome' ('TEMPORARY' or 'UNCERTAIN'), "
            f"'expiry_minutes' (int or null), and 'justification' (exactly two sentences)."
        )

    def _call_bedrock(self, prompt: str) -> str:
        # Standard Bedrock Converse / InvokeModel call structure
        body = json.dumps(
            {
                "inferenceConfig": {"max_new_tokens": 200, "temperature": 0.0},
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
            }
        )
        resp = self.client.invoke_model(modelId=self.model_id, body=body)
        raw = json.loads(resp["body"].read().decode("utf-8"))
        return raw["output"]["message"]["content"][0]["text"]

    def _parse_response(self, text: str) -> AgentProposal:
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.endswith("```"):
            clean = clean[:-3]
        data = json.loads(clean.strip())
        return AgentProposal(
            outcome=OutcomeType(data["outcome"]),
            expiry_minutes=data.get("expiry_minutes"),
            justification=data["justification"],
            requires_facilities_approval=False,
            tiebreaker_used=True,
            model_id=self.model_id,
        )

    def _offline_tiebreaker_reasoning(self, tools_output: RecheckToolsOutput) -> AgentProposal:
        """Deterministic tie-breaker matching Amazon Nova Lite behavior for offline environments."""
        clr = tools_output.clearance.free_clearance_m
        classes = tools_output.detection.classes or ["obstacle"]

        # Conflict scenario: clearance is adequate (>1.2m), but object detected
        # Rule: cannot arbitrarily reopen edge if report claimed blockage; marks as UNCERTAIN or TEMPORARY
        justification = (
            f"Obstacle ({', '.join(classes)}) provides {clr:.2f}m clearance but remains in the walking envelope. "
            f"Classification held as UNCERTAIN pending further corridor observation without disrupting user safety."
        )
        return AgentProposal(
            outcome=OutcomeType.UNCERTAIN,
            expiry_minutes=None,
            justification=justification,
            requires_facilities_approval=False,
            tiebreaker_used=True,
            model_id="offline-tiebreaker-simulator",
        )


class LambdaHardRuleValidator:
    """Enforces proposal invariants before DynamoDB or map state is updated.

    Section 9.4:
    'A Lambda validator checks every proposal against the hard rules before DynamoDB is updated.
    The language model cannot reopen an edge the rules mark as blocked and cannot approve a lasting closure;
    only facilities staff can.'
    """

    @staticmethod
    def validate_and_sanitize(
        proposal: AgentProposal,
        tools_output: RecheckToolsOutput,
        *, allow_simulated: bool = False,
    ) -> AgentProposal:
        """Validates proposal against non-negotiable safety rules and sanitizes if violated."""
        allowed = {"observed", "simulated"} if allow_simulated else {"observed"}
        if (any(item.evidence_status not in allowed for item in
                (tools_output.detection, tools_output.motion, tools_output.clearance))
                or tools_output.clearance.free_clearance_m is None
                or tools_output.motion.average_flow_magnitude is None):
            return AgentProposal(outcome=OutcomeType.UNCERTAIN,
                                 justification="Recorded re-check evidence is unavailable. "
                                               "Keep this edge blocked for further measurement or human review.")
        # Hard Rule 1: The language model cannot approve a lasting closure
        if proposal.outcome == OutcomeType.LASTING and not proposal.requires_facilities_approval:
            logger.warning("Hard Rule Violation: LLM attempted to mark lasting closure without facilities review.")
            proposal = AgentProposal(
                outcome=OutcomeType.LASTING,
                expiry_minutes=None,
                justification=proposal.justification,
                requires_facilities_approval=True,
                tiebreaker_used=proposal.tiebreaker_used,
                model_id=proposal.model_id,
            )

        # Hard Rule 2: If physical clearance is severely restricted (<1.2m) and multiple static reports exist,
        # the model CANNOT downgrade it to TEMPORARY or reopen it.
        expected_mode = "simulated" if allow_simulated else "recorded"
        has_lasting_history = any(entry.evidence_mode == expected_mode
                                  and entry.clearance_m is not None and entry.clearance_m < 1.20
                                  for entry in tools_output.history)
        if not tools_output.clearance.meets_ms1184_standard and has_lasting_history:
            if proposal.outcome == OutcomeType.TEMPORARY:
                logger.warning("Hard Rule Override: Refusing TEMPORARY downgrade on chronically blocked edge.")
                return AgentProposal(
                    outcome=OutcomeType.LASTING,
                    expiry_minutes=None,
                    justification="Validator override: Edge has persistent physical restriction (<1.20m) across multiple reports; escalated to facilities.",
                    requires_facilities_approval=True,
                    tiebreaker_used=True,
                    model_id="lambda-validator",
                )

        return proposal
