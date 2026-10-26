"""List camera indices visible to OpenCV without saving any frames.

Use the laptop webcam or an Android phone exposed as a Windows connected camera.
This is a capture check, not a latency or navigation safety validation.
"""

import argparse
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-index", type=int, default=5, help="Probe indices 0 through N (default: 5)")
    parser.add_argument("--frames", type=int, default=10, help="Frames to read from each camera (default: 10)")
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="auto",
                        help="Windows capture backend to try (default: auto)")
    args = parser.parse_args()
    if not 0 <= args.max_index <= 20 or not 1 <= args.frames <= 100:
        parser.error("Use --max-index 0..20 and --frames 1..100")

    try:
        import cv2
    except ImportError as exc:
        parser.error(f"Install OpenCV in the demo environment first: {exc}")

    backends = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
    found = 0
    for index in range(args.max_index + 1):
        capture = cv2.VideoCapture(index, backends[args.backend])
        try:
            if not capture.isOpened():
                continue
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            started = time.perf_counter()
            count = 0
            shape = None
            for _ in range(args.frames):
                okay, frame = capture.read()
                if not okay or frame is None:
                    break
                count += 1
                shape = frame.shape
            elapsed = time.perf_counter() - started
            if count:
                found += 1
                print(f"Camera {index} ({args.backend}): {shape[1]}x{shape[0]}, "
                      f"{count}/{args.frames} frames, {count / elapsed:.1f} capture FPS")
            else:
                print(f"Camera {index}: opened but no frames received")
        finally:
            capture.release()
    if not found:
        raise SystemExit("No camera delivered frames; check permissions and connected-camera setup.")
    print("Select a working index for later model testing; no frames were saved.")


if __name__ == "__main__":
    main()
