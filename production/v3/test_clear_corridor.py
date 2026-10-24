"""Unit tests demonstrating how corridors are established as clear in PathAble v3."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from calibrated_observation import FloorProjector, PerceptionPipeline, observation_from_vision
from calibrate_logitech_c920 import generate_c920_calibration
from local_agent import LocalAgent, Observation, RouteMap
from vision import Obstacle, VisionResult


class ClearCorridorEstablishmentTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)

        # Generate verified C920 calibration
        self.camera_path, self.floor_path = generate_c920_calibration(Path(self.temp.name))
        self.projector = FloorProjector(self.camera_path, self.floor_path)

        # 6-node prototype map
        map_data = {
            "version": 1,
            "nodes": {"0": "A", "1": "B", "2": "C", "3": "D", "4": "E", "5": "F"},
            "edges": [
                {"from": "A", "to": "B", "distance": 12.0},
                {"from": "B", "to": "C", "distance": 15.0},
                {"from": "C", "to": "D", "distance": 12.0},
                {"from": "B", "to": "E", "distance": 10.0},
                {"from": "E", "to": "F", "distance": 24.0},
                {"from": "F", "to": "D", "distance": 10.0},
            ],
        }
        self.route_map = RouteMap(map_data)
        self.agent = LocalAgent(self.route_map, "A", "D")

    def test_logitech_c920_calibration_is_ready_and_valid(self):
        """Verify that Logitech C920 calibration passes all cryptographic and geometric checks."""
        self.assertTrue(self.projector.ready)
        self.assertEqual(self.projector.image_size, (640, 480))
        # Point inside lower 60% floor region returns finite distance in metres
        dist = self.projector.distance_metres((320, 360), (640, 480), same_pose_verified=True)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 0.2)

    def test_unobstructed_corridor_establishes_clear_and_triggers_continue(self):
        """When no obstacles occupy the center walking path, corridor is established as clear."""
        # Unobstructed vision result (0% coverage across all zones)
        clear_vision = VisionResult(obstacles=(), coverage=(0.0, 0.0, 0.0), inference_ms=45.0)

        # In live navigation mode (allow_clear=True)
        obs = observation_from_vision(
            clear_vision,
            timestamp=1.0,
            frame_size=(640, 480),
            projector=self.projector,
            same_pose_verified=True,
            node="A",
            allow_clear=True,
        )

        self.assertEqual(obs.centre, "clear")
        self.assertEqual(obs.left, "clear")
        self.assertEqual(obs.right, "clear")
        self.assertEqual(obs.distance, "far")
        self.assertGreaterEqual(obs.confidence, 0.60)
        self.assertEqual(obs.node, "A")

        # Pass to LocalAgent -> must return CONTINUE
        decision = self.agent.observe(obs)
        self.assertEqual(decision.action, "CONTINUE")
        self.assertEqual(self.agent.low_confidence_rechecks, 0)

    def test_rerouted_corridor_establishes_clear_after_blockage(self):
        """After a reroute, the agent waits until the new corridor is confirmed clear."""
        # Arrive at Node B
        self.agent.observe(Observation(1.0, None, 1.0, "clear", "clear", "clear", "far", node="B"))
        self.assertEqual(self.agent.current_node, "B")

        # Encounter full blockage on B-C for 6 consecutive frames
        for i in range(6):
            t = 2.0 + i * 0.1
            blocked_obs = Observation(
                t, "chair", 0.90, "occupied", "occupied", "occupied", "near"
            )
            decision = self.agent.observe(blocked_obs)

        # 6th frame must trigger REROUTE
        self.assertEqual(decision.action, "REROUTE")
        self.assertEqual(self.agent.current_route, ("B", "E", "F", "D"))
        self.assertTrue(self.agent.awaiting_new_corridor)

        # While user is still facing blockage, agent says WAIT_AND_REOBSERVE
        still_blocked = Observation(3.0, "chair", 0.90, "occupied", "occupied", "occupied", "near")
        decision2 = self.agent.observe(still_blocked)
        self.assertEqual(decision2.action, "WAIT_AND_REOBSERVE")
        self.assertIn("check the new corridor", decision2.message.lower())

        # When camera turns towards corridor E and establishes it as CLEAR:
        new_corridor_clear = Observation(3.5, None, 1.0, "clear", "clear", "clear", "far")
        decision3 = self.agent.observe(new_corridor_clear)

        # Agent verifies new corridor is clear and proceeds with CONTINUE
        self.assertEqual(decision3.action, "CONTINUE")
        self.assertFalse(self.agent.awaiting_new_corridor)


if __name__ == "__main__":
    unittest.main()
