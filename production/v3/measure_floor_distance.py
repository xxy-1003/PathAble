"""Manually check fixed-camera ground distances; no object detector is required."""

import argparse
from pathlib import Path

import cv2
import numpy as np

from calibrated_observation import FloorProjector


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
WINDOW = "PathAble floor distance - centimetres"


def measure(projector, point, frame):
    height, width = frame.shape[:2]
    distance = projector.distance_metres(point, (width, height), same_pose_verified=True)
    return ("Unknown: outside calibrated area or resolution mismatch" if distance is None
            else f"O to clicked floor point: {distance * 100:.1f} cm")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=1)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    parser.add_argument("--camera-json", type=Path, default=Path(__file__).parent / "calibration/camera.json")
    parser.add_argument("--floor-json", type=Path, default=Path(__file__).parent / "calibration/floor.json")
    parser.add_argument("--same-pose-verified", action="store_true",
                        help="Confirm camera position, angle and framing match the calibration photo")
    parser.add_argument("--image", type=Path, help="Check a saved image instead of opening the camera")
    parser.add_argument("--point", type=int, nargs=2, metavar=("X", "Y"),
                        help="With --image, print one measurement without opening a window")
    args = parser.parse_args()
    if not args.same_pose_verified:
        parser.error("Confirm the unchanged camera pose using --same-pose-verified")
    if args.point is not None and args.image is None:
        parser.error("--point requires --image")
    projector = FloorProjector(args.camera_json, args.floor_json)
    if not projector.ready:
        parser.error("Floor calibration is missing or unverified; complete calibration first")

    capture = None
    frozen = None
    if args.image:
        frozen = cv2.imread(str(args.image))
        if frozen is None:
            parser.error(f"Could not read image: {args.image}")
        if args.point is not None:
            print(measure(projector, tuple(args.point), frozen))
            return
    else:
        capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
        if not capture.isOpened():
            capture.release()
            parser.error(f"Could not open camera {args.camera}; close other camera windows first")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, projector.image_size[0])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, projector.image_size[1])

    clicked = None
    message = "SPACE: freeze, then click a point on the FLOOR"

    def click(event, x, y, _flags, _userdata):
        nonlocal clicked, message
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if frozen is None:
            message = "Press SPACE to freeze before clicking"
            return
        clicked = (x, y)
        message = measure(projector, clicked, frozen)
        print(f"Pixel ({x}, {y}): {message}", flush=True)

    print("Keep camera fixed. Compare A-H positions with the reference photo before measuring.")
    print("SPACE freezes/resumes. Click J first: ruler O-J = 9.5 cm in this setup.")
    print("For the calculator case, click the FLOOR beside its bottom edge, not its raised top.")
    print("Distance is along the floor from O, not from the elevated camera lens. Q exits.")
    try:
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW, click)
        while True:
            if frozen is None:
                okay, frame = capture.read()
                if not okay or frame is None:
                    raise SystemExit("Camera stopped delivering frames")
            else:
                frame = frozen
            shown = frame.copy()
            if clicked is not None:
                cv2.drawMarker(shown, clicked, (0, 255, 255), cv2.MARKER_CROSS, 16, 2)
            banner = np.zeros((78, shown.shape[1], 3), dtype=np.uint8)
            for i, text in enumerate([
                    "FROZEN: click floor | SPACE: resume | Q: exit" if frozen is not None
                    else "LIVE | SPACE: freeze | Q: exit",
                    message, "Approximate floor distance from O; marked area only"]):
                cv2.putText(banner, text, (8, 20 + i * 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (0, 255, 255), 1, cv2.LINE_AA)
            # Put controls BELOW the image so mouse coordinates remain image coordinates.
            cv2.imshow(WINDOW, np.vstack([shown, banner]))
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord(" ") and not args.image:
                frozen = frame.copy() if frozen is None else None
                clicked = None
                message = "Click a floor point" if frozen is not None else "SPACE: freeze, then click"
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
