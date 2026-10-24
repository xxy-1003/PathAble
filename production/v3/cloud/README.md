# PathAble Cloud Slow-Loop Architecture (v3)

**Role**: Person 3 — AWS Slow-Loop Workflow  
**Target Proposal**: OpenCV AI Competition 2026, powered by AWS (Sections 6, 9, 10, 11)  
**Standard**: MS 1184:2014 (Universal Design in Built Environment — 1.20 m minimum clear corridor width)

---

## 1. Safety & Architecture Overview

PathAble employs a strict two-loop decoupled architecture:
- **Fast Loop (Device - Offline)**: Immediate collision avoidance, ArUco junction heading, local Dijkstra reroute, and `STOP` decisions run entirely on the laptop within 700 ms. **Safety never waits on the cloud or network.**
- **Slow Loop (AWS / Cloud - Asynchronous)**: When a local reroute occurs, a versioned blocked-edge event with 3–5 privacy-blurred keyframes is dispatched to the cloud. The cloud agent re-checks evidence, determines blockage permanence, coordinates human facilities review for lasting closures, and updates the shared map version for subsequent users.

```
+-----------------------------------------------------------------------------------+
| FAST LOOP (Device - Runs Offline, <= 700 ms)                                      |
|  Webcam -> YOLO11n-seg -> ArUco / Homography -> Decision Table -> TTS Speech     |
|                                     |                                             |
|                             REROUTE Event                                         |
|                      (Blurred Keyframes, Privacy OK)                              |
+-------------------------------------|---------------------------------------------+
                                      v
+-----------------------------------------------------------------------------------+
| SLOW LOOP (AWS - Asynchronous Re-check & Map Sync)                                |
|                                                                                   |
|  [Idempotent Intake] <---------------- POST /api/v1/events                        |
|           |                                                                       |
|  [Re-Check Tools (OpenCV 5 / Graviton)]                                           |
|     - detect(frames): YOLO11n-seg DNN engine                                      |
|     - motion(frames): Farneback optical flow (moving vs static)                   |
|     - clearance(frames): USAC homography width vs MS 1184 (1.20m min)             |
|     - history(edge): DynamoDB past reports                                        |
|           |                                                                       |
|  [Deterministic State Rules]                                                      |
|     - TEMPORARY: Moving object -> 10m auto-expiry (no human needed)               |
|     - UNCERTAIN: Static, 1st report -> Fail-safe hold (await next report)         |
|     - LASTING: Static across >=2 reports >=15m apart with clearance < 1.20m      |
|           |                                                                       |
|     [Tool Conflict?]                                                              |
|        Yes -> Amazon Bedrock (Nova Lite) Tie-Breaker                              |
|               -> Lambda Hard Rule Validator (LLM cannot reopen blocked edge)      |
|           |                                                                       |
|  [Outcome Execution]                                                              |
|     - TEMPORARY -> Auto-expiry timer -> Reopens edge -> Bumps Map Version         |
|     - LASTING   -> Opens Ticket (e.g. T-17) -> Facilities Review                  |
|                      - APPROVE -> Closes edge permanently -> Bumps Map Version    |
|                      - REJECT  -> Reopens edge -> Bumps Map Version               |
|                      - NO RESPONSE -> Fails safe (edge remains blocked)           |
+-----------------------------------------------------------------------------------+
```

---

## 2. Directory Layout

```
production/v3/cloud/
├── README.md                           # This document
├── schema/
│   ├── event_schema_v1.json            # JSON Schema Draft-07 for Blocked-Edge Event v1
│   └── models.py                       # Pydantic v2 data models
├── fixtures/
│   ├── event_temporary_person.json     # Moving person on B-C (10m auto-expiry)
│   ├── event_uncertain_chair.json      # Static chair, 1st report (fail-safe hold)
│   ├── event_lasting_furniture_1.json  # Table/chair report 1 at T=0m (0.9m clearance)
│   ├── event_lasting_furniture_2.json  # Table/chair report 2 at T=22m -> triggers LASTING
│   ├── event_conflicting_observation.json # Static chair with 1.6m clearance (Bedrock tie-breaker)
│   ├── event_invalid_privacy.json      # Unblurred frame (rejected by validator)
│   ├── event_invalid_schema.json       # Malformed payload (rejected by validator)
│   └── keyframes/                      # Synthetic 640x480 test JPEG frames
├── core/
│   ├── validation.py                   # Strict schema, graph edge, and privacy validation
│   ├── intake.py                       # Idempotent intake and payload hash deduplication
│   ├── recheck_tools.py                # OpenCV 5 Farneback flow, homography clearance, detection
│   ├── state_rules.py                  # TEMPORARY, UNCERTAIN, LASTING decision rules
│   ├── bedrock_tiebreaker.py           # Amazon Bedrock Nova Lite & Lambda Hard-Rule Validator
│   ├── map_sync.py                     # Versioned shared map manager with auto-expiry
│   ├── human_approval.py               # Facilities tickets (T-17+) & review workflow
│   ├── audit_logger.py                 # Structured CloudWatch decision trace recorder
│   └── orchestrator.py                 # Central orchestrator integrating all components
├── api/
│   ├── app.py                          # FastAPI REST application
│   └── static/                         # Interactive Facilities Review & Judge Web Dashboard
│       ├── index.html                  # Living 6-node SVG map & ticket review cards
│       ├── dashboard.css               # Clean accessible UI styling
│       └── dashboard.js                # Dynamic graph renderer and testbed triggers
├── infra/
│   ├── template.yaml                   # AWS SAM / CloudFormation serverless template
│   ├── cost_and_deployment_plan.md     # Itemized < $5.00 cost estimate & budget alarms
│   └── local_server.py                 # Standalone local execution server
└── tests/
    ├── test_schema_and_fixtures.py     # Schema conformity & privacy rule tests
    ├── test_intake_idempotency.py      # Deduplication & idempotent intake tests
    ├── test_state_rules.py             # TEMPORARY, UNCERTAIN, LASTING rule tests
    ├── test_bedrock_tiebreaker.py      # Bedrock conflict resolution & Lambda validator tests
    ├── test_map_versioning.py          # Map version increment & auto-expiry tests
    ├── test_human_approval.py          # Facilities APPROVE/REJECT ticket tests
    ├── test_recheck_tools.py           # OpenCV 5 Farneback optical flow & clearance tests
    └── test_api_and_review.py          # End-to-end API integration tests
```

---

## 3. Running Locally

### Run Unit & Integration Tests (100% Offline)
```powershell
python -m unittest discover -s production/v3/cloud/tests -t .
```

### Launch the Local Cloud Server & Web Dashboard
```powershell
python production/v3/cloud/infra/local_server.py --port 8000
```
Then open your browser:
- **Interactive Review Dashboard**: [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)
- **Swagger / OpenAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 4. API Specification

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/events` | Ingests blocked-edge events from edge device idempotently. |
| `GET` | `/api/v1/map` | Returns authoritative shared map graph with edge blocked statuses. |
| `GET` | `/api/v1/map/version` | Lightweight version check polled by edge devices at junctions. |
| `GET` | `/api/v1/tickets` | Lists facilities tickets (`?status=PENDING` filter supported). |
| `GET` | `/api/v1/tickets/{id}` | Returns details of a specific facilities ticket. |
| `POST` | `/api/v1/tickets/{id}/review` | Facilities staff action: `APPROVE` or `REJECT`. |
| `GET` | `/api/v1/traces` | Chronological decision trace audit stream (CloudWatch logs). |
| `GET` | `/api/v1/health` | Health check endpoint. |

---

## 5. Verification Status

| Component | Status | Verification Evidence |
| :--- | :--- | :--- |
| **Event Schema v1 & Fixtures** | **Verified** | 7 fixtures tested against Pydantic models & JSON schema (`test_schema_and_fixtures.py`) |
| **Idempotent Intake** | **Verified** | Deduplication, payload hash conflict detection, edge indexing verified (`test_intake_idempotency.py`) |
| **OpenCV 5 Farneback Optical Flow** | **Verified** | Farneback flow on keyframe image pairs verified (`test_recheck_tools.py`) |
| **MS 1184:2014 Clearance Engine** | **Verified** | Ground-line homography clearance calculations verified against 1.20m standard (`test_recheck_tools.py`) |
| **State Decision Rules** | **Verified** | TEMPORARY (10m), UNCERTAIN (hold), LASTING (>15m, 2 reports) verified (`test_state_rules.py`) |
| **Bedrock Tie-Breaker & Validator** | **Verified** | Conflict detection, LLM reasoning simulator, and hard-rule validator override verified (`test_bedrock_tiebreaker.py`) |
| **Map Versioning & Auto-Expiry** | **Verified** | Version bumping, temporary block expiration, lasting closures verified (`test_map_versioning.py`) |
| **Facilities Human Review** | **Verified** | Ticket creation (T-17+), fail-safe invariant, APPROVE/REJECT map synchronization verified (`test_human_approval.py`) |
| **FastAPI REST Service** | **Verified** | Complete API suite and HTTP responses verified (`test_api_and_review.py`) |
| **Review Web Dashboard** | **Verified** | Interactive SVG 6-node map, review cards, fixture simulation testbed (`dashboard.html / js / css`) |
| **Live AWS Provisioning** | **Unverified (Pending Approval)** | Blocked by explicit cost and deployment approval safeguard. Concrete plan prepared in `infra/cost_and_deployment_plan.md` |
