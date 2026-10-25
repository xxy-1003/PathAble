"""Live PathAble navigation bridge connecting webcam and ArUco markers to the local agent.

Captures from the Logitech C920 webcam at 640x480, extracts YOLO11n-seg obstacle
masks and ArUco junction nodes (A-F), synthesizes Observation objects, and feeds
them directly into LocalAgent's deterministic decision engine.

Demonstrates:
  1. Junction localization via ArUco markers (Nodes A-F).
  2. Conservative unknown zones where free-space evidence is unavailable.
  3. Obstacle avoidance (STEP_ASIDE) and blockage rerouting (REROUTE).
"""

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

from calibrated_observation import PerceptionPipeline
from local_agent import LocalAgent, RouteMap
from voice import VoiceGuidance
from manual_route_demo import ManualRouteDemo
from camera_region_demo import ChairRegionMonitor


BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


def draw_hud(frame: np.ndarray, obs, decision, agent: LocalAgent, pipeline: PerceptionPipeline) -> np.ndarray:
    """Render heads-up display overlaying perception zones, detected obstacles, and agent decisions."""
    h, w = frame.shape[:2]
    overlay = frame.copy()

    # Draw lower 60% floor zones (Left: 0-30%, Centre: 30-70%, Right: 70-100%)
    floor_top = int(h * 0.4)
    x_left = int(w * 0.3)
    x_right = int(w * 0.7)

    zone_colors = {
        "occupied": (0, 0, 220),  # Red
        "clear": (0, 200, 0),     # Green
        "unknown": (0, 165, 255), # Orange
    }

    # Left zone
    cv2.rectangle(overlay, (0, floor_top), (x_left, h), zone_colors.get(obs.left, (100, 100, 100)), 2)
    # Centre walking zone
    cv2.rectangle(overlay, (x_left, floor_top), (x_right, h), zone_colors.get(obs.centre, (100, 100, 100)), 3)
    # Right zone
    cv2.rectangle(overlay, (x_right, floor_top), (w, h), zone_colors.get(obs.right, (100, 100, 100)), 2)

    # Draw detected obstacle boxes and contact points
    if pipeline.last_vision_result and pipeline.last_vision_result.obstacles:
        for item in pipeline.last_vision_result.obstacles:
            x1, y1, x2, y2 = item.box
            box_col = (0, 0, 255) if item.coverage[1] >= 0.15 else (0, 200, 255)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), box_col, 2)
            label = f"{item.name} {item.confidence:.2f}"
            if item.name == "chair" and item.contact is None:
                label += " | floor contact unknown"
            cv2.putText(overlay, label,
                        (x1, max(y1 - 6, 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, box_col, 2)
            if item.contact is not None:
                cv2.circle(overlay, item.contact, 6, (0, 255, 0), -1)

    # Top HUD banner
    cv2.rectangle(overlay, (0, 0), (w, 80), (25, 25, 25), -1)

    # Status text
    route_str = " -> ".join(decision.route) if decision.route else "No route"
    node_str = f"Junction: {obs.node or agent.current_node}"
    cv2.putText(overlay, f"PathAble Navigation | {node_str}", (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(overlay, f"Route: {route_str}", (10, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 200, 200), 1)

    # Action badge
    action_color = (0, 220, 0) if decision.action == "CONTINUE" else (
        (0, 0, 255) if "STOP" in decision.action or "REROUTE" in decision.action else (0, 200, 255)
    )
    cv2.putText(overlay, f"ACTION: {decision.action}", (10, 68),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, action_color, 2)

    if decision.message:
        cv2.putText(overlay, decision.message, (w // 2 - 40, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

    # Zone labels at bottom
    cv2.putText(overlay, f"L: {obs.left}", (15, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, zone_colors.get(obs.left, (255, 255, 255)), 1)
    cv2.putText(overlay, f"WALKING PATH: {obs.centre} (dist: {obs.distance})", (x_left + 10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, zone_colors.get(obs.centre, (255, 255, 255)), 2)
    cv2.putText(overlay, f"R: {obs.right}", (x_right + 15, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, zone_colors.get(obs.right, (255, 255, 255)), 1)

    return overlay


def main() -> None:
    parser = argparse.ArgumentParser(description="Live camera + ArUco navigation agent")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0 for Logitech C920)")
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="dshow")
    parser.add_argument("--start", type=str, default="A", help="Start node (default: A)")
    parser.add_argument("--dest", type=str, default="D", help="Destination node (default: D)")
    parser.add_argument("--map", type=Path, default=Path(__file__).resolve().parents[1] / "map_graph.json")
    parser.add_argument("--model", type=Path, default=Path(__file__).parent / "models" / "yolo11n-seg.onnx")
    parser.add_argument("--camera-json", type=Path, default=Path(__file__).parent / "calibration" / "camera.json")
    parser.add_argument("--floor-json", type=Path, default=Path(__file__).parent / "calibration" / "floor.json")
    parser.add_argument("--same-pose-verified", action="store_true",
                        help="Confirm the fixed camera pose matches the surveyed floor calibration")
    parser.add_argument("--voice-mode", choices=("auto", "tts", "mock"), default="auto")
    parser.add_argument("--manual-route-demo", action="store_true",
                        help="Operator assigns junction B; press B to confirm B-C blocked and propose a route")
    parser.add_argument("--camera-route-demo", action="store_true",
                        help="Fixed-view chair overlap automatically proposes a demo route; not physical blockage verification")
    args = parser.parse_args()
    if args.manual_route_demo and args.camera_route_demo:
        parser.error("Choose either manual or camera route demo")
    if (args.manual_route_demo or args.camera_route_demo) and (args.start != "B" or args.dest != "D"):
        parser.error("Use --start B --dest D with route demos")

    # Check for model file
    if not args.model.is_file():
        print("=" * 70)
        print("WARNING: YOLO11n-seg ONNX model was not found at:")
        print(f"  {args.model}")
        print("Obstacle neural network detection is inactive until the model is downloaded!")
        print("To download the official model, run in PowerShell:")
        print("  .\\download_model.ps1")
        print("=" * 70)
    else:
        print(f"Loaded YOLO11n-seg model: {args.model}")

    if not args.map.is_file():
        parser.error(f"Map graph not found: {args.map}")

    route_map = RouteMap.from_file(args.map)
    voice = VoiceGuidance(mode=args.voice_mode)
    agent = LocalAgent(route_map, args.start, args.dest, voice=voice)
    # A separate graph prevents manual demo confirmations becoming sensor evidence.
    manual_demo = (ManualRouteDemo(RouteMap.from_file(args.map), voice)
                   if args.manual_route_demo or args.camera_route_demo else None)
    monitor = ChairRegionMonitor() if args.camera_route_demo else None
    monitor_status = None
    trial_dir = None
    print(f"Voice mode: {voice.active_mode}; timing records cover queue dispatch only.")
    print(f"PathAble Agent Initialized: {args.start} -> {args.dest}")
    print(f"Initial Route: {' -> '.join(agent.current_route)}")

    # A live camera feed does not establish verified pose or free space by itself.
    pipeline = PerceptionPipeline(
        model_path=args.model if args.model.is_file() else None,
        camera_path=args.camera_json if args.camera_json.is_file() else None,
        floor_path=args.floor_json if args.floor_json.is_file() else None,
        same_pose_verified=args.same_pose_verified,
    )
    if not pipeline.projector.ready or not args.same_pose_verified:
        print("Measured calibration / matching fixed pose unverified: distances remain unknown.")
    print("No detection leaves free space unknown; this viewer does not validate walking safety.")
    if args.manual_route_demo:
        print("MANUAL DEMO: junction B is operator-assigned, not camera-localised.")
        print("Press B in the camera window to confirm B-C blocked. Alternative route is a map proposal only.")
    if monitor:
        trial_dir = Path(__file__).parent / "calibration" / "camera_route_trials" / str(time.time_ns())
        trial_dir.mkdir(parents=True)
        print(f"CAMERA REGION DEMO: central blue rectangle represents B-C. Logs: {trial_dir}")
        print("Junction B is operator-assigned. Chair overlap is a demo trigger, not measured corridor clearance.")

    capture = cv2.VideoCapture(args.camera, BACKENDS[args.backend])
    if not capture.isOpened():
        voice.close()
        parser.error(f"Cannot open camera index {args.camera}")

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("\nStarting live navigation loop. Press Q to exit.")
    print("Hold up ArUco markers 0-5 on your phone screen to simulate arriving at junctions A-F.")
    last_action = None
    try:
        while True:
            t_now = time.time()
            okay, frame = capture.read()
            if not okay or frame is None:
                decision = agent.camera_timeout(t_now)
                if decision:
                    print(f"TIMEOUT: {decision.action} - {decision.message}")
                break

            # Process frame into conservative Observation
            obs = pipeline.process_frame(frame, t_now)

            # Pass Observation to LocalAgent
            decision = agent.observe(obs)
            if monitor:
                monitor_status = monitor.update(pipeline.last_vision_result, t_now,
                                                (frame.shape[1], frame.shape[0]))
                if monitor_status['trigger'] and not manual_demo.confirmed:
                    manual_demo.propose_from_camera(monitor_status)
                    cv2.imwrite(str(trial_dir / 'trigger.png'), frame)
                    print("CAMERA DEMO TRIGGER: " + json.dumps(manual_demo.last_event))
                with (trial_dir / 'observations.jsonl').open('a', encoding='utf-8') as log:
                    log.write(json.dumps(dict(timestamp=t_now, mode='camera_region_demo',
                        evidence=monitor_status, proposed_route=list(manual_demo.route),
                        triggered=manual_demo.confirmed)) + '\n')

            # Print state changes
            if decision.action != last_action or obs.node is not None:
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"Node: {obs.node or agent.current_node:1s} | "
                    f"Action: {decision.action:18s} | "
                    f"Centre: {obs.centre:8s} | "
                    f"Route: {' -> '.join(decision.route)}"
                )
                last_action = decision.action

            # Display GUI
            hud_frame = draw_hud(frame, obs, decision, agent, pipeline)
            if monitor:
                x1, y1, x2, y2 = monitor.pixel_region((frame.shape[1], frame.shape[0]))
                cv2.rectangle(hud_frame, (x1, y1), (x2, y2), (255, 200, 0), 3)
                cv2.putText(hud_frame, 'B-C DEMO REGION', (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1)
            if manual_demo:
                panel = np.zeros((122, hud_frame.shape[1], 3), dtype=np.uint8)
                playback = voice.get_playback_status()
                lines = [
                    "MANUAL DEMO | Assigned B | B: block | R: repeat route | Q: exit",
                    "B-C manually confirmed BLOCKED" if manual_demo.confirmed
                    else "After checking the camera view, press B to confirm B-C blocked",
                    "Proposed route: " + (" -> ".join(manual_demo.route) or "NONE"),
                    "Camera status above remains separate; alternative path is unverified.",
                    f"Voice: {playback['mode']} | {playback['state']} (backend status)",
                ]
                if monitor:
                    lines[0] = "CAMERA REGION DEMO | Assigned B | R: repeat route | Q: exit"
                    lines[1] = ("DEMO TRIGGERED by repeated chair overlap" if manual_demo.confirmed
                                else f"Monitoring chair overlap: {monitor_status['positive_frames']} positive frames")
                for index, line in enumerate(lines):
                    cv2.putText(panel, line, (8, 20 + index * 23),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                hud_frame = np.vstack([hud_frame, panel])
            cv2.imshow("PathAble Live Navigation", hud_frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("b"), ord("B")) and args.manual_route_demo:
                if manual_demo.confirm_blocked():
                    print("MANUAL CONFIRMATION: " + json.dumps(manual_demo.last_event))
                else:
                    print("B-C is already manually confirmed blocked; no repeat speech.")
            if key in (ord("r"), ord("R")) and manual_demo:
                if manual_demo.repeat_announcement():
                    print("REPLAY ROUTE: " + manual_demo.announcement)
                    print("VOICE STATUS: " + json.dumps(voice.get_playback_status()))
                else:
                    print("No proposed reroute to repeat yet.")
    finally:
        capture.release()
        cv2.destroyAllWindows()
        voice.close()
    print("Navigation session closed.")


if __name__ == "__main__":
    main()
