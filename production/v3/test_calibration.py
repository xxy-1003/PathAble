import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HAS_OPENCV = importlib.util.find_spec("cv2") is not None
if HAS_OPENCV:
    import cv2
    import numpy as np
    from calibrate_camera import board_object_points, main as calibrate_camera_main
    from calibrate_floor import fit_floor_homography
    from marker_id_probe import detect_ids, status_label
    from marker_pose_probe import inspect, marker_object_points


@unittest.skipUnless(HAS_OPENCV, "OpenCV vision extras are not installed")
class CalibrationTests(unittest.TestCase):
    def test_floor_fallback_keeps_physical_inlier_limit(self):
        pixels = np.array([[0,0],[10,0],[0,10],[10,10],[3,4],[7,6]], dtype=float)
        metres = pixels / 100
        matrix = np.diag([0.01,0.01,1.0])
        mask = np.ones((6,1), dtype=np.uint8)
        with patch("calibrate_floor.cv2.findHomography", side_effect=[(None,None),(matrix,mask)]) as fit:
            _, _, estimator = fit_floor_homography(pixels, metres)
        self.assertEqual(estimator, "RANSAC")
        self.assertEqual(fit.call_args_list[0].args[2:], (cv2.USAC_MAGSAC, 0.10))
        self.assertEqual(fit.call_args_list[1].args[2:], (cv2.RANSAC, 0.10))
        with patch("calibrate_floor.cv2.findHomography", side_effect=[(None,None),(np.eye(3),mask)]):
            with self.assertRaisesRegex(ValueError, "six inlier"):
                fit_floor_homography(pixels, metres)

    def test_multiple_views_accept_both_opencv_corner_shapes(self):
        """Exercise the second SPACE capture that previously raised AxisError."""
        root = Path(__file__).resolve().parent / ".test-tmp"
        root.mkdir(exist_ok=True)
        for shape in ((54, 2), (54, 1, 2)):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory(dir=root) as directory:
                output = Path(directory) / "camera.json"
                corners = np.mgrid[0:9, 0:6].T.reshape(-1, 2).astype(np.float32) * 10 + 50
                views = [(True, (corners + [20 * index, 0]).astype(np.float32).reshape(shape), (9, 6))
                         for index in range(10)]
                with (patch("sys.argv", ["calibrate_camera.py", "--camera", "1", "--samples", "10",
                                         "--target", "phone_screen", "--square-mm", "14.2",
                                         "--output", str(output)]),
                      patch("calibrate_camera.cv2.VideoCapture") as capture_factory,
                      patch("calibrate_camera.find_board", side_effect=views),
                      patch("calibrate_camera.cv2.drawChessboardCorners"),
                      patch("calibrate_camera.cv2.imshow"),
                      patch("calibrate_camera.cv2.waitKey", return_value=ord(" ")),
                      patch("calibrate_camera.cv2.destroyAllWindows"),
                      patch("calibrate_camera.cv2.calibrateCamera",
                            return_value=(0.5, np.eye(3), np.zeros(5), [], []))):
                    capture = capture_factory.return_value
                    capture.isOpened.return_value = True
                    capture.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
                    calibrate_camera_main()
                    capture.release.assert_called_once()
                saved = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(saved["samples"], 10)
                self.assertEqual(saved["square_size_mm"], 14.2)
                self.assertFalse(saved["verified_target_size"])

    def test_checkerboard_object_spacing_is_18_mm(self):
        points = board_object_points(9, 6, 18)
        self.assertEqual(points.shape, (54, 3))
        self.assertAlmostEqual(float(points[1, 0] - points[0, 0]), 0.018)
        phone_points = board_object_points(9, 6, 6.5)
        self.assertAlmostEqual(float(phone_points[1, 0] - phone_points[0, 0]), 0.0065)

    def test_phone_screen_requires_measured_square_size(self):
        result = subprocess.run([
            sys.executable, str(Path(__file__).parent / "calibrate_camera.py"),
            "--target", "phone_screen",
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--square-mm", result.stderr)

    def test_printed_marker_id_and_relative_pose(self):
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        marker = cv2.aruco.generateImageMarker(dictionary, 2, 200)
        frame[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        matrix = np.array([[800.0, 0, 320], [0, 800, 240], [0, 0, 1]])
        results = inspect(frame, cv2.aruco.ArucoDetector(dictionary), matrix,
                          np.zeros(5), marker_object_points(0.15))
        self.assertEqual(len(results), 1)
        marker_id, xyz, error = results[0]
        self.assertEqual(marker_id, 2)
        self.assertAlmostEqual(xyz[2], 0.603, places=2)
        self.assertLess(error, 1.0)

    def test_phone_screen_marker_id_recognition_needs_no_calibration(self):
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        marker = cv2.aruco.generateImageMarker(dictionary, 0, 200)
        frame[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        ids, corners = detect_ids(frame, cv2.aruco.ArucoDetector(dictionary))
        self.assertEqual(ids, [0])
        self.assertEqual(len(corners), 1)

    def test_marker_status_names_any_pathable_node(self):
        self.assertEqual(status_label([1])[0], "Detected: 1 -> B")
        self.assertEqual(status_label([5])[0], "Detected: 5 -> F")
        self.assertIn("Show marker", status_label([])[0])

    def test_floor_fit_checks_independent_measured_points(self):
        test_temp = Path(__file__).resolve().parent / ".test-tmp"
        if not test_temp.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise RuntimeError("Test temporary path escaped the workspace")
        test_temp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_temp) as directory:
            root = Path(directory)
            camera_path = root / "camera.json"
            points_path = root / "points.csv"
            output_path = root / "floor.json"
            camera_path.write_text(json.dumps({
                "image_size_px": [640, 480],
                "camera_matrix": [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
                "distortion_coefficients": [0, 0, 0, 0, 0],
            }), encoding="utf-8")
            pixels = [(100, 200), (540, 200), (100, 400), (540, 400),
                      (250, 300), (400, 350), (300, 250), (450, 380)]
            lines = ["pixel_x,pixel_y,floor_x_m,floor_y_m,role"]
            for index, (x, y) in enumerate(pixels):
                role = "fit" if index < 6 else "check"
                lines.append(f"{x},{y},{(x - 320) / 100},{(y - 240) / 100},{role}")
            points_path.write_text("\n".join(lines), encoding="utf-8")
            completed = subprocess.run([
                sys.executable, str(Path(__file__).parent / "calibrate_floor.py"),
                str(points_path), str(camera_path), "--output", str(output_path),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertLess(output["max_held_out_error_m"], 0.001)
            bad_lines = lines.copy()
            last = bad_lines[-1].split(",")
            last[2] = str(float(last[2]) + 1.0)
            bad_lines[-1] = ",".join(last)
            points_path.write_text("\n".join(bad_lines), encoding="utf-8")
            rejected_path = root / "rejected.json"
            rejected = subprocess.run([
                sys.executable, str(Path(__file__).parent / "calibrate_floor.py"),
                str(points_path), str(camera_path), "--output", str(rejected_path),
            ], capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(rejected_path.exists())


if __name__ == "__main__":
    unittest.main()
