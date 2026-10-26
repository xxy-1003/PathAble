"""Regression tests: camera model defaults and no detections are not evidence."""

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

        self.projector = FloorProjector(Path(self.temp.name) / "camera.json",
                                        Path(self.temp.name) / "floor.json")

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

    def test_camera_model_name_cannot_generate_verified_calibration(self):
        with self.assertRaisesRegex(ValueError, "cannot be generated"):
            generate_c920_calibration(Path(self.temp.name))
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertFalse(self.projector.ready)
        dist = self.projector.distance_metres((320, 360), (640, 480), same_pose_verified=True)
        self.assertIsNone(dist)

    def test_no_detection_does_not_authorize_continue_even_with_legacy_flag(self):
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

        self.assertEqual(obs.centre, "unknown")
        self.assertEqual(obs.left, "unknown")
        self.assertEqual(obs.right, "unknown")
        self.assertEqual(obs.distance, "unknown")
        self.assertEqual(obs.confidence, 0.0)
        self.assertEqual(obs.node, "A")

        decision = self.agent.observe(obs)
        self.assertNotEqual(decision.action, "CONTINUE")

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
