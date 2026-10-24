"""Capture one people-free reference frame after fixing the camera mount."""

import argparse
from pathlib import Path

import cv2


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "calibration" / "floor_frame.png")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Will not overwrite existing reference frame: {args.output}")
    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error("Camera could not be opened")
    print("Place visible floor reference points and make sure no people are in the frame.")
    print("Press SPACE to capture one frame; Q cancels.")
    try:
        while True:
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit("Camera stopped delivering frames")
            preview = frame.copy()
            cv2.putText(preview, "SPACE: save people-free floor frame | Q: cancel", (10, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.imshow("PathAble floor reference", preview)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                args.output.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(args.output), frame):
                    raise SystemExit("Could not save frame")
                print(f"Saved {args.output} at {frame.shape[1]}x{frame.shape[0]}")
                break
            if key in (ord("q"), 27):
                raise SystemExit("No frame saved")
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
