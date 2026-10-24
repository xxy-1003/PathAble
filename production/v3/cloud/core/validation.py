"""Event validation module for PathAble cloud intake.

Enforces schema conformity, privacy guarantees, valid map graph nodes/edges,
and data integrity before any processing or state updates occur.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from ..schema.models import BlockedEdgeEventV1


VALID_NODES = {"A", "B", "C", "D", "E", "F"}
VALID_EDGES = {
    frozenset(("A", "B")),
    frozenset(("B", "C")),
    frozenset(("C", "D")),
    frozenset(("B", "E")),
    frozenset(("E", "F")),
    frozenset(("F", "D")),
}


class EventValidationError(Exception):
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        self.message = message
        self.errors = errors or [message]
        super().__init__(f"{message}: {'; '.join(self.errors)}")


def validate_event_dict(payload: Dict[str, Any]) -> BlockedEdgeEventV1:
    """Validates a raw dictionary payload against BlockedEdgeEventV1 and domain rules."""
    try:
        event = BlockedEdgeEventV1.model_validate(payload)
    except ValidationError as e:
        error_msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        raise EventValidationError("Event payload failed schema validation", error_msgs) from e

    # Domain rule: nodes must exist in the 6-node prototype map
    if event.edge.from_node not in VALID_NODES:
        raise EventValidationError(f"Invalid edge from_node: {event.edge.from_node}")
    if event.edge.to_node not in VALID_NODES:
        raise EventValidationError(f"Invalid edge to_node: {event.edge.to_node}")
    if event.current_node not in VALID_NODES:
        raise EventValidationError(f"Invalid current_node: {event.current_node}")
    if event.destination_node not in VALID_NODES:
        raise EventValidationError(f"Invalid destination_node: {event.destination_node}")

    # Domain rule: edge must exist in the physical corridor graph
    edge_set = frozenset((event.edge.from_node, event.edge.to_node))
    if edge_set not in VALID_EDGES:
        raise EventValidationError(
            f"Edge {event.edge.from_node}-{event.edge.to_node} does not exist in prototype map"
        )

    # Privacy verification: Section 9.1 & 13
    if not event.privacy.people_blurred_on_device:
        raise EventValidationError(
            "Privacy rejection: unblurred person frame upload prohibited by ethics policy"
        )
    if event.privacy.face_recognition_used:
        raise EventValidationError(
            "Ethics rejection: face recognition is strictly prohibited in PathAble"
        )

    # Keyframes privacy check
    for kf in event.keyframes:
        if not kf.people_blurred:
            raise EventValidationError(
                f"Privacy rejection: keyframe {kf.frame_id} flagged as not blurred"
            )

    return event


def validate_event_json(json_str: str) -> BlockedEdgeEventV1:
    """Parses JSON string and validates."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise EventValidationError(f"Malformed JSON: {e}") from e
    return validate_event_dict(data)


def validate_event_file(path: str | Path) -> BlockedEdgeEventV1:
    """Reads file and validates."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_event_dict(data)
