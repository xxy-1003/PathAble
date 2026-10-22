"""Read ArUco junction IDs and relative poses with calibrated camera intrinsics.

This reports marker-relative pose only. Map heading requires surveyed marker
orientation and a fixed camera mount, so this probe issues no turn commands.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def marker_object_points(side_metres: float) -> np.ndarray:
    half = side_metres / 2
    return np.asarray([[-half, half, 0], [half, half, 0],
                       [half, -half, 0], [-half, -half, 0]], dtype=np.float32)


def inspect(frame, detector, camera_matrix, distortion, object_points):
    corners, ids, _ = detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    results = []
    if ids is None:
        return results
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        if not 0 <= int(marker_id) <= 5:
            continue
        okay, rotation, translation = cv2.solvePnP(
            object_points, marker_corners.reshape(4, 2), camera_matrix, distortion,
            flags=cv2.SOLVEPNP_IPPE_SQUARE
        )
        if not okay or translation[2, 0] <= 0:
            continue
        projected, _ = cv2.projectPoints(object_points, rotation, translation,
                                         camera_matrix, distortion)
        error_px = float(np.sqrt(np.mean(np.sum(
            (projected.reshape(4, 2) - marker_corners.reshape(4, 2)) ** 2, axis=1
        ))))
        if error_px <= 3.0:
            results.append((int(marker_id), translation.ravel().tolist(), error_px))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibration", type=Path, help="Camera JSON from calibrate_camera.py")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--marker-mm", type=float, default=150.0)
    args = parser.parse_args()
    if args.marker_mm <= 0 or not 1 <= args.frames <= 300:
        parser.error("Use a positive marker size and 1..300 frames")
    calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
    matrix = np.asarray(calibration["camera_matrix"], dtype=np.float64)
    distortion = np.asarray(calibration["distortion_coefficients"], dtype=np.float64)
    expected_size = tuple(calibration["image_size_px"])
    if not calibration.get("verified_target_size", calibration.get("verified_print_size")):
        print("WARNING: calibration-square size has not been marked verified.")
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    )
    object_points = marker_object_points(args.marker_mm / 1000)
    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error("Camera could not be opened")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, expected_size[0])
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, expected_size[1])
    try:
        for frame_index in range(args.frames):
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit("Camera stopped delivering frames")
            if (frame.shape[1], frame.shape[0]) != expected_size:
                raise SystemExit("Camera resolution differs from its calibration")
            results = inspect(frame, detector, matrix, distortion, object_points)
            if results:
                for marker_id, xyz, error_px in results:
                    print(f"Frame {frame_index + 1}: marker {marker_id} -> node "
                          f"{'ABCDEF'[marker_id]}, relative xyz {np.round(xyz, 3)} m, "
                          f"reprojection error {error_px:.2f} px")
            else:
                print(f"Frame {frame_index + 1}: no verified junction marker")
    finally:
        capture.release()
    print("Marker-relative pose only; map heading and turn direction remain unverified.")


if __name__ == "__main__":
    main()
