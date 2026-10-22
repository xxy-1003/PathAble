"""Conservative floor-distance adapter for fixed-pose, recorded-frame experiments.

The calibration files are deliberately insufficient on their own: the caller
must affirm that the current frame uses the measured camera pose. This module
does not authorize live walking guidance or treat no detection as clear space.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from local_agent import Distance, Observation
from vision import VisionResult


class FloorProjector:
    def __init__(self, camera_path: str | Path, floor_path: str | Path):
        self.ready = False
        self.image_size: tuple[int, int] | None = None
        try:
            camera_bytes = Path(camera_path).read_bytes()
            camera = json.loads(camera_bytes)
            floor = json.loads(Path(floor_path).read_text(encoding="utf-8"))
            if (camera.get("verified_print_size") is not True
                    or not camera.get("mount_description")
                    or floor.get("fixed_mount_verified") is not True
                    or not isinstance(floor.get("floor_origin_and_axes"), str)
                    or floor["floor_origin_and_axes"].startswith("FILL IN:")
                    or not floor["floor_origin_and_axes"].strip()
                    or floor.get("camera_calibration_sha256") != hashlib.sha256(camera_bytes).hexdigest()):
                return
            size = camera["image_size_px"]
            if (len(size) != 2 or not all(type(v) is int and v > 0 for v in size)
                    or size != floor["image_size_px"]):
                return
            if (camera["samples"] < 10 or not 0 <= camera["rms_reprojection_px"] <= 1.5
                    or floor["fit_points"] < 6 or floor["check_points"] < 2
                    or not 0 <= floor["max_held_out_error_m"] <= 0.15):
                return
            matrix = np.asarray(camera["camera_matrix"], dtype=np.float64)
            distortion = np.asarray(camera["distortion_coefficients"], dtype=np.float64)
            homography = np.asarray(floor["homography_undistorted_px_to_floor_m"], dtype=np.float64)
            anchor = np.asarray(floor["camera_floor_xy_m"], dtype=np.float64)
            hull = np.asarray(floor["fit_region_undistorted_px"], dtype=np.float32)
            if (matrix.shape != (3, 3) or homography.shape != (3, 3)
                    or anchor.shape != (2,) or hull.ndim != 2 or hull.shape[1] != 2
                    or hull.shape[0] < 3 or distortion.size < 4
                    or not all(np.isfinite(item).all() for item in
                               (matrix, distortion, homography, anchor, hull))
                    or abs(np.linalg.det(homography)) < 1e-12):
                return
            self.matrix = matrix
            self.distortion = distortion
            self.homography = homography
            self.anchor = anchor
            self.hull = hull
            self.error_m = float(floor["max_held_out_error_m"])
            self.image_size = (size[0], size[1])
            self.ready = True
        except (OSError, ValueError, TypeError, KeyError, cv2.error):
            return

    def distance_metres(self, contact: tuple[int, int] | None,
                        frame_size: tuple[int, int], *, same_pose_verified: bool = False) -> float | None:
        if (not self.ready or same_pose_verified is not True
                or frame_size != self.image_size or contact is None):
            return None
        x, y = contact
        if not (math.isfinite(x) and math.isfinite(y)
                and 0 <= x < frame_size[0] and 0 <= y < frame_size[1]):
            return None
        try:
            point = np.array([[[x, y]]], dtype=np.float64)
            undistorted = cv2.undistortPoints(point, self.matrix, self.distortion,
                                              P=self.matrix).reshape(2)
            if (not np.isfinite(undistorted).all()
                    or cv2.pointPolygonTest(self.hull, tuple(map(float, undistorted)), False) < 0):
                return None
            floor_xy = cv2.perspectiveTransform(
                undistorted.reshape(1, 1, 2), self.homography).reshape(2)
            if not np.isfinite(floor_xy).all():
                return None
            return float(np.linalg.norm(floor_xy - self.anchor))
        except (ValueError, TypeError, cv2.error):
            return None

    def distance_band(self, contact: tuple[int, int] | None,
                      frame_size: tuple[int, int], *, same_pose_verified: bool = False) -> Distance:
        distance = self.distance_metres(contact, frame_size,
                                       same_pose_verified=same_pose_verified)
        if distance is None:
            return "unknown"
        # Provisional demo bands. A held-out residual is only an observed error,
        # not a safety guarantee; values close to a boundary stay unknown.
        if distance + self.error_m < 1.0:
            return "near"
        if distance - self.error_m > 1.0 and distance + self.error_m < 2.5:
            return "medium"
        if distance - self.error_m > 2.5:
            return "far"
        return "unknown"


def observation_from_vision(result: VisionResult, timestamp: float,
                            frame_size: tuple[int, int], projector: FloorProjector,
                            *, same_pose_verified: bool = False) -> Observation:
    """Produce an observation for review/replay, never evidence of clear space."""
    occupied = result.occupied
    zones = tuple("occupied" if value else "unknown" for value in occupied)
    centre_obstacles = [item for item in result.obstacles if item.coverage[1] >= 0.15]
    distances = [projector.distance_metres(item.contact, frame_size,
                                           same_pose_verified=same_pose_verified)
                 for item in centre_obstacles]
    if centre_obstacles and all(value is not None for value in distances):
        nearest = centre_obstacles[distances.index(min(distances))]
        distance = projector.distance_band(nearest.contact, frame_size,
                                           same_pose_verified=same_pose_verified)
        name = nearest.name
        confidence = nearest.confidence
    else:
        distance = "unknown"
        name = centre_obstacles[0].name if centre_obstacles else None
        confidence = max((item.confidence for item in centre_obstacles), default=0.0)
    return Observation(timestamp, name, confidence, *zones, distance)
