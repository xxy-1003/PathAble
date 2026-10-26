"""Run the end-to-end camera, model, and ArUco marker pipeline to stream Observation instances.

Captures from the Logitech USB webcam at 640x480, extracts YOLO11n-seg obstacle
masks and ArUco junction nodes (A-F), and maps contact points via floor homography.
Strictly preserves fail-closed behavior: unverified calibration yields 'unknown'
distance, and non-occupied zones remain 'unknown' (never assumed 'clear').
"""

import argparse
from pathlib import Path
import time

import cv2

from calibrated_observation import PerceptionPipeline


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream fail-closed Observation values from camera, model, and markers"
    )
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0 for Logitech C920)")
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="dshow")
    parser.add_argument("--frames", type=int, default=10, help="Number of frames to process (default: 10)")
    parser.add_argument("--model", type=Path, default=Path(__file__).parent / "models" / "yolo11n-seg.onnx")
    parser.add_argument("--camera-json", type=Path, default=Path(__file__).parent / "calibration" / "camera.json")
    parser.add_argument("--floor-json", type=Path, default=Path(__file__).parent / "calibration" / "floor.json")
    args = parser.parse_args()

    if not 1 <= args.frames <= 500:
        parser.error("--frames must be between 1 and 500")

    print("Initializing PathAble Perception Pipeline...")
    pipeline = PerceptionPipeline(
        model_path=args.model if args.model.is_file() else None,
        camera_path=args.camera_json if args.camera_json.is_file() else None,
        floor_path=args.floor_json if args.floor_json.is_file() else None,
    )

    has_model = pipeline.detector is not None
    has_calib = pipeline.projector.ready
    print(f"  YOLO11n-seg Model: {'LOADED' if has_model else 'NOT FOUND (using fail-closed fallback)'}")
    print(f"  Floor Calibration: {'READY' if has_calib else 'UNVERIFIED (distances will be unknown)'}")
    print(f"  ArUco Localizer:   {'READY (DICT_4X4_50)' if pipeline.localizer else 'UNAVAILABLE'}")
    print(f"Opening camera {args.camera} ({args.backend}) at 640x480...")

    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error(f"Could not open camera {args.camera}. Ensure no other app is using it.")

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("\nStreaming conservative Observation instances:")
    print("-" * 75)
    try:
        for idx in range(args.frames):
            timestamp = time.time()
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit(f"Camera stopped delivering frames at frame {idx + 1}")

            obs = pipeline.process_frame(frame, timestamp)
            print(
                f"[{idx + 1:02d}] Node: {obs.node or '-':1s} | "
                f"Class: {obs.obstacle_class or 'none':10s} (conf: {obs.confidence:0.2f}) | "
                f"L/C/R: ({obs.left:7s}, {obs.centre:8s}, {obs.right:7s}) | "
                f"Dist: {obs.distance:7s}"
            )
    finally:
        capture.release()
    print("-" * 75)
    print("Pipeline probe complete. All observations adhere to fail-closed safety semantics.")


if __name__ == "__main__":
    main()
