"""Inspect a short camera sample with OpenCV 5 YOLO segmentation, without saving frames."""

import argparse
from pathlib import Path
import statistics

from vision import SegmentationDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path(__file__).parent / "models" / "yolo11n-seg.onnx")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="dshow")
    parser.add_argument("--frames", type=int, default=10)
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error(f"Model not found: {args.model}")
    if not 1 <= args.frames <= 100:
        parser.error("--frames must be 1..100")

    import cv2
    backends = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
    detector = SegmentationDetector(args.model)
    capture = cv2.VideoCapture(args.camera, backends[args.backend])
    if not capture.isOpened():
        parser.error(f"Camera {args.camera} could not be opened")
    times = []
    try:
        for index in range(args.frames):
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit(f"Camera stopped delivering frames at sample {index + 1}")
            result = detector.detect(frame)
            times.append(result.inference_ms)
            names = ", ".join(f"{item.name} {item.confidence:.2f}" for item in result.obstacles)
            print(f"Frame {index + 1}: {names or 'no target-class detection'}; "
                  f"L/C/R mask coverage {[round(x, 3) for x in result.coverage]}; "
                  f"inference {result.inference_ms:.1f} ms")
    finally:
        capture.release()
    print(f"Median inference {statistics.median(times):.1f} ms over {len(times)} frames; "
          "capture, mask decoding, routing and speech are not included in this number.")
    print("No frames saved. Coverage is not calibrated distance or safe route guidance.")


if __name__ == "__main__":
    main()
