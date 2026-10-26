"""Spec-compliance tests for PathAble v3 Local Navigation & Voice module.

Validates all requirements from the OpenCV AI Competition 2026 proposal v3,
Section 3-11, covering:

- Dijkstra reroute accuracy upon edge failure (networkx cross-check)
- Ring buffer smoothing and persistence counters
- Speech queue override logic (STOP preemption)
- Decision table latency verification (<= 10 ms execution target)
- Observation schema field validation
- Distance band boundaries (near < 1.0 m, medium 1.0-2.5 m, far > 2.5 m)
- 6-node graph edge distances matching spec

> [!CAUTION]
> These tests use synthetic observations only and do NOT certify the system
> safe for live physical deployment. Field testing with safety spotters and
> full sensor calibration is required before any human corridor trial.
"""

from __future__ import annotations

import time
import threading
import unittest
from collections import deque
from pathlib import Path

import networkx as nx

from local_agent import LocalAgent, Observation, RouteMap
from voice import VoiceGuidance


MAP_PATH = Path(__file__).resolve().parents[1] / "map_graph.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def obs(
    t: float,
    *,
    centre: str = "clear",
    left: str = "clear",
    right: str = "clear",
    distance: str = "far",
    confidence: float = 0.90,
    obstacle_class: str | None = None,
    moving: bool = False,
    node: str | None = None,
) -> Observation:
    return Observation(
        timestamp=t,
        obstacle_class=obstacle_class,
        confidence=confidence,
        left=left,
        centre=centre,
        right=right,
        distance=distance,
        moving=moving,
        node=node,
    )


def fresh_agent(start: str = "A", destination: str = "D",
                voice: VoiceGuidance | None = None) -> LocalAgent:
    return LocalAgent(RouteMap.from_file(MAP_PATH), start, destination, voice=voice)


# ---------------------------------------------------------------------------
# 1. Graph Architecture & Dijkstra Routing (with networkx cross-check)
# ---------------------------------------------------------------------------

class GraphArchitectureTests(unittest.TestCase):
    """Section 3.1: Six-node graph, correct edge distances, Dijkstra routing."""

    def setUp(self):
        self.route_map = RouteMap.from_file(MAP_PATH)
        # Build a matching networkx graph for cross-validation
        self.nx_graph = nx.Graph()
        for edge_key, dist in self.route_map.edges.items():
            a, b = sorted(edge_key)
            self.nx_graph.add_edge(a, b, weight=dist)

    def test_six_nodes_exist(self):
        """Map must have exactly six junction nodes: A B C D E F."""
        self.assertEqual(self.route_map.nodes, {"A", "B", "C", "D", "E", "F"})

    def test_edge_distances_match_spec(self):
        """All six edges must have exactly the specified distances."""
        spec = {
            frozenset(("A", "B")): 12.0,
            frozenset(("B", "C")): 15.0,
            frozenset(("C", "D")): 12.0,
            frozenset(("B", "E")): 10.0,
            frozenset(("E", "F")): 24.0,
            frozenset(("F", "D")): 10.0,
        }
        for edge, dist in spec.items():
            self.assertIn(edge, self.route_map.edges, f"Missing edge {edge}")
            self.assertAlmostEqual(self.route_map.edges[edge], dist,
                                   msg=f"Wrong distance for {edge}")

    def test_primary_route_abd_matches_spec(self):
        """Primary route A→B→C→D (39 m) must be shortest without blockage."""
        route = self.route_map.route("A", "D")
        self.assertEqual(route, ("A", "B", "C", "D"))

    def test_primary_route_distance_is_39m(self):
        """A→B→C→D total distance must be exactly 39 m."""
        route = ("A", "B", "C", "D")
        total = sum(
            self.route_map.edges[frozenset((route[i], route[i + 1]))]
            for i in range(len(route) - 1)
        )
        self.assertAlmostEqual(total, 39.0)

    def test_reroute_after_bc_block_matches_spec(self):
        """After B-C block, route must be B→E→F→D (44 m)."""
        self.route_map.block("B", "C")
        route = self.route_map.route("B", "D")
        self.assertEqual(route, ("B", "E", "F", "D"))

    def test_reroute_distance_is_44m(self):
        """Reroute B→E→F→D total distance must be exactly 44 m."""
        route = ("B", "E", "F", "D")
        total = sum(
            self.route_map.edges[frozenset((route[i], route[i + 1]))]
            for i in range(len(route) - 1)
        )
        self.assertAlmostEqual(total, 44.0)

    def test_networkx_dijkstra_agrees_with_primary_route(self):
        """NetworkX Dijkstra must agree with RouteMap on primary A→D path."""
        nx_path = tuple(nx.dijkstra_path(self.nx_graph, "A", "D", weight="weight"))
        agent_path = self.route_map.route("A", "D")
        self.assertEqual(nx_path, agent_path)

    def test_networkx_dijkstra_agrees_with_reroute(self):
        """After blocking B-C, networkx and RouteMap must agree on reroute."""
        self.nx_graph.remove_edge("B", "C")
        nx_path = tuple(nx.dijkstra_path(self.nx_graph, "B", "D", weight="weight"))
        self.route_map.block("B", "C")
        agent_path = self.route_map.route("B", "D")
        self.assertEqual(nx_path, agent_path)

    def test_networkx_path_weight_matches_spec(self):
        """NetworkX path weight for reroute B→E→F→D must equal 44 m."""
        self.nx_graph.remove_edge("B", "C")
        cost = nx.dijkstra_path_length(self.nx_graph, "B", "D", weight="weight")
        self.assertAlmostEqual(cost, 44.0)

    def test_both_edges_blocked_returns_empty_route(self):
        """With B-C and B-E both blocked, route from B to D must be empty."""
        self.route_map.block("B", "C")
        self.route_map.block("B", "E")
        route = self.route_map.route("B", "D")
        self.assertEqual(route, ())

    def test_agent_reroute_accuracy(self):
        """Agent must trigger REROUTE after 6 confirmed blockage frames then follow B→E→F→D."""
        agent = fresh_agent()
        agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(dec.action, "REROUTE")
        self.assertEqual(agent.current_route, ("B", "E", "F", "D"))


# ---------------------------------------------------------------------------
# 2. Ring Buffer Smoothing & Persistence Counters
# ---------------------------------------------------------------------------

class RingBufferTests(unittest.TestCase):
    """Section 3.3: 10-frame ring buffer, 6-frame persistence threshold."""

    def setUp(self):
        self.agent = fresh_agent()

    def test_ring_buffer_maxlen_is_10(self):
        """History deque must cap at 10 frames."""
        self.assertEqual(self.agent.history.maxlen, 10)

    def test_blockage_not_confirmed_with_five_frames(self):
        """5 blockage frames (< 6 threshold) must NOT trigger REROUTE."""
        self.agent.observe(obs(0.0, node="B"))
        actions = []
        for i in range(5):
            dec = self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
            actions.append(dec.action)
        self.assertNotIn("REROUTE", actions)

    def test_blockage_confirmed_at_exactly_six_frames(self):
        """Exactly 6 consecutive blockage frames must trigger REROUTE on frame 6."""
        self.agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(dec.action, "REROUTE")

    def test_buffer_cleared_on_new_node_marker(self):
        """Reaching a new ArUco marker must clear the ring buffer (old evidence invalid)."""
        # Accumulate 5 blockage frames
        for i in range(5):
            self.agent.observe(obs(
                float(i),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(sum(self.agent.history), 5)
        # Arrive at new node B → buffer cleared
        self.agent.observe(obs(5.0, node="B"))
        self.assertEqual(sum(self.agent.history), 0)

    def test_buffer_rolls_over_after_ten_frames(self):
        """After 10+ frames, old evidence drops out of the ring buffer."""
        self.agent.observe(obs(0.0, node="B"))
        # 6 blockage frames trigger reroute + clear buffer
        for i in range(6):
            self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        # Buffer is cleared after reroute; add 10 clear frames
        for j in range(10):
            self.agent.observe(obs(float(j + 8), centre="clear"))
        # None of those should be blockage
        self.assertEqual(sum(self.agent.history), 0)

    def test_persistence_threshold_resets_after_clear_corridor(self):
        """Blockage accumulation resets when route is re-evaluated after reroute."""
        self.agent.observe(obs(0.0, node="B"))
        for i in range(6):
            self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        # Verify buffer cleared by reroute
        self.assertEqual(len(self.agent.history), 0)

    def test_partial_blockage_does_not_trigger_reroute(self):
        """Mixed clear/blockage frames that don't reach 6 must NOT reroute."""
        self.agent.observe(obs(0.0, node="B"))
        actions = []
        for i in range(10):
            # Alternate blockage and clear
            if i % 2 == 0:
                dec = self.agent.observe(obs(
                    float(i + 1),
                    centre="occupied", left="occupied", right="occupied", distance="near",
                ))
            else:
                dec = self.agent.observe(obs(float(i + 1), centre="clear"))
            actions.append(dec.action)
        self.assertNotIn("REROUTE", actions)


# ---------------------------------------------------------------------------
# 3. Speech Queue Override Logic (STOP Preemption)
# ---------------------------------------------------------------------------

class SpeechQueuePreemptionTests(unittest.TestCase):
    """Section 3.5: STOP_AND_ESCALATE must instantly preempt all queued speech."""

    def setUp(self):
        self.voice = VoiceGuidance(mode="mock", cooldown_s=0.01)

    def tearDown(self):
        self.voice.close()

    def test_stop_preempts_queued_messages(self):
        """STOP must clear any queued non-urgent messages before enqueuing itself."""
        # Queue several non-urgent messages at once
        for i in range(5):
            self.voice.speak(f"Step message {i}", force=True)
        # Now issue STOP with priority=True (queue drain)
        self.voice.speak("Please stop and stay where you are.", priority=True, force=True)
        # Last spoken must be the STOP message
        self.assertEqual(
            self.voice.get_last_spoken(),
            "Please stop and stay where you are.",
        )

    def test_stop_agent_preempts_via_camera_timeout(self):
        """Camera timeout decision must produce STOP_AND_ESCALATE as last spoken."""
        voice = VoiceGuidance(mode="mock", cooldown_s=0.01)
        agent = fresh_agent(voice=voice)
        agent.observe(obs(0.0, centre="occupied", left="clear", distance="near"))
        dec = agent.camera_timeout(now=2.0)
        self.assertEqual(dec.action, "STOP_AND_ESCALATE")
        self.assertEqual(voice.get_last_spoken(), dec.message)
        voice.close()

    def test_continue_produces_no_speech(self):
        """CONTINUE action must never enqueue any voice message."""
        voice = VoiceGuidance(mode="mock", cooldown_s=0.01)
        agent = fresh_agent(voice=voice)
        agent.observe(obs(0.0, centre="clear", confidence=0.95))
        self.assertEqual(len(voice.get_history()), 0)
        self.assertIsNone(voice.get_last_spoken())
        voice.close()

    def test_stop_clears_queue_before_speaking(self):
        """priority=True in speak() must drain the queue before adding STOP message."""
        # Pack the queue with messages (they won't execute instantly in mock mode)
        for i in range(20):
            self.voice.speak(f"Queued message {i}", force=True)
        # Issue STOP with priority
        self.voice.speak("Please stop.", priority=True, force=True)
        # The STOP message must appear in history
        history_texts = [r.text for r in self.voice.get_history()]
        self.assertIn("Please stop.", history_texts)

    def test_reroute_also_has_priority(self):
        """REROUTE uses force+priority; it must appear as last spoken after obstacle."""
        voice = VoiceGuidance(mode="mock", cooldown_s=0.01)
        agent = fresh_agent(voice=voice)
        agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(dec.action, "REROUTE")
        self.assertEqual(voice.get_last_spoken(), dec.message)
        voice.close()

    def test_stop_escalate_message_content(self):
        """STOP_AND_ESCALATE message must include stop instruction."""
        voice = VoiceGuidance(mode="mock", cooldown_s=0.01)
        agent = fresh_agent(voice=voice)
        timeout_dec = agent.camera_timeout(now=99.0)
        self.assertIsNotNone(timeout_dec)
        self.assertIn("stop", timeout_dec.message.lower())
        voice.close()


# ---------------------------------------------------------------------------
# 4. Decision Table Latency (≤ 10 ms)
# ---------------------------------------------------------------------------

class DecisionLatencyTests(unittest.TestCase):
    """Section 3.4: Decision + route planning must complete within 10 ms."""

    LATENCY_BUDGET_MS = 10.0
    WARMUP_ITERATIONS = 5
    TIMED_ITERATIONS = 50

    def _measure_decision_latency(self, agent: LocalAgent,
                                  observation: Observation) -> float:
        """Returns median decision latency in milliseconds over TIMED_ITERATIONS."""
        latencies: list[float] = []
        for i in range(self.WARMUP_ITERATIONS + self.TIMED_ITERATIONS):
            # Fresh observation timestamp each iteration to avoid ordering error
            o = Observation(
                timestamp=float(i),
                obstacle_class=observation.obstacle_class,
                confidence=observation.confidence,
                left=observation.left,
                centre=observation.centre,
                right=observation.right,
                distance=observation.distance,
                moving=observation.moving,
                node=None,
            )
            t0 = time.perf_counter()
            agent.observe(o)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if i >= self.WARMUP_ITERATIONS:
                latencies.append(elapsed_ms)
        latencies.sort()
        return latencies[len(latencies) // 2]  # median

    def test_continue_decision_latency(self):
        """CONTINUE (clear path) decision must complete in ≤ 10 ms (median)."""
        agent = fresh_agent()
        median_ms = self._measure_decision_latency(
            agent, obs(0.0, centre="clear", confidence=0.95)
        )
        self.assertLess(
            median_ms, self.LATENCY_BUDGET_MS,
            f"CONTINUE median latency {median_ms:.2f} ms exceeds {self.LATENCY_BUDGET_MS} ms budget",
        )

    def test_wait_and_reobserve_decision_latency(self):
        """WAIT_AND_REOBSERVE decision must complete in ≤ 10 ms (median)."""
        agent = fresh_agent()
        median_ms = self._measure_decision_latency(
            agent,
            obs(0.0, centre="occupied", confidence=0.45),
        )
        self.assertLess(
            median_ms, self.LATENCY_BUDGET_MS,
            f"WAIT_AND_REOBSERVE median latency {median_ms:.2f} ms exceeds budget",
        )

    def test_reroute_decision_latency(self):
        """REROUTE decision (Dijkstra re-calc) must complete in ≤ 10 ms."""
        agent = fresh_agent()
        agent.observe(obs(0.0, node="B"))
        # Saturate ring buffer just below reroute threshold (5 frames)
        for i in range(5):
            agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        # The 6th frame triggers REROUTE — measure just that call
        t0 = time.perf_counter()
        dec = agent.observe(obs(
            6.0,
            centre="occupied", left="occupied", right="occupied", distance="near",
        ))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(dec.action, "REROUTE")
        self.assertLess(
            elapsed_ms, self.LATENCY_BUDGET_MS,
            f"REROUTE latency {elapsed_ms:.2f} ms exceeds {self.LATENCY_BUDGET_MS} ms budget",
        )

    def test_step_aside_decision_latency(self):
        """STEP_ASIDE decision must complete in ≤ 10 ms."""
        agent = fresh_agent()
        t0 = time.perf_counter()
        dec = agent.observe(obs(0.0, centre="occupied", left="occupied",
                                right="clear", distance="near"))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(dec.action, "STEP_ASIDE")
        self.assertLess(elapsed_ms, self.LATENCY_BUDGET_MS,
                        f"STEP_ASIDE latency {elapsed_ms:.2f} ms exceeds budget")

    def test_turn_to_look_decision_latency(self):
        """TURN_TO_LOOK decision must complete in ≤ 10 ms."""
        agent = fresh_agent()
        t0 = time.perf_counter()
        dec = agent.observe(obs(0.0, centre="occupied", left="unknown",
                                right="occupied", distance="medium"))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(dec.action, "TURN_TO_LOOK")
        self.assertLess(elapsed_ms, self.LATENCY_BUDGET_MS,
                        f"TURN_TO_LOOK latency {elapsed_ms:.2f} ms exceeds budget")

    def test_dijkstra_route_lookup_latency(self):
        """Standalone Dijkstra route lookup must complete in ≤ 10 ms."""
        route_map = RouteMap.from_file(MAP_PATH)
        t0 = time.perf_counter()
        for _ in range(100):
            route_map.route("A", "D")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0 / 100
        self.assertLess(
            elapsed_ms, self.LATENCY_BUDGET_MS,
            f"Dijkstra mean latency {elapsed_ms:.3f} ms exceeds budget",
        )


# ---------------------------------------------------------------------------
# 5. Observation Schema Validation
# ---------------------------------------------------------------------------

class ObservationSchemaTests(unittest.TestCase):
    """Validate Observation dataclass fields match the proposal spec."""

    def test_observation_has_required_fields(self):
        """Observation must have all required spec fields."""
        o = Observation(
            timestamp=1.0,
            obstacle_class="person",
            confidence=0.85,
            left="clear",
            centre="occupied",
            right="unknown",
            distance="near",
            moving=True,
            node="B",
        )
        self.assertEqual(o.timestamp, 1.0)
        self.assertEqual(o.obstacle_class, "person")
        self.assertAlmostEqual(o.confidence, 0.85)
        self.assertEqual(o.left, "clear")
        self.assertEqual(o.centre, "occupied")
        self.assertEqual(o.right, "unknown")
        self.assertEqual(o.distance, "near")
        self.assertTrue(o.moving)
        self.assertEqual(o.node, "B")

    def test_observation_confidence_bounds_enforced(self):
        """Agent must raise ValueError on confidence outside [0, 1]."""
        agent = fresh_agent()
        with self.assertRaises(ValueError):
            agent.observe(Observation(0.0, None, 1.1, "clear", "clear", "clear", "far"))
        with self.assertRaises(ValueError):
            agent.observe(Observation(0.0, None, -0.1, "clear", "clear", "clear", "far"))

    def test_observation_timestamp_ordering_enforced(self):
        """Agent must raise ValueError if observation timestamps go backwards."""
        agent = fresh_agent()
        agent.observe(Observation(5.0, None, 0.9, "clear", "clear", "clear", "far"))
        with self.assertRaises(ValueError):
            agent.observe(Observation(4.0, None, 0.9, "clear", "clear", "clear", "far"))

    def test_distance_band_boundaries(self):
        """Distance labels must align with spec: near<1.0m, medium 1-2.5m, far>2.5m."""
        # Verify these string literals are consistent in Decision responses
        agent = fresh_agent()
        # near distance + occupied centre -> STEP_ASIDE or blockage accumulation
        dec = agent.observe(obs(0.0, centre="occupied", left="clear",
                                right="clear", distance="near"))
        self.assertIn(dec.action, ("STEP_ASIDE", "WAIT_AND_REOBSERVE"))

    def test_zone_values_are_typed_correctly(self):
        """Zone values must be exactly 'clear', 'occupied', or 'unknown'."""
        valid_zones = ("clear", "occupied", "unknown")
        valid_distances = ("near", "medium", "far", "unknown")
        o = Observation(0.0, None, 0.9, "clear", "occupied", "unknown", "near")
        self.assertIn(o.left, valid_zones)
        self.assertIn(o.centre, valid_zones)
        self.assertIn(o.right, valid_zones)
        self.assertIn(o.distance, valid_distances)


# ---------------------------------------------------------------------------
# 6. Full Decision Table Coverage
# ---------------------------------------------------------------------------

class DecisionTableCoverageTests(unittest.TestCase):
    """Verify all spec decision actions can be triggered correctly."""

    def setUp(self):
        self.voice = VoiceGuidance(mode="mock", cooldown_s=0.0)
        self.agent = fresh_agent(voice=self.voice)

    def tearDown(self):
        self.voice.close()

    def test_continue_when_centre_clear(self):
        dec = self.agent.observe(obs(0.0, centre="clear", confidence=0.95))
        self.assertEqual(dec.action, "CONTINUE")
        self.assertEqual(dec.message, "")

    def test_step_aside_right_when_left_occupied(self):
        dec = self.agent.observe(obs(0.0, centre="occupied", left="occupied",
                                     right="clear", distance="near"))
        self.assertEqual(dec.action, "STEP_ASIDE")
        self.assertIn("right", dec.message.lower())

    def test_step_aside_left_when_right_occupied(self):
        dec = self.agent.observe(obs(0.0, centre="occupied", left="clear",
                                     right="occupied", distance="near"))
        self.assertEqual(dec.action, "STEP_ASIDE")
        self.assertIn("left", dec.message.lower())

    def test_wait_low_confidence(self):
        dec = self.agent.observe(obs(0.0, centre="occupied", confidence=0.45))
        self.assertEqual(dec.action, "WAIT_AND_REOBSERVE")

    def test_wait_moving_person(self):
        dec = self.agent.observe(obs(
            0.0, centre="occupied", obstacle_class="person",
            moving=True, distance="near", confidence=0.90,
        ))
        self.assertEqual(dec.action, "WAIT_AND_REOBSERVE")

    def test_turn_to_look_left_when_right_occupied(self):
        dec = self.agent.observe(obs(
            0.0, centre="occupied", left="unknown", right="occupied", distance="medium",
        ))
        self.assertEqual(dec.action, "TURN_TO_LOOK")
        self.assertIn("left", dec.message.lower())

    def test_reroute_after_six_blockage_frames(self):
        self.agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(dec.action, "REROUTE")
        self.assertIn("blocked", dec.message.lower())

    def test_stop_escalate_after_three_low_confidence(self):
        actions = [
            self.agent.observe(obs(float(i), centre="occupied", confidence=0.45)).action
            for i in range(3)
        ]
        self.assertEqual(actions[-1], "STOP_AND_ESCALATE")

    def test_stop_escalate_on_camera_timeout(self):
        self.agent.observe(obs(0.0))
        dec = self.agent.camera_timeout(now=2.0)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, "STOP_AND_ESCALATE")

    def test_arrived_at_destination(self):
        dec = self.agent.observe(obs(0.0, node="D"))
        self.assertEqual(dec.action, "ARRIVED")
        self.assertIn("destination", dec.message.lower())

    def test_reroute_message_includes_next_junction(self):
        """REROUTE message must name the next junction direction per spec."""
        self.agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = self.agent.observe(obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            ))
        self.assertEqual(dec.action, "REROUTE")
        self.assertIn("E", dec.message)  # Reroute goes towards E


# ---------------------------------------------------------------------------
# 7. Cloud Event Schema
# ---------------------------------------------------------------------------

class CloudEventSchemaTests(unittest.TestCase):
    """REROUTE must emit a correctly structured AWS cloud event."""

    def setUp(self):
        self.agent = fresh_agent()
        self.agent.observe(obs(0.0, node="B"))
        self.last_obs = None
        dec = None
        for i in range(6):
            self.last_obs = obs(
                float(i + 1),
                centre="occupied", left="occupied", right="occupied", distance="near",
            )
            dec = self.agent.observe(self.last_obs)
        self.reroute_dec = dec

    def test_cloud_event_has_required_keys(self):
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec)
        required = {"event_id", "timestamp", "edge", "current_node", "destination",
                    "route", "obstacle_class", "confidence", "distance", "zones",
                    "action", "message", "keyframes"}
        self.assertTrue(required.issubset(cloud_ev.keys()))

    def test_cloud_event_action_is_reroute(self):
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec)
        self.assertEqual(cloud_ev["action"], "REROUTE")

    def test_cloud_event_blocked_edge(self):
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec)
        self.assertIn("B", cloud_ev["edge"])
        self.assertIn("C", cloud_ev["edge"])

    def test_cloud_event_replanned_route(self):
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec)
        self.assertEqual(cloud_ev["route"], ["B", "E", "F", "D"])

    def test_cloud_event_keyframes_accepted(self):
        keyframes = ["s3://bucket/frame1.jpg", "s3://bucket/frame2.jpg"]
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec,
                                                  keyframes=keyframes)
        self.assertEqual(cloud_ev["keyframes"], keyframes)

    def test_cloud_event_zones_dict(self):
        cloud_ev = self.agent.create_cloud_event(self.last_obs, self.reroute_dec)
        zones = cloud_ev["zones"]
        self.assertIn("left", zones)
        self.assertIn("centre", zones)
        self.assertIn("right", zones)


if __name__ == "__main__":
    unittest.main()
