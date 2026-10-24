"""Click floor reference points in a saved frame to read image coordinates."""

import argparse
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f"Could not read image: {args.image}")
    shown = image.copy()

    def click(event, x, y, _flags, _userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            print(f"pixel_x={x}, pixel_y={y}", flush=True)
            cv2.drawMarker(shown, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 16, 2)
            cv2.imshow("PathAble floor pixels", shown)

    cv2.namedWindow("PathAble floor pixels")
    cv2.setMouseCallback("PathAble floor pixels", click)
    print("Click measured floor reference points; copy printed pixel x/y into the CSV. Press Q to close.")
    while True:
        cv2.imshow("PathAble floor pixels", shown)
        key = cv2.waitKey(20) & 0xFF
        if key in (ord("q"), 27):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
