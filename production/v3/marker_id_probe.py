"""Show ArUco IDs from the webcam without camera calibration or saved frames.

Use a phone screen to test ID recognition before printing physical markers.
This does not measure marker pose, direction, or distance.
"""

import argparse

import cv2


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def detect_ids(frame, detector) -> tuple[list[int], object]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    return ([] if ids is None else [int(value) for value in ids.flatten()]), corners


def main() -> None:
    parser = argparse.ArgumentParser(description="Recognize PathAble ArUco marker IDs without calibration")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="dshow")
    args = parser.parse_args()
    if args.camera < 0:
        parser.error("--camera must be zero or greater")

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary)
    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        parser.error("Camera could not be opened. Close Windows Camera, then try another backend or index.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print("Hold the phone marker in view with the whole black square and white margin visible.")
    print("A green 'ID 0 detected' label means this recognition test passed. Press Q to quit.")
    previous_ids = None
    try:
        while True:
            okay, frame = capture.read()
            if not okay or frame is None:
                raise SystemExit("Camera stopped delivering frames")
            ids, corners = detect_ids(frame, detector)
            if ids != previous_ids:
                print(f"Detected IDs: {ids if ids else 'none'}")
                previous_ids = ids
            if ids:
                cv2.aruco.drawDetectedMarkers(frame, corners)
            found_zero = 0 in ids
            label = "ID 0 detected" if found_zero else "Show marker ID 0 | Q to quit"
            color = (0, 180, 0) if found_zero else (0, 0, 220)
            cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("PathAble marker ID test", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()
    print("ID recognition only; physical size and distance remain unverified.")


if __name__ == "__main__":
    main()
