"""Cloud evidence from configured inference and measurement providers.

Missing models, recordings, or surveyed clearance remain unknown. Canned
workflow demonstrations live in simulated_recheck_tools.py and are opt-in.
"""

from pathlib import Path
import logging
import math

import cv2
import numpy as np

from ..schema.models import ClearanceResult, DetectionResult, MotionResult, RecheckToolsOutput

logger = logging.getLogger("pathable.cloud.recheck_tools")


class CloudRecheckTools:
    def __init__(self, history_provider=None, *, detector=None, model_path=None,
                 clearance_provider=None, keyframe_root=None):
        self._history_provider = history_provider or {}
        self.detector = detector
        if model_path is not None:
            try:
                from ...vision import SegmentationDetector
            except ImportError:  # cloud loaded from production/v3 as top-level package
                from vision import SegmentationDetector
            self.detector = SegmentationDetector(model_path)
        self.clearance_provider = clearance_provider
        self.keyframe_root = Path(keyframe_root).resolve() if keyframe_root else None

    def _frames(self, paths):
        if not paths:
            return []
        frames = []
        for path in paths:
            if not Path(path).is_file():
                return []
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                return []
            frames.append(frame)
        return frames

    def detect(self, keyframe_paths, fallback_classes=None, fallback_confidence=None):
        """Actual model inference only; event labels cannot become cloud detections."""
        unknown = DetectionResult(confidence=0.0, has_blocking_objects=False)
        frames = self._frames(keyframe_paths)
        if self.detector is None or not frames:
            return unknown
        try:
            results = [self.detector.detect(frame) for frame in frames]
            obstacles = [item for result in results for item in result.obstacles]
            return DetectionResult(
                evidence_status="observed", classes=sorted({item.name for item in obstacles}),
                confidence=max((item.confidence for item in obstacles), default=0.0),
                has_blocking_objects=any(item.coverage[1] >= 0.15 for item in obstacles),
                mask_coverage_percent=max(result.coverage[1] for result in results) * 100,
            )
        except (OSError, ValueError, RuntimeError, cv2.error):
            logger.exception("Cloud detector failed; evidence remains unknown")
            return unknown

    def motion(self, keyframe_paths, fallback_is_moving=None):
        """Observed frame motion heuristic; insufficient evidence is undetermined."""
        frames = self._frames(keyframe_paths)
        if len(frames) < 2 or frames[0].shape != frames[1].shape:
            return MotionResult()
        previous, current = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames[:2]]
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        average = float(np.mean(magnitude))
        if not np.isfinite(average):
            return MotionResult()
        moving = average > 2.0
        return MotionResult(evidence_status="observed", is_moving=moving,
                            average_flow_magnitude=average, motion_type="moving" if moving else "static")

    def clearance(self, ground_contact_m=None, occupied_zones=None, corridor_width_m=None,
                  *, keyframe_paths=()):
        """Only a trusted server measurement provider can supply metric clearance.

        Zone occupancy and obstacle range do not determine corridor free width.
        The provider must retain its surveyed geometry/source evidence for review.
        """
        if self.clearance_provider is None or not keyframe_paths:
            return ClearanceResult()
        try:
            result = self.clearance_provider(keyframe_paths)
        except (OSError, ValueError, RuntimeError):
            logger.exception("Clearance provider failed; measurement remains unknown")
            return ClearanceResult()
        if (not isinstance(result, ClearanceResult) or result.evidence_status != "observed"
                or result.free_clearance_m is None or not math.isfinite(result.free_clearance_m)
                or not result.measurement_source or not result.measurement_source.strip()):
            return ClearanceResult()
        # Recompute the threshold comparison instead of trusting a caller's bool.
        return result.model_copy(update={"meets_ms1184_standard": result.free_clearance_m >= 1.20})

    def history(self, edge):
        if callable(self._history_provider):
            return self._history_provider(edge.edge_key)
        return self._history_provider.get(edge.edge_key, [])

    def execute_all(self, event_id, edge, keyframe_paths, observations_summary):
        # Event filenames are untrusted: resolve only inside the configured evidence root.
        paths = []
        if self.keyframe_root is not None:
            for filename in keyframe_paths:
                path = (self.keyframe_root / filename).resolve()
                if not path.is_relative_to(self.keyframe_root) or not path.is_file():
                    paths = []
                    break
                paths.append(path)
        detection = self.detect(paths)
        motion = self.motion(paths)
        clearance = self.clearance(keyframe_paths=paths)
        mode = ("recorded" if all(item.evidence_status == "observed"
                                  for item in (detection, motion, clearance)) else "unavailable")
        return RecheckToolsOutput(evidence_mode=mode, event_id=event_id, edge=edge,
                                  detection=detection, motion=motion, clearance=clearance,
                                  history=self.history(edge))
