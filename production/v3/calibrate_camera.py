"""Interactively measure intrinsics for one fixed PathAble camera/mount.

Use the printed checkerboard or a phone showing phone_checkerboard.svg. Press
SPACE for each varied view; Q exits without claiming a calibration.
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


def find_board(gray: np.ndarray, cols: int, rows: int):
    """Detect checkerboard corners trying Sector-Based and standard methods in both orientations."""
    sb_flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE
    std_flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE

    # 1. Sector-Based (9, 6)
    found, corners = cv2.findChessboardCornersSB(gray, (cols, rows), flags=sb_flags)
    if found and corners is not None:
        return True, corners, (cols, rows)

    # 2. Sector-Based (6, 9)
    found, corners = cv2.findChessboardCornersSB(gray, (rows, cols), flags=sb_flags)
    if found and corners is not None:
        return True, corners, (rows, cols)

    # 3. Standard adaptive threshold (9, 6)
    found, corners = cv2.findChessboardCorners(gray, (cols, rows), flags=std_flags)
    if found and corners is not None:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        return True, corners, (cols, rows)

    # 4. Standard adaptive threshold (6, 9)
    found, corners = cv2.findChessboardCorners(gray, (rows, cols), flags=std_flags)
    if found and corners is not None:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        return True, corners, (rows, cols)

    return False, None, (cols, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--target", choices=("printed_board", "phone_screen"),
                        default="printed_board")
    parser.add_argument("--square-mm", type=float,
                        help="Ruler-measured side of one displayed square in millimetres")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "calibration" / "camera.json")
    args = parser.parse_args()
    if not 10 <= args.samples <= 100:
        parser.error("--samples must be 10..100")
    if args.target == "phone_screen" and args.square_mm is None:
        parser.error("Phone screen requires --square-mm measured on the phone with a ruler")
    square_mm = 18.0 if args.square_mm is None else args.square_mm
    if not np.isfinite(square_mm) or square_mm <= 0:
        parser.error("--square-mm must be a positive measured value")

    columns, rows = 9, 6
    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error("Camera could not be opened")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    object_points, image_points = [], []
    previous_corners = None
    frame_size = None
    print("Show the entire checkerboard and white margin. Move and tilt it between captures.")
    if args.target == "phone_screen":
        print("Tip: Keep phone brightness around 30-50% to prevent camera glare.")
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
            found, corners, grid_dims = find_board(gray, columns, rows)
            preview = frame.copy()
            if found and corners is not None:
                cv2.drawChessboardCorners(preview, grid_dims, corners, found)
            label = f"Views {len(image_points)}/{args.samples} | {'FOUND' if found else 'NO BOARD'} | SPACE save | Q quit"
            cv2.putText(preview, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.52, (0, 255, 0) if found else (0, 0, 255), 2)
            cv2.imshow("PathAble camera calibration", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                raise SystemExit("Calibration cancelled; no parameters saved")
            if key == ord(" ") and found and corners is not None:
                if previous_corners is not None and previous_corners.shape == corners.shape:
                    displacement = np.mean(np.linalg.norm(corners - previous_corners, axis=2))
                    if displacement < min(width, height) * 0.03:
                        print("Move or tilt the checkerboard more before the next capture.")
                        continue
                object_points.append(board_object_points(grid_dims[0], grid_dims[1], square_mm))
                image_points.append(corners.astype(np.float32))
                previous_corners = corners.copy()
                print(f"Accepted view {len(image_points)}/{args.samples} ({grid_dims[0]}x{grid_dims[1]})")
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
        "calibration_method": "opencv_checkerboard",
        "camera_index": args.camera,
        "backend": args.backend,
        "image_size_px": list(frame_size),
        "checkerboard_inner_corners": [columns, rows],
        "square_size_mm": square_mm,
        "calibration_target": args.target,
        "samples": len(image_points),
        "rms_reprojection_px": float(rms),
        "camera_matrix": camera_matrix.tolist(),
        "distortion_coefficients": distortion.ravel().tolist(),
        "verified_target_size": False,
        "mount_description": "",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {args.output}; RMS reprojection error {rms:.3f} px")
    print("Verify the target square size with a ruler and document the camera mount before using distances.")


if __name__ == "__main__":
    main()
