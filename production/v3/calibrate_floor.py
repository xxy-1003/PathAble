"""Fit a floor pixel-to-metre homography with held-out measured check points.

CSV roles: at least six 'fit' points and two different 'check' points. Coordinates
must come from one undistorted frame at the fixed demonstration camera pose.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def load_points(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        expected = {"pixel_x", "pixel_y", "floor_x_m", "floor_y_m", "role"}
        if set(reader.fieldnames or []) != expected:
            raise ValueError(f"CSV must contain columns: {', '.join(sorted(expected))}")
        points = [(float(row["pixel_x"]), float(row["pixel_y"]),
                   float(row["floor_x_m"]), float(row["floor_y_m"]), row["role"].strip())
                  for row in reader]
    if any(not np.isfinite(values[:4]).all() or values[4] not in ("fit", "check")
           for values in points):
        raise ValueError("Every row needs finite coordinates and role fit or check")
    return points


def project(points: np.ndarray, homography: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(points.reshape(-1, 1, 2), homography).reshape(-1, 2)


def fit_floor_homography(pixels: np.ndarray, metres: np.ndarray):
    """Keep the same physical inlier limit when MAGSAC cannot fit a layout."""
    for name, method in (("USAC_MAGSAC", cv2.USAC_MAGSAC), ("RANSAC", cv2.RANSAC)):
        homography, inliers = cv2.findHomography(pixels, metres, method, 0.10)
        if (homography is not None and inliers is not None
                and np.isfinite(homography).all() and inliers.sum() >= 6):
            residuals = np.linalg.norm(project(pixels, homography) - metres, axis=1)
            accepted = inliers.ravel() != 0
            if np.isfinite(residuals).all() and np.all(residuals[accepted] <= 0.10):
                if name == "RANSAC":
                    print("MAGSAC did not produce a usable fit; using RANSAC with the same 0.10 m inlier limit.")
                return homography, inliers, name
    raise ValueError("Homography needs at least six inlier fit points; remeasure the floor")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("points", type=Path, help="Measured point CSV based on the fixed camera frame")
    parser.add_argument("calibration", type=Path, help="Camera JSON from calibrate_camera.py")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "calibration" / "floor.json")
    args = parser.parse_args()
    points = load_points(args.points)
    fit = [row for row in points if row[4] == "fit"]
    checks = [row for row in points if row[4] == "check"]
    if len(fit) < 6 or len(checks) < 2:
        parser.error("Use at least six spread-out fit points and two separate check points")

    camera_bytes = args.calibration.read_bytes()
    camera = json.loads(camera_bytes)
    matrix = np.asarray(camera["camera_matrix"], dtype=np.float64)
    distortion = np.asarray(camera["distortion_coefficients"], dtype=np.float64)
    if matrix.shape != (3, 3):
        parser.error("Invalid camera matrix")
    image_size = camera.get("image_size_px")
    if (not isinstance(image_size, list) or len(image_size) != 2
            or any(not isinstance(value, int) or value <= 0 for value in image_size)):
        parser.error("Camera calibration needs a valid image_size_px")

    def undistorted(rows):
        pixels = np.asarray([[row[0], row[1]] for row in rows], dtype=np.float64)
        return cv2.undistortPoints(pixels.reshape(-1, 1, 2), matrix, distortion, P=matrix).reshape(-1, 2)

    fit_pixels = undistorted(fit)
    fit_metres = np.asarray([[row[2], row[3]] for row in fit], dtype=np.float64)
    try:
        homography, inliers, estimator = fit_floor_homography(fit_pixels, fit_metres)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    check_pixels = undistorted(checks)
    check_metres = np.asarray([[row[2], row[3]] for row in checks], dtype=np.float64)
    errors = np.linalg.norm(project(check_pixels, homography) - check_metres, axis=1)
    max_error = float(errors.max())
    print(f"Fit inliers: {int(inliers.sum())}/{len(fit)}; held-out errors: "
          f"{[round(float(value), 3) for value in errors]} m")
    if not np.isfinite(homography).all() or max_error > 0.15:
        raise SystemExit("Floor calibration rejected: held-out error exceeds 0.15 m")
    result = {
        "calibration_method": "surveyed_homography",
        "homography_estimator": estimator,
        "homography_undistorted_px_to_floor_m": homography.tolist(),
        "camera_calibration": str(args.calibration.resolve()),
        "camera_calibration_sha256": hashlib.sha256(camera_bytes).hexdigest(),
        "image_size_px": image_size,
        "fit_region_undistorted_px": cv2.convexHull(
            fit_pixels[inliers.ravel() != 0].astype(np.float32)).reshape(-1, 2).tolist(),
        "fit_points": len(fit),
        "inliers": int(inliers.sum()),
        "check_points": len(checks),
        "max_held_out_error_m": max_error,
        "floor_origin_and_axes": "FILL IN: measured origin and x/y directions",
        "camera_floor_xy_m": None,
        "fixed_mount_verified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {args.output}; verify mount, floor origin and axes before use")


if __name__ == "__main__":
    main()
