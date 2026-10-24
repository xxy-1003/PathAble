"""Recorded-keyframe re-check used by the COOL/stock benchmark.

This is a measurement adapter around the v3 perception and calibration code.
It does not make navigation decisions. Distances and floor spans are evidence
only when an explicitly verified calibration is supplied.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any
import sys

import cv2
import numpy as np

V3_ROOT = Path(__file__).resolve().parents[1]
if str(V3_ROOT) not in sys.path:
    sys.path.insert(0, str(V3_ROOT))

from calibrated_observation import FloorProjector
from vision import SegmentationDetector


def _flow_evidence(previous: np.ndarray | None, current: np.ndarray,
                   boxes: list[tuple[int, int, int, int]], elapsed_s: float) -> dict[str, Any]:
    if previous is None:
        return {"status": "unknown", "reason": "first_keyframe", "objects": []}
    if elapsed_s <= 0 or previous.shape != current.shape:
        return {"status": "unknown", "reason": "invalid_interval_or_shape", "objects": []}
    prior_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(prior_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    h, w = gray.shape
    # Estimate camera/background motion from the whole frame, then subtract it
    # from each detected object's mean flow. This is only a heuristic for a
    # fixed camera recording, so the result is always labelled evidence.
    global_dx = float(np.median(flow[..., 0]))
    global_dy = float(np.median(flow[..., 1]))
    objects = []
    for x1, y1, x2, y2 in boxes:
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        roi = flow[y1:y2, x1:x2]
        dx = float(np.median(roi[..., 0])) - global_dx
        dy = float(np.median(roi[..., 1])) - global_dy
        speed = math.hypot(dx, dy) / elapsed_s
        objects.append({"box_xyxy": [x1, y1, x2, y2],
                        "relative_flow_px_s": round(speed, 4),
                        "motion": "moving" if speed >= 2.0 else "static_candidate"})
    return {"status": "measured", "method": "Farneback ROI median minus frame median",
            "threshold_px_s": 2.0, "objects": objects}


def _floor_span(projector: FloorProjector | None, box: tuple[int, int, int, int],
                frame_size: tuple[int, int], same_pose_verified: bool,
                corridor_x_limits_m: tuple[float, float] | None) -> dict[str, Any]:
    if projector is None or not projector.ready:
        return {"status": "unknown", "reason": "verified_floor_calibration_unavailable"}
    if same_pose_verified is not True or frame_size != projector.image_size:
        return {"status": "unknown", "reason": "same_pose_or_calibrated_resolution_not_verified"}
    x1, y1, x2, y2 = box
    # Use the lower box edge as a coarse floor-contact span. The trained mask
    # contact remains the preferred distance evidence; box span is not a
    # certified accessible route-width measurement.
    y = max(y1, y2 - 1)
    def project(x):
        point = np.array([[[x, y]]], dtype=np.float64)
        undistorted = cv2.undistortPoints(point, projector.matrix, projector.distortion,
                                          P=projector.matrix).reshape(2)
        if (not np.isfinite(undistorted).all()
                or cv2.pointPolygonTest(projector.hull, tuple(map(float, undistorted)), False) < 0):
            return None
        return cv2.perspectiveTransform(
            undistorted.reshape(1, 1, 2), projector.homography).reshape(2)
    left, right = project(x1), project(x2 - 1)
    if left is None or right is None or not np.isfinite(left).all() or not np.isfinite(right).all():
        return {"status": "unknown", "reason": "span_outside_calibrated_fit_region"}
    span = float(np.linalg.norm(right - left))
    evidence = {"status": "estimated", "floor_contact_span_m": round(span, 4),
                "limitation": "projected box-edge span; geometry estimate, not a compliance decision"}
    if corridor_x_limits_m is not None:
        corridor_left, corridor_right = corridor_x_limits_m
        object_left, object_right = sorted((float(left[0]), float(right[0])))
        object_left = min(corridor_right, max(corridor_left, object_left))
        object_right = min(corridor_right, max(corridor_left, object_right))
        left_gap = max(0.0, object_left - corridor_left)
        right_gap = max(0.0, corridor_right - object_right)
        evidence.update({"corridor_x_limits_m": [corridor_left, corridor_right],
                         "left_passage_estimate_m": round(left_gap, 4),
                         "right_passage_estimate_m": round(right_gap, 4),
                         "widest_side_passage_estimate_m": round(max(left_gap, right_gap), 4),
                         "clearance_limitation": "requires measured corridor wall x limits in calibration axes; box-edge projection is approximate"})
    return evidence


class RecordedRechecker:
    def __init__(self, model_path: Path, camera_calibration: Path | None = None,
                 floor_calibration: Path | None = None, *, same_pose_verified: bool = False,
                 corridor_x_limits_m: tuple[float, float] | None = None):
        self.detector = SegmentationDetector(model_path)
        self.projector = (FloorProjector(camera_calibration, floor_calibration)
                          if camera_calibration and floor_calibration else None)
        self.same_pose_verified = same_pose_verified
        if corridor_x_limits_m is not None and corridor_x_limits_m[0] >= corridor_x_limits_m[1]:
            raise ValueError("corridor x limits must be increasing")
        self.corridor_x_limits_m = corridor_x_limits_m
        self.previous: dict[str, tuple[np.ndarray, float]] = {}

    def recheck(self, keyframe_id: str, image_path: Path, timestamp_s: float) -> dict[str, Any]:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Cannot decode keyframe: {image_path}")
        result = self.detector.detect(frame)
        boxes = [tuple(map(int, obstacle.box)) for obstacle in result.obstacles]
        prior = self.previous.get(keyframe_id)
        flow = _flow_evidence(prior[0] if prior else None, frame, boxes,
                              timestamp_s - prior[1] if prior else 0.0)
        self.previous[keyframe_id] = (frame, timestamp_s)
        h, w = frame.shape[:2]
        obstacles = []
        flow_objects = flow.get("objects", [])
        for object_index, obstacle in enumerate(result.obstacles):
            distance_m = (self.projector.distance_metres(
                obstacle.contact, (w, h), same_pose_verified=self.same_pose_verified)
                if self.projector else None)
            obstacles.append({
                "class": obstacle.name,
                "confidence": round(float(obstacle.confidence), 6),
                "object_index": object_index,
                "box_xyxy": list(obstacle.box),
                "mask_contact_xy": list(obstacle.contact) if obstacle.contact else None,
                "zone_coverage_lcr": [round(float(v), 6) for v in obstacle.coverage],
                "distance_m": round(distance_m, 4) if distance_m is not None else None,
                "floor_clearance_evidence": _floor_span(
                    self.projector, obstacle.box, (w, h), self.same_pose_verified,
                    self.corridor_x_limits_m),
                "motion_evidence": flow_objects[object_index]
                if object_index < len(flow_objects) else {"status": "unknown",
                                                         "reason": flow.get("reason", "no_motion_estimate")},
            })
        return {
            "keyframe_id": keyframe_id,
            "timestamp_s": timestamp_s,
            "object_evidence": obstacles,
            "motion_check": flow,
            "zone_coverage_lcr": [round(float(v), 6) for v in result.coverage],
            "floor_calibration_used": bool(self.projector and self.projector.ready
                                            and self.same_pose_verified),
            "detector_inference_ms": round(float(result.inference_ms), 4),
        }
