"""Local UI verification against Person 2's actual app, with synthetic evidence.

Not AWS. No camera, credentials, durable storage or laptop sync is exercised.
"""
import argparse
import base64
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backend-root", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.backend_root.resolve()))

from fastapi.testclient import TestClient
import uvicorn
from production.v3.cloud.fixed_camera.app import create_app

root = Path(__file__).resolve().parents[1]
fixtures = json.loads((root / "fixtures.json").read_text(encoding="utf-8"))
app = create_app(allowed_origins=["http://127.0.0.1:8003"])
with TestClient(app) as client:
    photo = client.post("/api/v2/photos", json={"camera_id": "camera-b-01",
        "jpeg_base64": base64.b64encode((root / "synthetic.jpg").read_bytes()).decode()})
    photo.raise_for_status()
    request = fixtures["report_request"]
    request["image"] = photo.json()
    response = client.post("/api/v2/reports", json=request)
    response.raise_for_status()
    print("SYNTHETIC LOCAL CONTRACT TEST ONLY: one pending report, map version 1", flush=True)

uvicorn.run(app, host="127.0.0.1", port=8002)
