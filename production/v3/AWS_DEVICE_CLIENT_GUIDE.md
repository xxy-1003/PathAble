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

`aws_device_config.example.json` illustrates constructor/configuration values;
the live command does not load that JSON file. Use the environment variables above
or explicit command-line options. Never commit a real token in a config file.

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

# Person 2's local actual backend (synthetic/local test only):
python production/v3/live_navigation.py --start B --dest D --aws-workflow --api-url "http://127.0.0.1:8002" --outbox-dir ".test-tmp/device-local" --poll-interval-s 2.5 --http-timeout-s 5 --max-submission-attempts 3
```

---

## Device Workflow States

The HUD overlay and logs display the active lifecycle:

| Status | Meaning |
|---|---|
| `MONITORING` | Camera is observing region B-C; no sustained blockage confirmed yet. |
| `UPLOADING_EVIDENCE` | Multi-frame trigger fired; evidence frame captured and uploading to cloud. |
| `REPORT_SENT` | Reserved status; successful intake currently transitions directly to AWAITING_REVIEW. The report UUID is generated once and reused on retry. |
| `AWAITING_REVIEW` | Report received by backend; awaiting human facilities review. |
| `APPROVED` | Authoritative map received with edge B-C marked blocked. |
| `PROPOSED_ROUTE_UPDATED` | Dijkstra route recalculated ($B \to E \to F \to D$) and announced once via voice. |
| `CONNECTION_UNAVAILABLE` | Connection, rejected request or recovery error; inspect the error. Retries preserve report identity and have a bounded attempt budget. |

---

## Safety Disclaimers

- Chair overlap is an image-region heuristic, **not** certified walking safety or physical clearance.
- Detection submits a report and waits; it does **not** declare free space or perform immediate local rerouting.
- Disappearance of the chair does **not** automatically reopen edge B-C; reopening requires an authoritative cloud map update.

## Review fixes and recovery

Follow-up branch: `codex/aws-device-client-fixes`, based on Person 1's
`a42119c25d76e01eac47ef48bba14d95462509c8`. See
[AWS_DEVICE_FIXES_HANDOFF.md](AWS_DEVICE_FIXES_HANDOFF.md) for verified outcomes.

- The outbox atomically saves JPEG, checksum and metadata before acknowledging a
  trigger. Restarting restores unsent reports with the same ID/photo reference;
  submitted pending reports resume status polling without being blindly reposted.
- The API returns 200 for an identical report retry. A 409 is a payload conflict
  and is never treated as success. 401/403/409/422 stop automatic submission retries.
  Temporary failures get at most three attempts by default. Correct credentials,
  payload or connection, reconcile the event on the server, and restart using the
  same outbox to retry preserved unsent events.
- Outbox and map checkpoints are bound to API address, prefix, camera and assigned
  location. Corrupt, altered or mismatched files block automatic recovery and new
  reports; original files are retained. Old outboxes without context/checksum
  metadata require deliberate owner reconciliation/migration. Do not delete an
  unresolved outbox just to silence an error or mint new event IDs.
- The complete authoritative graph must match the six-node prototype, have a valid
  monotonic version and contain every edge exactly once. All blocked flags and
  abstract route weights are applied together; null distances remain null. A newer
  full-map response uses its own version; stale or partial maps are rejected while
  retaining the previous route. A cached map is labelled unconfirmed until a fresh
  server check succeeds.
- Pending report status is polled independently of the map version, so rejection
  is detected even though the map stays unchanged. After a terminal decision, a
  continuing qualifying region is suppressed. A non-qualifying monitor result
  rearms a later episode, which receives a new ID. This never reopens a cloud edge.
- Route announcements are recorded once per relevant route change, with a persisted
  checkpoint to suppress repeats after restart. They do not clear queued camera
  STOP warnings. A recorded speech call is not proof of audible playback.

## Local cross-workstream contract check

Run from this checkout, with Person 2/3 code in the named sibling directories and
the backend's development Python dependencies plus Node.js available:

```powershell
python production/v3/verify_device_backend_contract.py --backend-root ../pathable-person5 --dashboard-root ../pathable-review-dashboard
```

This uses the actual three codebases, an ephemeral localhost HTTP API, a synthetic
JPEG and a speech-call recorder. It tests upload/intake, pending behaviour,
outbox restart, reviewer approval/rejection, authoritative maps, route changes,
announcement suppression and a later reporting episode. Storage is in memory;
auth is explicitly local-development mode. No AWS/camera/audio evidence is claimed.

The legacy `test_live_workflow_e2e.py` remains a **mock-server** demonstration.
Its name/output must not be used as proof of live AWS or audible speech.

Before real uploads, the team must approve image privacy handling and retention.
The client uploads the supplied frame bytes without automatic face/person redaction;
do not claim blurring ran. Deployed JWT scopes, real evidence privacy, AWS durability,
the physical camera workflow and audible recording remain live acceptance gates.
