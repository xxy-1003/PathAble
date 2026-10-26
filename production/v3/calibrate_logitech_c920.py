"""Validate an existing measured C920 calibration; never generate lens defaults."""

import argparse
from pathlib import Path

from calibrated_observation import FloorProjector


def generate_c920_calibration(*args, **kwargs):
    """Compatibility guard for older callers of the removed placeholder generator."""
    raise ValueError("Calibration cannot be generated from a camera model name. "
                     "Run calibrate_camera.py with a measured checkerboard and "
                     "calibrate_floor.py with surveyed floor points.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-json", type=Path, default=Path(__file__).parent / "calibration/camera.json")
    parser.add_argument("--floor-json", type=Path, default=Path(__file__).parent / "calibration/floor.json")
    args = parser.parse_args()
    projector = FloorProjector(args.camera_json, args.floor_json)
    if not projector.ready:
        parser.error("Measured calibration is missing or unverified. Run calibrate_camera.py "
                     "and calibrate_floor.py, then verify target size, surveyed axes, and fixed mount.")
    print("Measured calibration files pass the format and integrity checks. "
          "Confirm the same physical camera pose separately before using distances.")


if __name__ == "__main__":
    main()
