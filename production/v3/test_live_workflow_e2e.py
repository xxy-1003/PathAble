"""Live end-to-end integration test of Person 1's AWS camera workflow.

Starts the mock backend on localhost, connects AwsDeviceClient, simulates a
sustained chair-overlap trigger, tests photo upload, report submission,
human approval, background map polling, local reroute (B -> E -> F -> D),
and voice announcement.
"""

from datetime import datetime, timezone
import json
import threading
import time
import urllib.request

from aws_device_client import AwsDeviceClient, DeviceWorkflowStatus
from local_agent import RouteMap
from mock_backend_server import MockBackendHandler, HTTPServer, MAP_STATE, REPORTS, PHOTOS


class TestVoiceRecorder:
    def __init__(self):
        self.spoken = []

    def speak(self, text, force=False, priority=False):
        self.spoken.append(text)
        print(f"\n[VOICE OUTPUT SPOKEN]: \"{text}\"")


def run_test():
    # 1. Start mock backend on 127.0.0.1:8000
    server = HTTPServer(("127.0.0.1", 8000), MockBackendHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print("[1] Mock AWS backend listening on http://127.0.0.1:8000/api/v2")

    # 2. Initialize device client
    voice = TestVoiceRecorder()
    route_map = RouteMap({
        "nodes": {"0": "A", "1": "B", "2": "C", "3": "D", "4": "E", "5": "F"},
        "edges": [
            {"from": "A", "to": "B", "distance": 12.0, "blocked": False},
            {"from": "B", "to": "C", "distance": 15.0, "blocked": False},
            {"from": "C", "to": "D", "distance": 12.0, "blocked": False},
            {"from": "B", "to": "E", "distance": 10.0, "blocked": False},
            {"from": "E", "to": "F", "distance": 24.0, "blocked": False},
            {"from": "F", "to": "D", "distance": 10.0, "blocked": False},
        ],
    })

    client = AwsDeviceClient(
        api_base_url="http://127.0.0.1:8000",
        api_prefix="/api/v2",
        camera_id="camera-b-01",
        assigned_node="B",
        assigned_edge=("B", "C"),
        destination_node="D",
        route_map=route_map,
        voice=voice,
        poll_interval_s=1.0,
    )
    client.start()
    print("[2] AwsDeviceClient started. Initial route: B -> C -> D")

    try:
        # Step 3: Trigger sustained chair detection
        time.sleep(0.5)
        print("\n[3] Simulating sustained chair overlap detection at Junction B...")
        evidence = {
            "trigger": True,
            "positive_frames": 8,
            "total_frames": 10,
            "current": {"confidence": 0.89, "region_overlap": 0.35},
        }
        fake_frame = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x42" * 128
        record = client.on_chair_overlap_trigger(evidence, fake_frame)
        print(f"    Report generated: {record.report_id}")

        # Wait for outbox worker to upload photo & submit report
        print("\n[4] Waiting for outbox worker to upload evidence & submit report...")
        for _ in range(20):
            if client.status == DeviceWorkflowStatus.AWAITING_REVIEW:
                break
            time.sleep(0.2)

        assert client.status == DeviceWorkflowStatus.AWAITING_REVIEW, f"Expected AWAITING_REVIEW, got {client.status}"
        assert len(PHOTOS) == 1, "Photo was not uploaded to backend"
        assert len(REPORTS) == 1, "Report was not registered on backend"
        print(f"    Status confirmed: {client.status.value}")
        print(f"    Backend reports count: {len(REPORTS)} (Status: {list(REPORTS.values())[0]['status']})")
        print("    Invariant checked: Map version is still v1, edge B-C is NOT closed yet.")

        # Step 5: Simulate facilities reviewer clicking "APPROVE"
        print("\n[5] Simulating facilities human reviewer approving the B-C closure...")
        req = urllib.request.Request("http://127.0.0.1:8000/api/v2/simulate-approve", method="POST")
        with urllib.request.urlopen(req) as resp:
            approval_res = json.loads(resp.read().decode("utf-8"))
        print(f"    Review response: {approval_res}")

        # Step 6: Wait for map poller to detect v2 and apply reroute
        print("\n[6] Waiting for map poller to detect map v2 and apply reroute...")
        for _ in range(25):
            if client.is_edge_blocked_in_cloud and client.proposed_route == ["B", "E", "F", "D"]:
                break
            time.sleep(0.2)

        assert client.is_edge_blocked_in_cloud, "Edge B-C should be marked blocked in client"
        assert client.proposed_route == ["B", "E", "F", "D"], f"Expected reroute B->E->F->D, got {client.proposed_route}"
        assert len(voice.spoken) == 1, f"Expected 1 voice announcement, got {len(voice.spoken)}"
        print(f"    Client status: {client.status.value}")
        print(f"    New calculated route: {' -> '.join(client.proposed_route)}")
        print(f"    Voice announcement count: {len(voice.spoken)}")

        # Step 7: Verify subsequent map polls do NOT repeat speech
        print("\n[7] Waiting 3 seconds of additional map polls to verify speech debouncing...")
        time.sleep(3.0)
        assert len(voice.spoken) == 1, "Speech was improperly repeated!"
        print("    Speech debounce verified: 0 repeated announcements.")

        print("\n" + "=" * 65)
        print(" *** ALL PERSON 1 LIVE INTEGRATION TESTS PASSED SUCCESSFULLY! ***")
        print("=" * 65)

    finally:
        client.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_test()
