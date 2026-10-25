"""Fixed-view chair-overlap demo; never declares free space or physical blockage."""

from collections import deque
import math


class ChairRegionMonitor:
    def __init__(self, region=(0.36, 0.42, 0.72, 0.90)):
        if len(region) != 4 or not all(math.isfinite(v) for v in region):
            raise ValueError('Region needs four finite normalised coordinates')
        x1, y1, x2, y2 = region
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError('Region must lie inside image')
        self.region = tuple(region)
        self.samples = deque()
        self.last_time = None

    def pixel_region(self, size):
        width, height = size
        return tuple(round(v * (width if i % 2 == 0 else height))
                     for i, v in enumerate(self.region))

    def update(self, result, timestamp, size):
        if not math.isfinite(timestamp) or (self.last_time is not None and timestamp < self.last_time):
            raise ValueError('Monitor timestamps must be finite and ordered')
        if self.last_time is not None and timestamp - self.last_time > 0.75:
            self.samples.clear()
        self.last_time = timestamp
        x1, y1, x2, y2 = self.pixel_region(size)
        area = max(1, (x2 - x1) * (y2 - y1))
        best = None
        if result is not None:
            for obstacle in result.obstacles:
                if obstacle.name != 'chair' or obstacle.confidence < 0.60:
                    continue
                a, b, c, d = obstacle.box
                overlap = max(0, min(c, x2) - max(a, x1)) * max(0, min(d, y2) - max(b, y1)) / area
                if overlap >= 0.25 and (best is None or overlap > best['region_overlap']):
                    best = dict(confidence=obstacle.confidence, region_overlap=overlap,
                                box=list(obstacle.box))
        self.samples.append((timestamp, best is not None))
        while self.samples and timestamp - self.samples[0][0] > 2.0:
            self.samples.popleft()
        positives = [t for t, detected in self.samples if detected]
        sustained = (best is not None and len(positives) >= 6
                     and positives[-1] - positives[0] >= 1.0
                     and len(positives) / len(self.samples) >= 0.80)
        return dict(trigger=bool(sustained), positive_frames=len(positives),
                    total_frames=len(self.samples), current=best,
                    region_normalised=list(self.region),
                    rule='chair score >=0.60; bbox covers >=25% region; >=6 positives spanning >=1s, >=80% over last 2s',
                    physical_blockage_verified=False)
