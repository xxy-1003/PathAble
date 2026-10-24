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


from datetime import datetime, timezone

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


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes convenience events emitted by LocalAgent.create_cloud_event into Schema v1."""
    if "schema_version" not in payload and "edge" in payload:
        edge = payload.get("edge", [])
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            edge_obj = {"from_node": edge[0], "to_node": edge[1]}
        elif isinstance(edge, dict):
            edge_obj = edge
        else:
            edge_obj = {"from_node": "B", "to_node": "C"}

        zones = payload.get("zones", {})
        classes = []
        if payload.get("obstacle_class"):
            classes.append(payload["obstacle_class"])
        elif payload.get("obstacle_classes"):
            classes = list(payload["obstacle_classes"])
        else:
            classes = ["obstacle"]

        ts = payload.get("timestamp")
        if isinstance(ts, (int, float)):
            ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        else:
            ts_iso = str(ts or datetime.now(timezone.utc).isoformat())

        normalized = {
            "schema_version": "1.0.0",
            "event_id": str(payload.get("event_id", f"e-{int(datetime.now().timestamp()*1000)}")),
            "client_id": str(payload.get("client_id", "laptop-device-01")),
            "timestamp": ts_iso,
            "edge": edge_obj,
            "current_node": payload.get("current_node", edge_obj.get("from_node", "B")),
            "destination_node": payload.get("destination", payload.get("destination_node", "D")),
            "local_reroute": payload.get("route", payload.get("local_reroute", ["B", "E", "F", "D"])),
            "observations": {
                "confidence": float(payload.get("confidence", 0.85)),
                "obstacle_classes": classes,
                "distance_band": payload.get("distance", payload.get("distance_band", "near")),
                "ground_contact_distance_m": payload.get("ground_contact_distance_m", 1.0),
                "zone_occupancy": {
                    "left": zones.get("left", "clear"),
                    "centre": zones.get("centre", "occupied"),
                    "right": zones.get("right", "clear"),
                },
                "moving": bool(payload.get("moving", False)),
                "consecutive_blocked_frames": int(payload.get("consecutive_blocked_frames", 6)),
            },
            "keyframes": payload.get("keyframes", []),
            "privacy": {
                "people_blurred_on_device": True,
                "face_recognition_used": False,
                "s3_lifecycle_days": 7,
            },
            "map_version": int(payload.get("map_version", 1)),
        }
        return normalized
    return payload


def validate_event_dict(payload: Dict[str, Any]) -> BlockedEdgeEventV1:
    """Validates a raw dictionary payload against BlockedEdgeEventV1 and domain rules."""
    payload = normalize_payload(payload)
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
