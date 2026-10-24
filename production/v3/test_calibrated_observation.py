import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HAS_OPENCV = importlib.util.find_spec("cv2") is not None
if HAS_OPENCV:
    import numpy as np
    from calibrated_observation import FloorProjector, PerceptionPipeline, observation_from_vision
    from local_agent import LocalAgent, RouteMap
    from vision import MarkerDetection, Obstacle, VisionResult


@unittest.skipUnless(HAS_OPENCV, "OpenCV vision extras are not installed")
class CalibratedObservationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.camera_path = Path(self.temp.name) / "camera.json"
        self.floor_path = Path(self.temp.name) / "floor.json"
        self.camera = {
            "verified_target_size": True,
            "calibration_target": "phone_screen",
            "mount_description": "Fixed tripod at marked station",
            "image_size_px": [640, 480],
            "samples": 20,
            "rms_reprojection_px": 0.5,
            "camera_matrix": [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
            "distortion_coefficients": [0, 0, 0, 0, 0],
        }
        self.floor = {
            "fixed_mount_verified": True,
            "floor_origin_and_axes": "Measured grid, x east, y north",
            "camera_floor_xy_m": [0.0, 0.0],
            "image_size_px": [640, 480],
            "fit_points": 6,
            "check_points": 2,
            "max_held_out_error_m": 0.05,
            "homography_undistorted_px_to_floor_m": [[0.01, 0, -3.2], [0, 0.01, -2.4], [0, 0, 1]],
            "fit_region_undistorted_px": [[0, 0], [639, 0], [639, 479], [0, 479]],
        }
        self.save()

    def save(self):
        self.camera_path.write_text(json.dumps(self.camera), encoding="utf-8")
        self.floor["camera_calibration_sha256"] = hashlib.sha256(self.camera_path.read_bytes()).hexdigest()
        self.floor_path.write_text(json.dumps(self.floor), encoding="utf-8")

    def projector(self):
        return FloorProjector(self.camera_path, self.floor_path)

    def test_requires_physical_flags_matching_camera_and_same_pose(self):
        projector = self.projector()
        self.assertTrue(projector.ready)
        self.assertEqual(projector.distance_band((370, 240), (640, 480)), "unknown")
        self.assertEqual(projector.distance_band((370, 240), (320, 240), same_pose_verified=True), "unknown")
        self.assertEqual(projector.distance_band((700, 240), (640, 480), same_pose_verified=True), "unknown")
        self.camera["verified_target_size"] = False
        self.save()
        self.assertFalse(self.projector().ready)
        self.camera["verified_target_size"] = True
        self.save()
        self.camera_path.write_text(self.camera_path.read_text() + " ", encoding="utf-8")
        self.assertFalse(self.projector().ready)

    def test_classification_and_uncertain_thresholds(self):
        projector = self.projector()
        band = lambda x: projector.distance_band((x, 240), (640, 480), same_pose_verified=True)
        self.assertEqual(band(370), "near")
        self.assertEqual(band(420), "unknown")
        self.assertEqual(band(470), "medium")
        self.assertEqual(band(570), "unknown")
        self.assertEqual(band(600), "far")
        self.floor["fit_region_undistorted_px"] = [[300, 200], [400, 200], [400, 300], [300, 300]]
        self.save()
        self.assertEqual(self.projector().distance_band(
            (470, 240), (640, 480), same_pose_verified=True), "unknown")

    def test_adapter_never_invents_clear_path(self):
        projector = self.projector()
        empty = observation_from_vision(VisionResult((), (0, 0, 0), 1.0),
                                        0.0, (640, 480), projector, same_pose_verified=True)
        self.assertEqual((empty.left, empty.centre, empty.right, empty.distance, empty.confidence),
                         ("unknown", "unknown", "unknown", "unknown", 0.0))
        obstacle = Obstacle("chair", 0.9, (400, 150, 500, 240), (470, 240), (0, 0.3, 0))
        result = VisionResult((obstacle,), (0, 0.3, 0), 1.0)
        event = observation_from_vision(result, 1.0, (640, 480), projector,
                                        same_pose_verified=True)
        self.assertEqual((event.centre, event.distance, event.obstacle_class),
                         ("occupied", "medium", "chair"))
        unknown = observation_from_vision(result, 1.0, (640, 480), projector)
        self.assertEqual(unknown.distance, "unknown")
        route = RouteMap({"nodes": {"A": "A", "B": "B"},
                          "edges": [{"from": "A", "to": "B", "distance": 1}]})
        agent = LocalAgent(route, "A", "B")
        self.assertEqual(agent.observe(unknown).action, "WAIT_AND_REOBSERVE")

    def test_node_and_moving_fields_propagate_conservatively(self):
        projector = self.projector()
        obstacle = Obstacle("person", 0.95, (200, 100, 440, 400), (320, 390), (0, 0.4, 0))
        result = VisionResult((obstacle,), (0, 0.4, 0), 1.0)

        # Pass node and moving flags
        obs = observation_from_vision(
            result, 2.0, (640, 480), projector,
            same_pose_verified=True, node="B", moving=True
        )
        self.assertEqual(obs.node, "B")
        self.assertTrue(obs.moving)
        self.assertEqual(obs.obstacle_class, "person")

        # When moving person is in centre, agent issues WAIT_AND_REOBSERVE
        route = RouteMap({"nodes": {"A": "A", "B": "B", "C": "C"},
                          "edges": [{"from": "A", "to": "B", "distance": 10},
                                    {"from": "B", "to": "C", "distance": 15}]})
        agent = LocalAgent(route, "A", "C")
        # Initialize at node B
        decision = agent.observe(obs)
        self.assertEqual(decision.action, "WAIT_AND_REOBSERVE")
        self.assertIn("person", decision.message.lower())

    def test_missing_calibration_fails_closed_to_unknown_distance(self):
        missing_cam = Path(self.temp.name) / "nonexistent_cam.json"
        missing_floor = Path(self.temp.name) / "nonexistent_floor.json"
        broken_projector = FloorProjector(missing_cam, missing_floor)
        self.assertFalse(broken_projector.ready)
        self.assertIsNone(broken_projector.distance_metres((320, 240), (640, 480), same_pose_verified=True))
        self.assertEqual(broken_projector.distance_band((320, 240), (640, 480), same_pose_verified=True), "unknown")

        obstacle = Obstacle("chair", 0.85, (200, 100, 440, 400), (320, 390), (0, 0.4, 0))
        result = VisionResult((obstacle,), (0, 0.4, 0), 1.0)
        obs = observation_from_vision(result, 1.0, (640, 480), broken_projector, same_pose_verified=True)
        self.assertEqual(obs.distance, "unknown")

    def test_perception_pipeline_synthetic_end_to_end(self):
        # Create a mock detector returning a chair in the centre zone
        class MockDetector:
            def detect(self, frame):
                obstacle = Obstacle("chair", 0.88, (200, 100, 440, 300), (470, 240), (0, 0.25, 0))
                return VisionResult((obstacle,), (0, 0.25, 0), 12.5)

        # Create a mock localizer returning marker node "B"
        class MockLocalizer:
            def detect(self, frame):
                return (MarkerDetection(marker_id=1, node="B", corners=((0, 0), (1, 0), (1, 1), (0, 1))),)

        projector = self.projector()
        pipeline = PerceptionPipeline(
            detector=MockDetector(),
            localizer=MockLocalizer(),
            projector=projector,
            same_pose_verified=True,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        obs = pipeline.process_frame(frame, timestamp=5.0)

        self.assertEqual(obs.timestamp, 5.0)
        self.assertEqual(obs.node, "B")
        self.assertEqual(obs.obstacle_class, "chair")
        self.assertAlmostEqual(obs.confidence, 0.88)
        self.assertEqual(obs.centre, "occupied")
        self.assertEqual(obs.distance, "medium")

    def test_perception_pipeline_fail_closed_on_none_frame(self):
        pipeline = PerceptionPipeline()
        obs = pipeline.process_frame(None, timestamp=10.0)
        self.assertEqual(obs.timestamp, 10.0)
        self.assertIsNone(obs.obstacle_class)
        self.assertEqual(obs.confidence, 0.0)
        self.assertEqual((obs.left, obs.centre, obs.right, obs.distance),
                         ("unknown", "unknown", "unknown", "unknown"))
        self.assertIsNone(obs.node)


if __name__ == "__main__":
    unittest.main()
