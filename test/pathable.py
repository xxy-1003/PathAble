
import os
import time
import queue
import threading

import cv2
import numpy as np
import pyttsx3
from ultralytics import YOLO


# ============================================================
# PATHABLE - OFFLINE-FIRST COMPUTER VISION PROTOTYPE
# Camera: Windows webcam
# Detection: YOLO11 Nano
# Image processing: OpenCV
# Speech: Local text-to-speech
# ============================================================

APP_NAME = "PathAble"

# YOLO model. The first run requires internet to download it.
# Later runs can use the locally cached model offline.
MODEL_NAME = "yolo11n.pt"

CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
CONFIDENCE_THRESHOLD = 0.40

# Demo-only alert thresholds. These are NOT calibrated distances.
MIN_BOX_AREA_RATIO = 0.035
LOWER_FRAME_RATIO = 0.48
SPEECH_COOLDOWN_SECONDS = 3.0

# Set to True to enable spoken demo warnings.
ENABLE_SPEECH = True

# Avoid automatic telemetry/update checks during normal operation.
os.environ["YOLO_VERBOSE"] = "False"


# ============================================================
# SPEECH WORKER
# Keep speech processing off the camera-processing thread.
# ============================================================

speech_queue = queue.Queue(maxsize=1)


def speech_worker():
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.setProperty("volume", 1.0)
    except Exception as exc:
        print(f"[Speech] Could not initialise speech engine: {exc}")
        return

    while True:
        message = speech_queue.get()

        if message is None:
            break

        try:
            engine.say(message)
            engine.runAndWait()
        except Exception as exc:
            print(f"[Speech] Error: {exc}")

    engine.stop()


def announce(message):
    """Queue a spoken message without blocking video processing."""
    if not ENABLE_SPEECH:
        return

    # Keep only the newest pending message.
    try:
        while True:
            speech_queue.get_nowait()
    except queue.Empty:
        pass

    try:
        speech_queue.put_nowait(message)
    except queue.Full:
        pass


# ============================================================
# OBJECT DETECTION
# ============================================================

def get_position(center_x, frame_width):
    """Return approximate horizontal image position."""
    ratio = center_x / frame_width

    if ratio < 0.38:
        return "LEFT"
    elif ratio > 0.62:
        return "RIGHT"
    return "CENTER"


def box_area_ratio(x1, y1, x2, y2, frame_width, frame_height):
    """Calculate the fraction of the image covered by a bounding box."""
    box_area = max(0, x2 - x1) * max(0, y2 - y1)
    frame_area = frame_width * frame_height

    if frame_area == 0:
        return 0.0

    return box_area / frame_area


def is_demo_hazard(x1, y1, x2, y2, frame_width, frame_height):
    """
    Heuristic for a possible obstacle in the lower central image.

    This is not real depth estimation or validated collision prediction.
    """
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2

    horizontal_ratio = center_x / frame_width
    vertical_ratio = center_y / frame_height

    area_ratio = box_area_ratio(
        x1, y1, x2, y2, frame_width, frame_height
    )

    in_central_path = 0.30 <= horizontal_ratio <= 0.70
    in_lower_image = vertical_ratio >= LOWER_FRAME_RATIO
    large_enough = area_ratio >= MIN_BOX_AREA_RATIO

    return in_central_path and in_lower_image and large_enough


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    print("=" * 55)
    print(f"{APP_NAME} - Offline Vision Prototype")
    print("=" * 55)

    print("\nLoading AI model...")

    try:
        model = YOLO(MODEL_NAME)
    except Exception as exc:
        print("\nCould not load the YOLO model.")
        print("Check your internet connection on the first run,")
        print("or verify that the model file is available locally.")
        print(f"\nDetails: {exc}")
        return

    print("Model loaded successfully.")

    print("\nOpening camera...")

    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        print("ERROR: Could not open your webcam.")
        print("Try CAMERA_INDEX = 1 if you have another camera.")
        return

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    # Start local speech processing.
    speaker_thread = None

    if ENABLE_SPEECH:
        speaker_thread = threading.Thread(
            target=speech_worker,
            daemon=True
        )
        speaker_thread.start()

    last_alert_time = {}
    fps = 0.0
    previous_time = time.time()

    print("\nPathAble is running.")
    print("Press Q or ESC in the video window to quit.\n")

    try:
        while True:
            success, frame = camera.read()

            if not success:
                print("Unable to read a frame from the camera.")
                break

            frame_height, frame_width = frame.shape[:2]

            # Run object detection on the current frame.
            results = model.predict(
                source=frame,
                conf=CONFIDENCE_THRESHOLD,
                imgsz=640,
                verbose=False
            )

            possible_hazards = []
            detected_objects = []

            for result in results:
                if result.boxes is None:
                    continue

                for box in result.boxes:
                    x1, y1, x2, y2 = map(
                        int, box.xyxy[0].tolist()
                    )

                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    object_name = model.names[class_id]

                    position = get_position(
                        (x1 + x2) / 2,
                        frame_width
                    )

                    detected_objects.append(
                        (object_name, confidence, position)
                    )

                    hazard = is_demo_hazard(
                        x1, y1, x2, y2,
                        frame_width, frame_height
                    )

                    # Draw the detection.
                    box_color = (
                        (0, 0, 255) if hazard else (0, 220, 0)
                    )

                    cv2.rectangle(
                        frame,
                        (x1, y1),
                        (x2, y2),
                        box_color,
                        2
                    )

                    label = (
                        f"{object_name} {confidence:.0%} "
                        f"| {position}"
                    )

                    cv2.putText(
                        frame,
                        label,
                        (x1, max(25, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        box_color,
                        2,
                        cv2.LINE_AA
                    )

                    if hazard:
                        possible_hazards.append(
                            (object_name, position)
                        )

            # ------------------------------------------------
            # DEMO WARNING LOGIC
            # This only flags some visible objects based on
            # image position and box size.
            # It cannot determine whether the path is safe.
            # ------------------------------------------------

            now = time.time()

            for object_name, position in possible_hazards:
                alert_key = (object_name, position)
                previous_alert = last_alert_time.get(
                    alert_key, 0
                )

                if now - previous_alert >= SPEECH_COOLDOWN_SECONDS:
                    message = (
                        f"Possible obstacle {position.lower()}: "
                        f"{object_name}"
                    )

                    print(f"[WARNING] {message}")
                    announce(message)
                    last_alert_time[alert_key] = now

            # Calculate FPS.
            current_time = time.time()
            delta = current_time - previous_time

            if delta > 0:
                instant_fps = 1.0 / delta
                fps = (
                    instant_fps if fps == 0
                    else 0.9 * fps + 0.1 * instant_fps
                )

            previous_time = current_time

            # Draw directional zones.
            left_boundary = int(frame_width * 0.38)
            right_boundary = int(frame_width * 0.62)

            cv2.line(
                frame,
                (left_boundary, 0),
                (left_boundary, frame_height),
                (255, 180, 0),
                1
            )

            cv2.line(
                frame,
                (right_boundary, 0),
                (right_boundary, frame_height),
                (255, 180, 0),
                1
            )

            # Status panel.
            cv2.rectangle(
                frame,
                (0, 0),
                (frame_width, 75),
                (25, 25, 25),
                -1
            )

            cv2.putText(
                frame,
                "PATHABLE | OFFLINE VISION PROTOTYPE",
                (15, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2
            )

            cv2.putText(
                frame,
                f"FPS: {fps:.1f} | Objects: "
                f"{len(detected_objects)}",
                (15, 57),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (180, 255, 180),
                2
            )

            # Warning banner.
            if possible_hazards:
                cv2.rectangle(
                    frame,
                    (0, frame_height - 48),
                    (frame_width, frame_height),
                    (0, 0, 180),
                    -1
                )

                cv2.putText(
                    frame,
                    "POSSIBLE OBSTACLE - CHECK YOUR SURROUNDINGS",
                    (15, frame_height - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

            cv2.imshow(APP_NAME, frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

    except KeyboardInterrupt:
        print("\nStopping PathAble...")

    finally:
        camera.release()
        cv2.destroyAllWindows()

        if ENABLE_SPEECH:
            try:
                speech_queue.put_nowait(None)
            except queue.Full:
                pass

        print("PathAble stopped.")


if __name__ == "__main__":
    main()
