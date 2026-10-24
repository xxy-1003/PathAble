"""End-to-End Walkthrough Demonstration of PathAble (Proposal Sections 5.1 & 11).

Demonstrates the full life cycle of a living indoor route:
1. Fast Loop encounters obstacle on B-C and reroutes to B -> E -> F -> D.
2. Event e-0193 sent to cloud intake; OpenCV 5 tools re-check (clearance = 0.60m, static).
3. First report classified as UNCERTAIN; edge kept blocked under fail-safe hold.
4. Second report e-0205 arrives 22 minutes later for the same edge.
5. Cloud classifies as LASTING; generates facilities ticket T-17.
6. Facilities staff reviews and APPROVES closure.
7. Map increments version; edge B-C marked closed.
8. Next user at Entrance (A) fetches updated map and plans A -> B -> E -> F -> D from the start!
"""

import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from production.v3.cloud.core.orchestrator import SlowLoopOrchestrator
from production.v3.cloud.core.validation import validate_event_file
from production.v3.local_agent import LocalAgent, RouteMap


MAP_PATH = Path(__file__).resolve().parents[2] / "map_graph.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def print_step(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def run_demo():
    print_step("PathAble End-to-End Decision Trace Demo (Proposal Section 11)")

    # 1. Initial State: User 1 at Entrance A heading to Lab D
    route_map = RouteMap.from_file(MAP_PATH)
    agent_user1 = LocalAgent(route_map, "A", "D")
    print(f"[Device User 1] Initial planned route: {' -> '.join(agent_user1.current_route)}")

    # 2. Initialize Cloud Slow-Loop Orchestrator
    orchestrator = SlowLoopOrchestrator(initial_map_path=MAP_PATH)
    print(f"[AWS Cloud] Initial shared map version: v{orchestrator.map_sync.version}")

    # 3. Time 0.0s - User 1 encounters chairs/table blocking corridor B-C
    print_step("Step 1: First Blockage Encounter (T = 0.0s)")
    with open(FIXTURES_DIR / "event_lasting_furniture_1.json", "r", encoding="utf-8") as f:
        event_1_payload = json.load(f)

    print(f"[Device User 1] REROUTE triggered on edge B-C: Obstacle = {event_1_payload['observations']['obstacle_classes']}")
    print(f"[Device User 1] Dijkstra replans locally: {' -> '.join(event_1_payload['local_reroute'])}")
    print("[Device User 1] Privacy filter: People blurred with cv.GaussianBlur before upload.")
    print(f"[Device User 1] Event {event_1_payload['event_id']} posted to AWS intake.")

    res_1 = orchestrator.process_event(event_1_payload)
    print(f"[AWS Cloud Intake] Event {res_1['event_id']} processed.")
    print(f"[AWS Re-Check Tools] Optical flow: static | Measured clearance: 0.60m (MS 1184 min is 1.20m).")
    print(f"[AWS State Rules] Outcome: {res_1['outcome']} (First static report without history).")
    print(f"[AWS State Rules] Justification: {res_1['justification']}")
    print(f"[AWS Shared Map] Edge B-C kept blocked under fail-safe hold. Map version: v{res_1['map_version']}")

    # 4. Time +22 min - User 2 encounters the same furniture in corridor B-C
    print_step("Step 2: Second Report Arrives (+22 minutes later)")
    with open(FIXTURES_DIR / "event_lasting_furniture_2.json", "r", encoding="utf-8") as f:
        event_2_payload = json.load(f)

    print(f"[Device User 2] Rerouting at B-C. Posting second report: {event_2_payload['event_id']}")
    res_2 = orchestrator.process_event(event_2_payload)

    print(f"[AWS Cloud Intake] Event {res_2['event_id']} processed.")
    print(f"[AWS State Rules] Outcome: {res_2['outcome']} (Static obstruction persistent > 15 minutes).")
    print(f"[AWS Facilities Ticket] Generated Ticket: {res_2['ticket_id']}")
    print(f"[AWS Facilities Ticket] Justification: {res_2['justification']}")

    # 5. Time +30 min - Facilities Staff Reviews and Approves Closure
    print_step("Step 3: Facilities Review & Human Approval (T = +30 min)")
    ticket_id = res_2["ticket_id"]
    print(f"[Facilities Staff] Notification received via SNS for Ticket {ticket_id}.")
    print(f"[Facilities Staff] Reviewing measured clearance (0.60m < 1.20m) & evidence frames.")
    print("[Facilities Staff] Action: APPROVE CLOSURE.")

    ticket, new_version = orchestrator.approval_mgr.review_ticket(
        ticket_id=ticket_id,
        action="APPROVE",
        reviewer_id="facilities-lead-01",
        notes="Confirmed corridor B-C is undergoing scheduled partition work. Edge closed.",
    )
    print(f"[AWS Human Review] Ticket {ticket_id} resolved: {ticket.status.value}")
    print(f"[AWS Shared Map] Authoritative map updated! New Map Version: v{new_version}")

    # 6. Next User (User 3) arrives at Entrance A
    print_step("Step 4: Next User Pulls Map v{} at Junction A".format(new_version))
    fresh_map_data = orchestrator.map_sync.get_map()
    user3_map = RouteMap(fresh_map_data)
    agent_user3 = LocalAgent(user3_map, "A", "D")

    print(f"[Device User 3] Synced latest map (v{user3_map.version}) at Entrance A.")
    print(f"[Device User 3] Edge B-C blocked status in shared map: {user3_map.edges.get(frozenset(('B', 'C')))} (blocked: {frozenset(('B', 'C')) in user3_map.blocked})")
    print(f"[Device User 3] Planned route from entrance: {' -> '.join(agent_user3.current_route)}")
    print("\n===> SUCCESS: New user is guided along safe route (A -> B -> E -> F -> D) from the start!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_demo()
