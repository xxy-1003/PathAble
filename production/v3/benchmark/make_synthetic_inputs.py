"""Generate explicitly synthetic, non-performance-claim keyframes for smoke runs."""

import argparse
import csv
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "synthetic_inputs")
    args = parser.parse_args()
    import cv2
    import numpy as np
    args.output.mkdir(parents=True, exist_ok=True)
    h, w = 480, 640
    for index, shift in enumerate((0, 4, 8)):
        frame = np.full((h, w, 3), (92, 92, 92), dtype=np.uint8)
        cv2.rectangle(frame, (40, 80), (600, 470), (145, 145, 145), -1)
        cv2.rectangle(frame, (250 + shift, 210), (360 + shift, 420), (20, 20, 20), -1)
        cv2.circle(frame, (100 + index * 20, 150), 22, (210, 210, 210), -1)
        path = args.output / f"synthetic_{index:02d}.png"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"Could not write {path}")
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sequence_id", "timestamp_s", "path"))
        for index in range(3):
            writer.writerow(("synthetic-sequence-1", index * 0.5,
                             f"synthetic_{index:02d}.png"))
    (args.output / "DATASET_LABEL.txt").write_text(
        "SYNTHETIC FIXTURE: generated shapes, not recorded PathAble keyframes; "
        "not suitable for a performance claim or detection accuracy evaluation.\n",
        encoding="utf-8")
    print(f"Synthetic smoke fixture written to {args.output}")


if __name__ == "__main__":
    main()
