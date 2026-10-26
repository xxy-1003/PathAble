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
from vision import MarkerLocalizer, SegmentationDetector, VisionResult


class FloorProjector:
    def __init__(self, camera_path: str | Path, floor_path: str | Path):
        self.ready = False
        self.image_size: tuple[int, int] | None = None
        try:
            camera_bytes = Path(camera_path).read_bytes()
            camera = json.loads(camera_bytes)
            floor = json.loads(Path(floor_path).read_text(encoding="utf-8"))
            if (camera.get("calibration_method") != "opencv_checkerboard"
                    or camera.get("calibration_target") not in {"printed_board", "phone_screen"}
                    or floor.get("calibration_method") != "surveyed_homography"
                    or camera.get("verified_target_size", camera.get("verified_print_size")) is not True
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


def observation_from_vision(
    result: VisionResult,
    timestamp: float,
    frame_size: tuple[int, int],
    projector: FloorProjector,
    *,
    same_pose_verified: bool = False,
    node: str | None = None,
    moving: bool = False,
    allow_clear: bool = False,
) -> Observation:
    """Produce an observation for review/replay, preserving fail-closed behavior.

    The legacy allow_clear argument is retained for callers but cannot promote
    absent detections into free-space evidence. Unoccupied zones remain unknown.
    """
    occupied = result.occupied
    zones = tuple("occupied" if value else "unknown" for value in occupied)

    centre_obstacles = [item for item in result.obstacles if item.coverage[1] >= 0.15]
    distances = [
        projector.distance_metres(item.contact, frame_size, same_pose_verified=same_pose_verified)
        for item in centre_obstacles
    ]

    if centre_obstacles and all(value is not None for value in distances):
        nearest = centre_obstacles[distances.index(min(distances))]
        distance = projector.distance_band(
            nearest.contact, frame_size, same_pose_verified=same_pose_verified
        )
        name = nearest.name
        confidence = nearest.confidence
    elif centre_obstacles:
        distance = "unknown"
        name = centre_obstacles[0].name
        confidence = max((item.confidence for item in centre_obstacles), default=0.0)
    else:
        name = None
        distance = "unknown"
        confidence = 0.0

    return Observation(timestamp, name, confidence, *zones, distance, moving=moving, node=node)


class PerceptionPipeline:
    """End-to-end camera/model/marker perception pipeline producing conservative Observation instances.

    Strictly preserves fail-closed behavior at every step:
    - Missing or invalid calibration -> distance is 'unknown'
    - Missing model -> zones remain 'unknown' (never assumed 'clear')
    - Sensor corruption / missing frame -> fail-closed unknown observation
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        camera_path: str | Path | None = None,
        floor_path: str | Path | None = None,
        *,
        detector: SegmentationDetector | None = None,
        localizer: MarkerLocalizer | None = None,
        projector: FloorProjector | None = None,
        same_pose_verified: bool = False,
        allow_clear: bool = False,
    ):
        if detector is not None:
            self.detector = detector
        elif model_path is not None and Path(model_path).is_file():
            self.detector = SegmentationDetector(model_path)
        else:
            self.detector = None

        if localizer is not None:
            self.localizer = localizer
        else:
            try:
                self.localizer = MarkerLocalizer()
            except Exception:
                self.localizer = None

        if projector is not None:
            self.projector = projector
        elif camera_path is not None and floor_path is not None:
            self.projector = FloorProjector(camera_path, floor_path)
        else:
            self.projector = FloorProjector("", "")

        self.same_pose_verified = same_pose_verified
        self.allow_clear = allow_clear
        self.last_vision_result: VisionResult | None = None

    def process_frame(
        self,
        frame: np.ndarray | None,
        timestamp: float,
        *,
        moving: bool = False,
    ) -> Observation:
        """Process a camera frame and emit a conservative Observation."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0 or frame.ndim != 3:
            self.last_vision_result = None
            return Observation(
                timestamp=timestamp,
                obstacle_class=None,
                confidence=0.0,
                left="unknown",
                centre="unknown",
                right="unknown",
                distance="unknown",
                moving=False,
                node=None,
            )

        frame_size = (frame.shape[1], frame.shape[0])

        # 1. Junction marker detection (nodes A-F)
        node = None
        if self.localizer is not None:
            markers = self.localizer.detect(frame)
            if markers:
                node = markers[0].node

        # 2. Obstacle perception
        if self.detector is not None:
            vision_result = self.detector.detect(frame)
            effective_allow_clear = self.allow_clear
        else:
            # Without an active neural network detector, we must never claim a corridor is clear
            vision_result = VisionResult((), (0.0, 0.0, 0.0), 0.0)
            effective_allow_clear = False
        self.last_vision_result = vision_result

        # 3. Floor projection & conservative observation synthesis
        return observation_from_vision(
            vision_result,
            timestamp,
            frame_size,
            self.projector,
            same_pose_verified=self.same_pose_verified,
            node=node,
            moving=moving,
            allow_clear=effective_allow_clear,
        )
