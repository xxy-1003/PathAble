"""Interactively measure intrinsics for one fixed PathAble camera/mount.

Print the checkerboard from the supplied PDF at 100% scale. Press SPACE for
each varied view; Q exits without claiming a calibration.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def board_object_points(columns: int, rows: int, square_mm: float) -> np.ndarray:
    points = np.zeros((columns * rows, 3), dtype=np.float32)
    points[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2)
    points *= square_mm / 1000.0
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "calibration" / "camera.json")
    args = parser.parse_args()
    if not 10 <= args.samples <= 100:
        parser.error("--samples must be 10..100")

    columns, rows, square_mm = 9, 6, 18.0
    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error("Camera could not be opened")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    object_points, image_points = [], []
    previous_corners = None
    frame_size = None
    print("Show the entire printed checkerboard. Move and tilt it between captures.")
    print("Press SPACE to accept a detected view; press Q to quit.")
    try:
        while len(image_points) < args.samples:
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit("Camera stopped delivering frames")
            height, width = frame.shape[:2]
            if frame_size is not None and frame_size != (width, height):
                raise SystemExit("Camera resolution changed during calibration")
            frame_size = (width, height)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCornersSB(gray, (columns, rows))
            preview = frame.copy()
            if found:
                cv2.drawChessboardCorners(preview, (columns, rows), corners, found)
            label = f"Views {len(image_points)}/{args.samples} | {'FOUND' if found else 'NO BOARD'} | SPACE save | Q quit"
            cv2.putText(preview, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.52, (0, 255, 0) if found else (0, 0, 255), 2)
            cv2.imshow("PathAble camera calibration", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                raise SystemExit("Calibration cancelled; no parameters saved")
            if key == ord(" ") and found:
                if previous_corners is not None:
                    displacement = np.mean(np.linalg.norm(corners - previous_corners, axis=2))
                    if displacement < min(width, height) * 0.03:
                        print("Move or tilt the checkerboard more before the next capture.")
                        continue
                object_points.append(board_object_points(columns, rows, square_mm))
                image_points.append(corners.astype(np.float32))
                previous_corners = corners.copy()
                print(f"Accepted view {len(image_points)}/{args.samples}")
    finally:
        capture.release()
        cv2.destroyAllWindows()

    rms, camera_matrix, distortion, _, _ = cv2.calibrateCamera(
        object_points, image_points, frame_size, None, None
    )
    if not np.isfinite(camera_matrix).all() or not np.isfinite(distortion).all():
        raise SystemExit("Calibration returned non-finite parameters")
    if rms > 1.5:
        raise SystemExit(f"Calibration rejected: RMS reprojection error {rms:.3f} px exceeds 1.5 px")
    result = {
        "camera_index": args.camera,
        "backend": args.backend,
        "image_size_px": list(frame_size),
        "checkerboard_inner_corners": [columns, rows],
        "square_size_mm": square_mm,
        "samples": len(image_points),
        "rms_reprojection_px": float(rms),
        "camera_matrix": camera_matrix.tolist(),
        "distortion_coefficients": distortion.ravel().tolist(),
        "verified_print_size": False,
        "mount_description": "",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {args.output}; RMS reprojection error {rms:.3f} px")
    print("Measure the printed square with a ruler and document the camera mount before using distances.")


if __name__ == "__main__":
    main()
