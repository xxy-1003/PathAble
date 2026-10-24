"""YOLO11n-seg decoding and ArUco junction localisation for PathAble.

The model must be a raw (NMS-free) Ultralytics COCO segmentation ONNX export.
OpenCV 5's new DNN engine is forced so a classic-engine fallback is visible.
"""

import os
os.environ["OPENCV_FORCE_DNN_ENGINE"] = "2"

from dataclasses import dataclass
from pathlib import Path
import time

import cv2
import numpy as np


CLASSES = {
    0: "person",
    13: "bench",
    24: "backpack",
    28: "suitcase",
    56: "chair",
    58: "potted plant",
    60: "dining table",
}

NODE_NAMES = {
    0: "A",
    1: "B",
    2: "C",
    3: "D",
    4: "E",
    5: "F",
}


@dataclass(frozen=True)
class Obstacle:
    name: str
    confidence: float
    box: tuple[int, int, int, int]
    contact: tuple[int, int] | None
    coverage: tuple[float, float, float]


@dataclass(frozen=True)
class VisionResult:
    obstacles: tuple[Obstacle, ...]
    coverage: tuple[float, float, float]
    inference_ms: float

    @property
    def occupied(self) -> tuple[bool, bool, bool]:
        return tuple(value >= 0.15 for value in self.coverage)


@dataclass(frozen=True)
class MarkerDetection:
    marker_id: int
    node: str
    corners: tuple[tuple[float, float], ...]


class MarkerLocalizer:
    """Detects ArUco junction markers (DICT_4X4_50) corresponding to nodes A-F."""

    def __init__(self, dictionary_id: int = cv2.aruco.DICT_4X4_50):
        self.dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        self.detector = cv2.aruco.ArucoDetector(self.dictionary)

    def detect(self, frame: np.ndarray) -> tuple[MarkerDetection, ...]:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim not in (2, 3):
            return ()
        if frame.size == 0:
            return ()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        corners, ids, _ = self.detector.detectMarkers(gray)
        if ids is None or len(ids) == 0:
            return ()
        results = []
        for marker_corners, marker_id in zip(corners, ids.flatten()):
            mid = int(marker_id)
            if mid in NODE_NAMES:
                c_pts = tuple(
                    (float(pt[0]), float(pt[1]))
                    for pt in marker_corners.reshape(4, 2)
                )
                results.append(MarkerDetection(marker_id=mid, node=NODE_NAMES[mid], corners=c_pts))
        return tuple(results)


def zone_coverage(mask: np.ndarray) -> tuple[float, float, float]:
    """Mask fractions in left, centre, right of the lower 60% of a frame."""
    if mask is None or not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.size == 0:
        return (0.0, 0.0, 0.0)
    height, width = mask.shape
    floor = mask[int(height * 0.4):]
    left_end = int(width * 0.3)
    right_start = int(width * 0.7)
    zones = (floor[:, :left_end], floor[:, left_end:right_start], floor[:, right_start:])
    return tuple(float(zone.mean()) if zone.size else 0.0 for zone in zones)


def letterbox(frame: np.ndarray, size: int = 640):
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    resized_width = round(width * scale)
    resized_height = round(height * scale)
    x0 = (size - resized_width) // 2
    y0 = (size - resized_height) // 2
    padded = np.full((size, size, 3), 114, dtype=np.uint8)
    padded[y0:y0 + resized_height, x0:x0 + resized_width] = cv2.resize(
        frame, (resized_width, resized_height)
    )
    return padded, scale, x0, y0, resized_width, resized_height


class SegmentationDetector:
    def __init__(self, model_path: str | Path):
        if not cv2.__version__.startswith("5."):
            raise RuntimeError(f"OpenCV 5 required, found {cv2.__version__}")
        self.net = cv2.dnn.readNetFromONNX(str(model_path))
        self.output_names = self.net.getUnconnectedOutLayersNames()

    def detect(self, frame: np.ndarray) -> VisionResult:
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Expected a BGR camera frame")
        original_height, original_width = frame.shape[:2]
        padded, scale, x0, y0, resized_width, resized_height = letterbox(frame)
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (640, 640), swapRB=True)
        self.net.setInput(blob)
        started = time.perf_counter()
        outputs = self.net.forward(self.output_names)
        inference_ms = (time.perf_counter() - started) * 1000
        if len(outputs) != 2:
            raise RuntimeError(f"Expected two segmentation outputs; got {len(outputs)}")
        predictions, prototype = outputs
        if predictions.shape != (1, 116, 8400) or prototype.shape != (1, 32, 160, 160):
            raise RuntimeError(f"Unexpected YOLO11n-seg shapes: {predictions.shape}, {prototype.shape}")

        predictions = predictions[0].T
        boxes, scores, class_ids, coefficients = [], [], [], []
        for prediction in predictions:
            class_id = int(np.argmax(prediction[4:84]))
            confidence = float(prediction[4 + class_id])
            if class_id not in CLASSES or confidence < 0.40:
                continue
            cx, cy, width, height = map(float, prediction[:4])
            left = max(0, int(cx - width / 2))
            top = max(0, int(cy - height / 2))
            right = min(640, int(cx + width / 2))
            bottom = min(640, int(cy + height / 2))
            if right <= left or bottom <= top:
                continue
            boxes.append([left, top, right - left, bottom - top])
            scores.append(confidence)
            class_ids.append(class_id)
            coefficients.append(prediction[84:116])

        union = np.zeros((original_height, original_width), dtype=bool)
        obstacles = []
        if boxes:
            indices = np.array(cv2.dnn.NMSBoxes(boxes, scores, 0.40, 0.45)).reshape(-1)
            proto = prototype[0].reshape(32, -1)
            for index in indices:
                index = int(index)
                logits = coefficients[index] @ proto
                small_mask = 1.0 / (1.0 + np.exp(-np.clip(logits, -50, 50)))
                padded_mask = cv2.resize(small_mask.reshape(160, 160), (640, 640))
                left, top, width, height = boxes[index]
                box_mask = np.zeros((640, 640), dtype=np.uint8)
                box_mask[top:top + height, left:left + width] = 1
                padded_mask = (padded_mask > 0.5) & (box_mask != 0)
                unpadded = padded_mask[y0:y0 + resized_height, x0:x0 + resized_width]
                mask = cv2.resize(unpadded.astype(np.uint8),
                                  (original_width, original_height), interpolation=cv2.INTER_NEAREST) != 0
                union |= mask

                ys, xs = np.nonzero(mask)
                contact = None
                if len(ys):
                    lowest = int(ys.max())
                    contact = (int(np.median(xs[ys == lowest])), lowest)
                original_box = (
                    max(0, round((left - x0) / scale)),
                    max(0, round((top - y0) / scale)),
                    min(original_width, round((left + width - x0) / scale)),
                    min(original_height, round((top + height - y0) / scale)),
                )
                obstacles.append(Obstacle(CLASSES[class_ids[index]], scores[index],
                                          original_box, contact, zone_coverage(mask)))
        return VisionResult(tuple(obstacles), zone_coverage(union), inference_ms)
