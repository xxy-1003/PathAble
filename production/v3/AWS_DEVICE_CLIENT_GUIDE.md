# PathAble: Person 1 AWS Device Client Guide

Laptop-side integration connecting the fixed USB camera at Junction B to AWS.

## Architecture

```
[ Fixed USB Camera (Junction B) ]
               │
               ▼
   [ ChairRegionMonitor ]
   - Sustained trigger (>=6 frames, >=1s, >=80% over 2s)
               │
               ▼ (Off-thread outbox queue)
      [ AwsDeviceClient ]
      ├── Step 1: POST /api/v2/photos  (JPEG Base64 -> photo_id)
      ├── Step 2: POST /api/v2/reports (report_id UUIDv4, photo_id, edge B-C)
      └── Step 3: Background Map Poller (GET /api/v2/map/version every 2.5s)
               │
               ▼ (Approved map version received)
      [ Local Routing & Voice ]
      ├── Computes alternative route: B -> E -> F -> D
      └── Announces once: "Approved map update received from cloud..."
```

## Setup & Configuration

### 1. Environment Variables (No hard-coded credentials)

```powershell
# Set AWS API base URL (local dev or API Gateway URL)
$env:PATHABLE_API_URL = "http://127.0.0.1:8000"

# API path prefix (default: /api/v2 per CONTRACT.md)
$env:PATHABLE_API_PREFIX = "/api/v2"

# Camera ID assigned to Junction B
$env:PATHABLE_CAMERA_ID = "camera-b-01"

# Optional JWT access token when connecting to authenticated AWS API Gateway
# (Unauthenticated in local 127.0.0.1 mode)
$env:PATHABLE_AUTH_TOKEN = "your-jwt-bearer-token-here"
```

Alternatively, copy `aws_device_config.example.json` to configure options.

---

## Operating Commands

### 1. Run Unit Tests (Person 1)

```powershell
python -m pytest production/v3/test_aws_device_client.py -v
```

### 2. Run Complete v3 Integration Suite

```powershell
python -m pytest production/v3 -q
```

### 3. Launch AWS-Connected Live Camera Workflow

```powershell
# Live USB camera with TTS voice:
python production/v3/live_navigation.py --camera 0 --backend dshow --start B --dest D --aws-workflow

# For headless or testing with mock speech engine:
python production/v3/live_navigation.py --camera 0 --backend dshow --start B --dest D --aws-workflow --voice-mode mock

# Custom API endpoint:
python production/v3/live_navigation.py --start B --dest D --aws-workflow --api-url "https://your-api-gateway.amazonaws.com"
```

---

## Device Workflow States

The HUD overlay and logs display the active lifecycle:

| Status | Meaning |
|---|---|
| `MONITORING` | Camera is observing region B-C; no sustained blockage confirmed yet. |
| `UPLOADING_EVIDENCE` | Multi-frame trigger fired; evidence frame captured and uploading to cloud. |
| `REPORT_SENT` | Photo uploaded; report submitted with unique deterministic UUID `report_id`. |
| `AWAITING_REVIEW` | Report received by backend; awaiting human facilities review. |
| `APPROVED` | Authoritative map received with edge B-C marked blocked. |
| `PROPOSED_ROUTE_UPDATED` | Dijkstra route recalculated ($B \to E \to F \to D$) and announced once via voice. |
| `CONNECTION_UNAVAILABLE` | Transient network error; outbox retains report and retries with the same `report_id`. |

---

## Safety Disclaimers

- Chair overlap is an image-region heuristic, **not** certified walking safety or physical clearance.
- Detection submits a report and waits; it does **not** declare free space or perform immediate local rerouting.
- Disappearance of the chair does **not** automatically reopen edge B-C; reopening requires an authoritative cloud map update.
