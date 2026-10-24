"""Scripted, offline A-to-D route replay demonstrating PathAble v3 local navigation & voice.

Follows Proposal Sections 5.1, 7.4, 8, and 11:
- Start: Entrance (A) -> Destination: Lab (D)
- Initial planned route: A -> B -> C -> D (39 m)
- Demonstrates all six local decision actions + destination arrival:
    1. CONTINUE (normally silent walking)
    2. STOP_AND_ESCALATE (camera timeout / high priority interrupt)
    3. WAIT_AND_REOBSERVE (low-confidence re-observation & moving person)
    4. REROUTE (confirmed 6-frame full blockage B-C, replans B -> E -> F -> D)
    5. TURN_TO_LOOK (active perception when side clearance is unclear)
    6. STEP_ASIDE (local obstacle avoidance towards clear side)
    7. ARRIVED (destination reached)
- Testable offline voice guidance with prioritization and speech latency tracking.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from local_agent import LocalAgent, Observation, RouteMap
from voice import VoiceGuidance


def run_scripted_demo(voice_mode: str = "auto", verbose: bool = True) -> int:
    map_path = Path(__file__).resolve().parents[1] / "map_graph.json"
    if not map_path.exists():
        print(f"Error: Map file not found at {map_path}", file=sys.stderr)
        return 1

    route_map = RouteMap.from_file(map_path)
    voice = VoiceGuidance(mode=voice_mode, speech_rate=165, cooldown_s=1.5)
    agent = LocalAgent(route_map, start="A", destination="D", voice=voice)

    print("=" * 78)
    print(" PathAble v3: Local Navigation & Voice Decision Trace (Person 1)")
    print(" Route: Entrance (A) -> Lab (D) with Simulated Obstacles")
    print(f" Voice engine mode: {voice.active_mode}")
    print("=" * 78)
    print(f"Initial planned route: {' -> '.join(agent.current_route)} (39 m)\n")

    # Scripted sequence of observations
    # Phase 1: Departure at Entrance A
    scripted_steps: list[dict] = [
        {
            "desc": "Phase 1: User starts at Entrance A; path ahead clear",
            "obs": Observation(0.0, None, 1.0, "clear", "clear", "clear", "far", node="A"),
        },
        {
            "desc": "Walking corridor A -> B; path clear",
            "obs": Observation(0.4, None, 0.95, "clear", "clear", "clear", "far"),
        },
        {
            "desc": "Simulated camera dropout check (>1.0s elapsed)",
            "timeout_probe": 1.5,
        },
        {
            "desc": "Camera recovers; arriving at Junction B",
            "obs": Observation(1.6, None, 0.95, "clear", "clear", "clear", "far", node="B"),
        },
        # Phase 2: Junction B facing Corridor B-C (Uncertain observation -> Full blockage)
        {
            "desc": "Phase 2: Facing corridor B-C: low confidence obstacle seen",
            "obs": Observation(2.0, "chair", 0.48, "unknown", "occupied", "unknown", "medium"),
        },
    ]

    # 6 consecutive frames of full blockage (chairs/tables across corridor)
    for i in range(6):
        t = 2.1 + i * 0.1
        step_desc = (
            f"Frame {i + 1}/6: full blockage confirmed; replanning route"
            if i == 5
            else f"Frame {i + 1}/6: confirming blockage over ring buffer"
        )
        scripted_steps.append({
            "desc": step_desc,
            "obs": Observation(t, "chair", 0.85, "occupied", "occupied", "occupied", "near"),
        })

    # Phase 3: Transition to new corridor B -> E & moving obstacle
    scripted_steps.extend([
        {
            "desc": "Phase 3: User turns towards E; new corridor verified clear",
            "obs": Observation(2.8, None, 0.90, "clear", "clear", "clear", "far"),
        },
        {
            "desc": "Walking towards E: moving person detected in centre path",
            "obs": Observation(3.2, "person", 0.92, "clear", "occupied", "clear", "near", moving=True),
        },
        {
            "desc": "Person has walked past; walking path clear",
            "obs": Observation(3.6, None, 0.90, "clear", "clear", "clear", "far"),
        },
        # Phase 4: Junction E -> Corridor E-F (Active perception & side stepping)
        {
            "desc": "Phase 4: Arrived at Junction E; turn towards F",
            "obs": Observation(4.0, None, 0.95, "clear", "clear", "clear", "far", node="E"),
        },
        {
            "desc": "Corridor E-F: centre occupied, left unknown (turn to look)",
            "obs": Observation(4.4, "box", 0.88, "unknown", "occupied", "occupied", "medium"),
        },
        {
            "desc": "User scanned left: left confirmed clear (step aside)",
            "obs": Observation(4.7, "box", 0.88, "clear", "occupied", "occupied", "near"),
        },
        {
            "desc": "User stepped left; obstacle cleared",
            "obs": Observation(5.1, None, 0.92, "clear", "clear", "clear", "far"),
        },
        # Phase 5: Junction F -> Destination D
        {
            "desc": "Phase 5: Arrived at Junction F; turn towards D",
            "obs": Observation(5.5, None, 0.95, "clear", "clear", "clear", "far", node="F"),
        },
        {
            "desc": "Corridor F-D clear",
            "obs": Observation(6.0, None, 0.95, "clear", "clear", "clear", "far"),
        },
        {
            "desc": "Destination reached: Lab (D)",
            "obs": Observation(6.5, None, 1.0, "clear", "clear", "clear", "far", node="D"),
        },
    ])

    actions_seen: set[str] = set()

    for step in scripted_steps:
        desc = step["desc"]
        if "timeout_probe" in step:
            now = step["timeout_probe"]
            decision = agent.camera_timeout(now)
            if decision:
                actions_seen.add(decision.action)
                spoken = voice.get_last_spoken()
                print(f"[{now:4.1f}s] {decision.action:<18} | {desc}")
                print(f"         Spoken: \"{decision.message}\"")
                print(f"         Route : {' -> '.join(decision.route)}\n")
            continue

        obs_event: Observation = step["obs"]
        decision = agent.observe(obs_event)
        actions_seen.add(decision.action)

        spoken_tag = f"Spoken: \"{decision.message}\"" if decision.message else "(silent)"
        print(f"[{obs_event.timestamp:4.1f}s] {decision.action:<18} | {desc}")
        print(f"         Voice : {spoken_tag}")
        print(f"         Route : {' -> '.join(decision.route)}")

        if decision.action == "REROUTE":
            cloud_event = agent.create_cloud_event(obs_event, decision)
            print(f"         [AWS Event Emitted] id={cloud_event['event_id']}, "
                  f"blocked_edge={cloud_event['edge']}, replanned={cloud_event['route']}")
        print()

    # Wait for any pending speech in the worker queue to drain
    voice.wait_until_done()
    voice.close()

    print("=" * 78)
    print(" Replay Summary & Acceptance Verification:")
    print(f" - Distinct actions demonstrated: {sorted(actions_seen)}")
    expected_actions = {
        "CONTINUE",
        "STOP_AND_ESCALATE",
        "WAIT_AND_REOBSERVE",
        "REROUTE",
        "TURN_TO_LOOK",
        "STEP_ASIDE",
        "ARRIVED",
    }
    missing = expected_actions - actions_seen
    if missing:
        print(f" [FAIL] Missing expected decision actions: {missing}")
        return 1

    print(" - All 6 Proposal decision actions + ARRIVED verified successfully!")
    print(f" - Total voice messages dispatched: {len(voice.get_history())}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PathAble v3 scripted route demo")
    parser.add_argument(
        "--voice-mode",
        choices=["auto", "tts", "mock"],
        default="auto",
        help="Voice engine mode (default: auto, fallback to mock if no audio device)",
    )
    args = parser.parse_args()
    sys.exit(run_scripted_demo(voice_mode=args.voice_mode))
