"""Synthetic localhost integration of the real device, backend and dashboard code.

Requires sibling checkouts with Person 2/3 code and backend development dependencies.
Does not use AWS, a camera or audio hardware. No source files in other checkouts change.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time


def wait_until(condition, label, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out: " + label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--dashboard-root", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.backend_root.resolve()))
    import uvicorn
    from production.v3.cloud.fixed_camera.app import create_app
    from aws_device_client import AwsDeviceClient
    from test_aws_device_client import cloud_map
    from aws_device_client import validated_cloud_map

    fixture_root = args.backend_root / "production/v3/cloud/fixed_camera/fixtures"
    jpeg = (fixture_root / "synthetic-evidence.jpg").read_bytes()
    dashboard = args.dashboard_root.resolve() / "production/v3/cloud/reviewer"
    evidence = {"trigger": True, "positive_frames": 8, "total_frames": 10,
                "current": {"confidence": 0.88}}

    class VoiceRecorder:
        def __init__(self):
            self.messages = []

        def speak(self, message, **kwargs):
            self.messages.append(message)

    for action in ("APPROVE", "REJECT"):
        # Each case gets a fresh map/report store and an isolated local outbox.
        app = create_app()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        server_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        server_thread.start()
        wait_until(lambda: server.started, "local backend startup")
        voice = VoiceRecorder()
        client = None
        try:
            with tempfile.TemporaryDirectory(prefix="pathable-contract-") as folder:
                def make_client():
                    return AwsDeviceClient(api_base_url=f"http://127.0.0.1:{port}",
                        outbox_dir=Path(folder), route_map=validated_cloud_map(cloud_map()),
                        voice=voice, poll_interval_s=0.5, http_timeout_s=1)

                client = make_client()
                record = client.on_chair_overlap_trigger(evidence, jpeg)
                client.start()
                wait_until(lambda: record.submitted_at is not None, "device photo/report submission")
                assert app.state.store.get_map()["version"] == 1
                assert client.proposed_route == ["B", "C", "D"] and not voice.messages
                client.stop()
                client = make_client()
                assert client._current_report.report_id == record.report_id
                assert client._submission_queue.empty()
                client.start()

                # Execute Person 3's actual API client/controller against Person 2's
                # real HTTP app. No replacement reviewer implementation or mock server.
                script = f'''
import {{ ApiClient }} from {json.dumps((dashboard / 'api.mjs').as_uri())};
import {{ ReviewController }} from {json.dumps((dashboard / 'controller.mjs').as_uri())};
const ui = new ReviewController(new ApiClient('http://127.0.0.1:{port}/api/v2', ''));
await ui.refresh();
await ui.select('T-{record.report_id}');
await ui.decide('{action}', 'Synthetic localhost cross-workstream verification');
if (ui.state.error || ui.state.selected.status !== '{'APPROVED' if action == 'APPROVE' else 'REJECTED'}')
  throw new Error(ui.state.error || 'Review status mismatch');
console.log(JSON.stringify({{status:ui.state.selected.status,map_version:ui.state.map.version}}));
'''
                result = subprocess.run(["node", "--input-type=module", "-e", script],
                                        capture_output=True, text=True, timeout=30, check=True)
                expected = "APPROVED" if action == "APPROVE" else "REJECTED"
                wait_until(lambda: client._reports[record.report_id].status == expected, "terminal report status")
                print(f"PASS: {action} with real three-workstream code; dashboard {result.stdout.strip()}", flush=True)

                if action == "APPROVE":
                    wait_until(lambda: client.proposed_route == ["B", "E", "F", "D"] and len(voice.messages) == 1,
                               "approved map route and one queued speech message")
                    client.stop()
                    assert app.state.store.get_map()["version"] == 2
                    # Repeated report submission returns existing terminal report, not 409.
                    assert client._submit_report(client._reports[record.report_id])["status"] == "APPROVED"
                    client = make_client()
                    client.poll_and_synchronize_map()
                    assert len(voice.messages) == 1
                    print("PASS: B-E-F-D, one recorded speech call, same-map restart does not repeat it", flush=True)
                else:
                    assert app.state.store.get_map()["version"] == 1 and not voice.messages
                    assert client.proposed_route == ["B", "C", "D"]
                    assert client.on_chair_overlap_trigger(evidence, jpeg) is None
                    client.on_chair_overlap_trigger({"trigger": False}, b"")
                    fresh = client.on_chair_overlap_trigger(evidence, jpeg)
                    assert fresh and fresh.report_id != record.report_id
                    wait_until(lambda: fresh.submitted_at is not None, "new episode after rejection")
                    client.stop()
                    print("PASS: rejection leaves v1 unchanged; later episode submits a distinct report", flush=True)
        finally:
            if client:
                client.stop()
            server.should_exit = True
            server_thread.join(timeout=5)
            listener.close()
    print("LOCAL SYNTHETIC VERIFICATION ONLY: no AWS deployment, live camera or audible speech proof.")


if __name__ == "__main__":
    main()
