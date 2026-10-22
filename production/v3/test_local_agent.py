import unittest
from pathlib import Path

from local_agent import LocalAgent, Observation, RouteMap


MAP_PATH = Path(__file__).resolve().parents[1] / "map_graph.json"


def event(t, *, centre="clear", left="clear", right="clear", distance="far",
          confidence=0.9, obstacle_class=None, moving=False, node=None):
    return Observation(t, obstacle_class, confidence, left, centre, right, distance, moving, node)


class LocalAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = LocalAgent(RouteMap.from_file(MAP_PATH), "A", "D")

    def test_initial_shortest_route(self):
        self.assertEqual(self.agent.current_route, ("A", "B", "C", "D"))

    def test_partial_obstacle_steps_only_into_clear_side(self):
        result = self.agent.observe(event(0, centre="occupied", left="occupied", distance="near"))
        self.assertEqual(result.action, "STEP_ASIDE")
        self.assertIn("right", result.message)

    def test_unknown_side_requires_look(self):
        result = self.agent.observe(event(0, centre="occupied", left="occupied", right="unknown", distance="near"))
        self.assertEqual(result.action, "TURN_TO_LOOK")

    def test_moving_person_waits(self):
        result = self.agent.observe(event(0, centre="occupied", obstacle_class="person", moving=True, distance="near"))
        self.assertEqual(result.action, "WAIT_AND_REOBSERVE")

    def test_low_confidence_stops_after_two_rechecks(self):
        actions = [self.agent.observe(event(i, centre="occupied", confidence=0.45)).action for i in range(3)]
        self.assertEqual(actions, ["WAIT_AND_REOBSERVE", "WAIT_AND_REOBSERVE", "STOP_AND_ESCALATE"])

    def test_full_blockage_requires_six_recent_frames_then_reroutes(self):
        self.agent.observe(event(0, node="B"))
        results = [self.agent.observe(event(i + 1, centre="occupied", left="occupied", right="occupied", distance="near")).action for i in range(6)]
        self.assertEqual(results[:5], ["WAIT_AND_REOBSERVE"] * 5)
        self.assertEqual(results[5], "REROUTE")
        self.assertEqual(self.agent.current_route, ("B", "E", "F", "D"))
        self.assertEqual(self.agent.map.route("A", "D"), ("A", "B", "E", "F", "D"))

    def test_no_alternative_route_stops(self):
        self.agent.map.block("B", "E")
        self.agent.observe(event(0, node="B"))
        result = None
        for i in range(6):
            result = self.agent.observe(event(i + 1, centre="occupied", left="occupied", right="occupied", distance="near"))
        self.assertEqual(result.action, "STOP_AND_ESCALATE")

    def test_camera_timeout_stops(self):
        self.agent.observe(event(0))
        self.assertIsNone(self.agent.camera_timeout(0.5))
        self.assertEqual(self.agent.camera_timeout(1.01).action, "STOP_AND_ESCALATE")

    def test_old_corridor_evidence_cleared_at_new_marker(self):
        for i in range(5):
            self.agent.observe(event(i, centre="occupied", left="occupied", right="occupied", distance="near"))
        result = self.agent.observe(event(5, centre="occupied", left="occupied", right="occupied", distance="near", node="B"))
        self.assertEqual(result.action, "WAIT_AND_REOBSERVE")

    def test_repeat_marker_does_not_clear_blockage_evidence(self):
        results = [self.agent.observe(event(i, centre="occupied", left="occupied", right="occupied", distance="near", node="B")) for i in range(6)]
        self.assertEqual(results[-1].action, "REROUTE")

    def test_unverified_junction_cannot_reroute(self):
        results = [self.agent.observe(event(i, centre="occupied", left="occupied", right="occupied", distance="near")) for i in range(6)]
        self.assertEqual(results[-1].action, "STOP_AND_ESCALATE")

    def test_reroute_waits_for_new_corridor_to_be_verified(self):
        self.agent.observe(event(0, node="B"))
        for i in range(6):
            self.agent.observe(event(i + 1, centre="occupied", left="occupied", right="occupied", distance="near"))
        result = self.agent.observe(event(7, centre="occupied", left="occupied", right="occupied", distance="near"))
        self.assertEqual(result.action, "WAIT_AND_REOBSERVE")
        self.assertEqual(self.agent.current_route, ("B", "E", "F", "D"))
        self.assertEqual(self.agent.observe(event(8)).action, "CONTINUE")


if __name__ == "__main__":
    unittest.main()
