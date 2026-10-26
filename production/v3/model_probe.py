"""Go/no-go check: force OpenCV 5's new DNN engine on a supplied ONNX file.

Run with the same Python and model that will be used for the laptop demo.
This does not establish detection quality or real-time speed.
"""

import argparse
import os
from pathlib import Path
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path, help="Path to exported YOLO11n-seg ONNX model")
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error(f"Model not found: {args.model}")

    # OpenCV documents value 2 as 'new engine only'; auto mode could silently
    # fall back to classic and produce a misleading competition claim.
    os.environ["OPENCV_FORCE_DNN_ENGINE"] = "2"
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        parser.error(f"Install OpenCV 5 and NumPy in the demo environment: {exc}")
    if not cv2.__version__.startswith("5."):
        parser.error(f"OpenCV 5 required, found {cv2.__version__}")

    started = time.perf_counter()
    net = cv2.dnn.readNetFromONNX(str(args.model))
    load_ms = (time.perf_counter() - started) * 1000
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    net.setInput(np.zeros((1, 3, 640, 640), dtype=np.float32))
    started = time.perf_counter()
    outputs = net.forward(net.getUnconnectedOutLayersNames())
    inference_ms = (time.perf_counter() - started) * 1000
    print(f"OpenCV {cv2.__version__}; forced new DNN engine")
    print(f"Model load: {load_ms:.1f} ms; blank-frame inference: {inference_ms:.1f} ms")
    print("Output shapes:", [tuple(output.shape) for output in outputs])
    if len(outputs) < 2:
        raise SystemExit("No-go: expected detection and segmentation prototype outputs")
    print("Go for tensor-decoder development; real frames and latency still need testing.")


if __name__ == "__main__":
    main()
