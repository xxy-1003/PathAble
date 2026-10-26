"""Deterministic, offline navigation decisions for the bounded PathAble demo.

Perception supplies observations; this module never guesses from raw pixels.
The floor map is a small, measured graph and must be checked on site.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from heapq import heappop, heappush
from pathlib import Path
import json
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from voice import VoiceGuidance


Zone = Literal["clear", "occupied", "unknown"]
Distance = Literal["near", "medium", "far", "unknown"]


@dataclass(frozen=True)
class Observation:
    timestamp: float
    obstacle_class: str | None
    confidence: float
    left: Zone
    centre: Zone
    right: Zone
    distance: Distance
    moving: bool = False
    node: str | None = None


@dataclass(frozen=True)
class Decision:
    action: str
    message: str
    route: tuple[str, ...]
    blocked_edge: tuple[str, str] | None = None


class RouteMap:
    def __init__(self, data: dict):
        self.version = data.get("version", 1)
        self.nodes = set(data["nodes"].values())
        self.edges: dict[frozenset[str], float] = {}
        self.blocked: set[frozenset[str]] = set()
        for edge in data["edges"]:
            a, b, distance = edge["from"], edge["to"], edge["distance"]
            if a not in self.nodes or b not in self.nodes or a == b or distance <= 0:
                raise ValueError(f"Invalid map edge: {edge}")
            key = frozenset((a, b))
            if key in self.edges:
                raise ValueError(f"Duplicate map edge: {edge}")
            self.edges[key] = distance
            if edge.get("blocked", False):
                self.blocked.add(key)

    @classmethod
    def from_file(cls, path: str | Path) -> RouteMap:
        with open(path, encoding="utf-8") as file:
            return cls(json.load(file))

    def block(self, a: str, b: str) -> None:
        key = frozenset((a, b))
        if key not in self.edges:
            raise ValueError(f"Unknown edge: {a}-{b}")
        self.blocked.add(key)

    def route(self, start: str, destination: str) -> tuple[str, ...]:
        if start not in self.nodes or destination not in self.nodes:
            return ()
        queue = [(0.0, start, (start,))]
        best = {start: 0.0}
        while queue:
            cost, node, path = heappop(queue)
            if cost > best[node]:
                continue
            if node == destination:
                return path
            for edge, length in self.edges.items():
                if node not in edge or edge in self.blocked:
                    continue
                neighbor = next(iter(edge - {node}))
                new_cost = cost + length
                if new_cost < best.get(neighbor, float("inf")):
                    best[neighbor] = new_cost
                    heappush(queue, (new_cost, neighbor, path + (neighbor,)))
        return ()


class LocalAgent:
    """Applies Section 8 of proposal v3; unknown evidence leads to re-observation."""

    def __init__(
        self,
        route_map: RouteMap,
        start: str,
        destination: str,
        voice: VoiceGuidance | None = None,
    ):
        self.map = route_map
        self.current_node = start
        self.destination = destination
        self.voice = voice
        self.current_route = self.map.route(start, destination)
        self.history: deque[bool] = deque(maxlen=10)
        self.low_confidence_rechecks = 0
        self.last_frame_at: float | None = None
        self.last_marker_at: float | None = None
        self.awaiting_new_corridor = False
        self._last_decision_key = None

    def _decision(self, action: str, message: str = "", edge=None) -> Decision:
        decision = Decision(action, message, self.current_route, edge)
        key = (action, message, self.current_node, tuple(self.current_route), edge)
        is_stop = action == "STOP_AND_ESCALATE"
        repeated_stop = is_stop and key == self._last_decision_key
        # Keep returning STOP on every frame, but announce an unchanged stop once.
        # A new reason/location/route or leaving and re-entering STOP rearms speech.
        self._last_decision_key = key
        if self.voice and message and not repeated_stop:
            is_reroute = action == "REROUTE"
            is_urgent = is_stop or is_reroute
            self.voice.speak(
                message,
                force=is_urgent,
                priority=is_urgent,
                now=self.last_frame_at,
            )
        return decision

    def camera_timeout(self, now: float) -> Decision | None:
        if self.last_frame_at is None or now - self.last_frame_at > 1.0:
            decision = self._decision(
                "STOP_AND_ESCALATE", "Please stop and stay where you are. Camera unavailable."
            )
            return decision
        return None

    def create_cloud_event(
        self,
        event: Observation,
        decision: Decision,
        keyframes: list | None = None,
    ) -> dict:
        """Constructs an AWS slow-loop blocked-edge event JSON per proposal Section 7.1 and 9.1."""
        edge_pair = list(decision.blocked_edge) if decision.blocked_edge else []
        return {
            "event_id": f"e-{int(event.timestamp * 1000):04d}",
            "timestamp": event.timestamp,
            "edge": edge_pair,
            "current_node": self.current_node,
            "destination": self.destination,
            "route": list(decision.route),
            "obstacle_class": event.obstacle_class,
            "confidence": event.confidence,
            "distance": event.distance,
            "zones": {
                "left": event.left,
                "centre": event.centre,
                "right": event.right,
            },
            "action": decision.action,
            "message": decision.message,
            "keyframes": keyframes or [],
        }

    def observe(self, event: Observation) -> Decision:
        if not 0.0 <= event.confidence <= 1.0:
            raise ValueError("Confidence must be between 0 and 1")
        if self.last_frame_at is not None and event.timestamp < self.last_frame_at:
            raise ValueError("Observations must be ordered by timestamp")
        self.last_frame_at = event.timestamp

        if event.node is not None:
            if event.node not in self.map.nodes:
                return self._decision("STOP_AND_ESCALATE", "Please stop. Unknown junction marker.")
            self.last_marker_at = event.timestamp
            if event.node != self.current_node:
                self.current_node = event.node
                self.current_route = self.map.route(event.node, self.destination)
                self.history.clear()  # Evidence from the previous corridor cannot block the next.
                self.awaiting_new_corridor = False

        if not self.current_route:
            return self._decision("STOP_AND_ESCALATE", "Please stop. No verified route is available.")
        if self.current_node == self.destination:
            return self._decision("ARRIVED", "You have reached your destination.")

        if self.awaiting_new_corridor:
            if event.centre != "clear" or event.confidence < 0.60:
                return self._decision(
                    "WAIT_AND_REOBSERVE", "Please wait while I check the new corridor."
                )
            self.awaiting_new_corridor = False

        full_near = (
            event.centre == "occupied"
            and event.left == "occupied"
            and event.right == "occupied"
            and event.distance == "near"
            and event.confidence >= 0.60
        )
        self.history.append(full_near)

        # CONTINUE is normally silent: message is empty, no speech is emitted
        if event.centre == "clear" and event.confidence >= 0.60:
            self.low_confidence_rechecks = 0
            return self._decision("CONTINUE")

        if event.confidence < 0.60 or event.centre == "unknown" or (
            event.centre == "occupied" and event.distance == "unknown"
        ):
            self.low_confidence_rechecks += 1
            if self.low_confidence_rechecks >= 3:
                return self._decision(
                    "STOP_AND_ESCALATE", "Please stop and stay where you are. I cannot verify the path."
                )
            return self._decision("WAIT_AND_REOBSERVE", "Please wait while I check the path again.")
        self.low_confidence_rechecks = 0

        if event.moving and event.obstacle_class == "person":
            return self._decision("WAIT_AND_REOBSERVE", "Please wait for the person to pass.")

        if full_near:
            if sum(self.history) < 6:
                return self._decision("WAIT_AND_REOBSERVE", "Please wait while I check the blockage.")
            if self.last_marker_at is None or event.timestamp - self.last_marker_at > 10.0:
                return self._decision(
                    "STOP_AND_ESCALATE", "Please stop. I cannot verify your junction for a safe reroute."
                )
            if len(self.current_route) < 2:
                return self._decision("STOP_AND_ESCALATE", "Please stop. No verified route is available.")
            edge = (self.current_node, self.current_route[1])
            self.map.block(*edge)
            self.current_route = self.map.route(self.current_node, self.destination)
            self.history.clear()
            if not self.current_route:
                return self._decision("STOP_AND_ESCALATE", "Please stop. No alternative route is available.", edge)
            self.awaiting_new_corridor = True
            return self._decision(
                "REROUTE", f"Route blocked. Take the corridor towards {self.current_route[1]}.", edge
            )

        if event.centre == "occupied" and event.distance in ("near", "medium"):
            if event.left == "unknown" and event.right != "clear":
                return self._decision("TURN_TO_LOOK", "Turn slightly left so I can check that side.")
            if event.right == "unknown" and event.left != "clear":
                return self._decision("TURN_TO_LOOK", "Turn slightly right so I can check that side.")
            if event.right == "clear":
                return self._decision("STEP_ASIDE", "Obstacle ahead. Step slightly right.")
            if event.left == "clear":
                return self._decision("STEP_ASIDE", "Obstacle ahead. Step slightly left.")
            return self._decision("WAIT_AND_REOBSERVE", "Please wait while I check the path.")

        return self._decision("CONTINUE")
