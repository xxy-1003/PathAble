"""Lightweight local mock backend for testing the Person 1 camera client.

Implements the CONTRACT.md endpoints under /api/v2:
- POST /api/v2/photos
- POST /api/v2/reports
- GET  /api/v2/map/version
- GET  /api/v2/map
- POST /api/v2/simulate-approve  (helper to simulate reviewer approving the report)
- POST /api/v2/simulate-reject   (helper to simulate reviewer rejecting the report)
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
import time
import uuid

# Shared in-memory state
MAP_STATE = {
    "version": 1,
    "map_id": "prototype",
    "nodes": {str(i): n for i, n in enumerate("ABCDEF")},
    "edges": [
        {"from": "A", "to": "B", "blocked": False},
        {"from": "B", "to": "C", "blocked": False},
        {"from": "C", "to": "D", "blocked": False},
        {"from": "B", "to": "E", "blocked": False},
        {"from": "E", "to": "F", "blocked": False},
        {"from": "F", "to": "D", "blocked": False},
    ],
}
for edge in MAP_STATE["edges"]:
    edge.update(distance=None, distance_source="unmeasured", route_weight=1)
REPORTS = {}
PHOTOS = {}
LOCK = threading.Lock()


class MockBackendHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(post_body)
        except json.JSONDecodeError:
            data = {}

        if self.path == "/api/v2/photos":
            photo_id = str(uuid.uuid4())
            with LOCK:
                PHOTOS[photo_id] = data
            print(f"\n[BACKEND] Photo uploaded! photo_id={photo_id}")
            self._send_json(201, {"photo_id": photo_id, "sha256": "mock-sha256"})

        elif self.path == "/api/v2/reports":
            report_id = data.get("report_id", str(uuid.uuid4()))
            with LOCK:
                prior = REPORTS.get(report_id)
                if prior:
                    if any(prior.get(k) != v for k, v in data.items()):
                        self._send_json(409, {"detail": "Report ID already used with a different payload"})
                    else:
                        self._send_json(200, prior)
                    return
                data.update(status="PENDING", received_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                REPORTS[report_id] = data
            print(f"\n[BACKEND] Obstacle report received! report_id={report_id}, camera={data.get('camera_id')}, obstacle={data.get('obstacle_class')}")
            print(f"[BACKEND] Status: PENDING review. Map version remains v{MAP_STATE['version']}.")
            self._send_json(201, data)

        elif self.path == "/api/v2/simulate-approve":
            with LOCK:
                MAP_STATE["version"] += 1
                for edge in MAP_STATE["edges"]:
                    if sorted([edge["from"], edge["to"]]) == ["B", "C"]:
                        edge["blocked"] = True
                new_ver = MAP_STATE["version"]
                for report in REPORTS.values():
                    if report["status"] == "PENDING":
                        report["status"] = "APPROVED"
            print(f"\n[BACKEND REVIEWER] *** REPORT APPROVED! ***")
            print(f"[BACKEND REVIEWER] Edge B-C is now BLOCKED. Map bumped to v{new_ver}!")
            self._send_json(200, {"status": "APPROVED", "map_version": new_ver, "edge": "B-C", "blocked": True})

        elif self.path == "/api/v2/simulate-reject":
            with LOCK:
                for report in REPORTS.values():
                    if report["status"] == "PENDING":
                        report["status"] = "REJECTED"
            print(f"\n[BACKEND REVIEWER] Report rejected. Edge B-C remains UNBLOCKED.")
            self._send_json(200, {"status": "REJECTED", "map_version": MAP_STATE["version"]})

        else:
            self._send_json(404, {"detail": "Not found"})

    def do_GET(self):
        if self.path.startswith("/api/v2/reports/"):
            with LOCK:
                report = REPORTS.get(self.path.rsplit("/", 1)[-1])
                self._send_json(200 if report else 404, report or {"detail": "Report not found"})
        elif self.path == "/api/v2/map/version":
            with LOCK:
                ver = MAP_STATE["version"]
            self._send_json(200, {"map_id": "prototype", "version": ver})

        elif self.path == "/api/v2/map":
            with LOCK:
                current_map = json.loads(json.dumps(MAP_STATE))
            self._send_json(200, current_map)

        elif self.path == "/health":
            self._send_json(200, {"status": "ok", "mode": "mock-backend"})

        else:
            self._send_json(404, {"detail": "Not found"})

    def log_message(self, format, *args):
        # Silence default HTTP access logs so output stays readable
        pass


def run_mock_server(port=8000):
    server = HTTPServer(("127.0.0.1", port), MockBackendHandler)
    print(f"[MOCK BACKEND] Running at http://127.0.0.1:{port}/api/v2")
    print(f"[MOCK BACKEND] Press Ctrl+C to terminate.")
    server.serve_forever()


if __name__ == "__main__":
    run_mock_server()
