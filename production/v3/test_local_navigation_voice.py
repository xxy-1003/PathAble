"""Unit tests for Person 1: Local navigation decisions, voice layer, and prioritization.

Validates:
- All 6 decision actions: CONTINUE, STEP_ASIDE, WAIT_AND_REOBSERVE, TURN_TO_LOOK, REROUTE, STOP_AND_ESCALATE (+ ARRIVED)
- Priority handling: STOP_AND_ESCALATE preempts pending speech
- CONTINUE is normally silent
- Offline voice debouncing and latency budget (<= 300 ms)
- Camera timeout escalation
- Cloud event generation format for AWS slow loop
"""

from pathlib import Path
import unittest

from local_agent import LocalAgent, Observation, RouteMap
from voice import VoiceGuidance


MAP_PATH = Path(__file__).resolve().parents[1] / "map_graph.json"


def obs(
    t: float,
    *,
    centre="clear",
    left="clear",
    right="clear",
    distance="far",
    confidence=0.9,
    obstacle_class=None,
    moving=False,
    node=None,
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


class LocalNavigationVoiceTests(unittest.TestCase):
    def setUp(self):
        self.voice = VoiceGuidance(mode="mock", cooldown_s=1.0)
        self.route_map = RouteMap.from_file(MAP_PATH)
        self.agent = LocalAgent(self.route_map, "A", "D", voice=self.voice)

    def tearDown(self):
        self.voice.close()

    def test_continue_is_normally_silent(self):
        """CONTINUE must produce no spoken voice warning."""
        decision = self.agent.observe(obs(0.0, centre="clear", confidence=0.95))
        self.assertEqual(decision.action, "CONTINUE")
        self.assertEqual(decision.message, "")
        self.assertEqual(len(self.voice.get_history()), 0)

    def test_step_aside_speaks_clear_direction(self):
        """STEP_ASIDE must direct the user toward the clear side."""
        decision = self.agent.observe(
            obs(0.0, centre="occupied", left="occupied", right="clear", distance="near")
        )
        self.assertEqual(decision.action, "STEP_ASIDE")
        self.assertIn("right", decision.message)
        self.assertEqual(self.voice.get_last_spoken(), decision.message)

    def test_turn_to_look_speaks_when_side_unknown(self):
        """TURN_TO_LOOK must ask the user to turn toward the unknown side."""
        decision = self.agent.observe(
            obs(0.0, centre="occupied", left="unknown", right="occupied", distance="medium")
        )
        self.assertEqual(decision.action, "TURN_TO_LOOK")
        self.assertIn("left", decision.message)
        self.assertEqual(self.voice.get_last_spoken(), decision.message)

    def test_moving_person_waits_with_spoken_warning(self):
        """A moving person triggers WAIT_AND_REOBSERVE with spoken prompt."""
        decision = self.agent.observe(
            obs(0.0, centre="occupied", obstacle_class="person", moving=True, distance="near")
        )
        self.assertEqual(decision.action, "WAIT_AND_REOBSERVE")
        self.assertIn("person", decision.message)
        self.assertEqual(self.voice.get_last_spoken(), decision.message)

    def test_stop_takes_priority_and_preempts(self):
        """STOP_AND_ESCALATE must speak immediately with priority override."""
        # Non-urgent speech
        self.agent.observe(obs(0.0, centre="occupied", left="clear", distance="near"))
        # Force a stop escalation
        timeout_dec = self.agent.camera_timeout(now=2.0)
        self.assertIsNotNone(timeout_dec)
        self.assertEqual(timeout_dec.action, "STOP_AND_ESCALATE")
        self.assertEqual(self.voice.get_last_spoken(), timeout_dec.message)

    def test_full_blockage_reroutes_and_speaks_warning(self):
        """6 consecutive blockage frames trigger REROUTE and vocal prompt."""
        self.agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            dec = self.agent.observe(
                obs(0.1 * (i + 1), centre="occupied", left="occupied", right="occupied", distance="near")
            )
        self.assertEqual(dec.action, "REROUTE")
        self.assertIn("Route blocked", dec.message)
        self.assertIn("towards E", dec.message)
        self.assertEqual(self.agent.current_route, ("B", "E", "F", "D"))
        self.assertEqual(self.voice.get_last_spoken(), dec.message)

    def test_unchanged_stop_is_announced_once_across_many_frames(self):
        self.agent.observe(obs(-0.2, centre="unknown", distance="unknown"))
        self.agent.observe(obs(-0.1, centre="unknown", distance="unknown"))
        self.voice.clear_history()
        for t in (0.0, 0.1, 2.0, 10.0, 60.0):
            decision = self.agent.observe(obs(t, centre="unknown", distance="unknown"))
            self.assertEqual(decision.action, "STOP_AND_ESCALATE")
        self.assertEqual(len(self.voice.get_history()), 1)

    def test_stop_is_announced_again_after_recovery(self):
        self.agent.observe(obs(-0.2, centre="unknown", distance="unknown"))
        self.agent.observe(obs(-0.1, centre="unknown", distance="unknown"))
        first = self.agent.observe(obs(0.0, centre="unknown", distance="unknown"))
        self.assertEqual(first.action, "STOP_AND_ESCALATE")
        recovered = self.agent.observe(obs(0.1))
        self.assertEqual(recovered.action, "CONTINUE")
        self.agent.observe(obs(0.2, centre="unknown", distance="unknown"))
        self.agent.observe(obs(0.3, centre="unknown", distance="unknown"))
        count_before = len(self.voice.get_history())
        again = self.agent.observe(obs(0.4, centre="unknown", distance="unknown"))
        self.assertEqual(again.message, first.message)
        self.assertEqual(len(self.voice.get_history()), count_before + 1)

    def test_new_stop_reason_is_announced_immediately(self):
        self.agent.observe(obs(-0.2, centre="unknown", distance="unknown"))
        self.agent.observe(obs(-0.1, centre="unknown", distance="unknown"))
        self.voice.clear_history()
        self.agent.observe(obs(0.0, centre="unknown", distance="unknown"))
        timeout = self.agent.camera_timeout(2.0)
        self.assertIn("Camera unavailable", timeout.message)
        self.assertEqual(len(self.voice.get_history()), 2)
        self.agent.camera_timeout(2.1)
        self.assertEqual(len(self.voice.get_history()), 2)

    def test_destination_arrival_speaks_arrived(self):
        """Arriving at the destination node must announce arrival."""
        decision = self.agent.observe(obs(0.0, node="D"))
        self.assertEqual(decision.action, "ARRIVED")
        self.assertIn("reached your destination", decision.message)
        self.assertEqual(self.voice.get_last_spoken(), decision.message)

    def test_cloud_event_serialization(self):
        """REROUTE decision must produce a valid structured AWS event dictionary."""
        self.agent.observe(obs(0.0, node="B"))
        dec = None
        for i in range(6):
            o = obs(0.1 * (i + 1), centre="occupied", left="occupied", right="occupied", distance="near")
            dec = self.agent.observe(o)
        cloud_event = self.agent.create_cloud_event(o, dec, keyframes=["s3://bucket/frame1.jpg"])
        self.assertEqual(cloud_event["action"], "REROUTE")
        self.assertEqual(cloud_event["current_node"], "B")
        self.assertEqual(cloud_event["edge"], ["B", "C"])
        self.assertEqual(cloud_event["route"], ["B", "E", "F", "D"])
        self.assertEqual(cloud_event["keyframes"], ["s3://bucket/frame1.jpg"])

    def test_voice_latency_budget(self):
        """Speech dispatch latency must be well below the 300 ms target."""
        latencies = [
            self.voice.speak(f"Test utterance {i}", force=True)
            for i in range(10)
        ]
        p95_latency = sorted(latencies)[int(0.95 * len(latencies))]
        self.assertLess(p95_latency, 50.0)  # Worker dispatch typically < 5 ms


if __name__ == "__main__":
    unittest.main()
