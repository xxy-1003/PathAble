# PathAble — Agent Rules & Contribution Guide

> [!CAUTION]
> Spoken navigation instructions produced by this system are **NOT** certified safe
> for live physical deployment. Field testing with safety spotters and full sensor
> calibration is required before any human corridor trial.

## Repository Purpose

PathAble is a prototype indoor navigation aid for visually impaired users,
entered in the **OpenCV AI Competition 2026**. The project is divided into three
specialist roles:

| Person | Domain |
|--------|--------|
| **Person 1 (Local Navigation & Voice)** | On-device decision agent, Dijkstra routing, offline TTS |
| **Person 2 (Perception & Calibration)** | YOLO11n-seg, ArUco localisation, floor homography, optical flow |
| **Person 3 (Cloud / AWS)** | Slow-loop re-check, IoT sensor hub, companion alert |

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable release snapshots only |
| `codex/pathable-v3` | Integration target for v3 proposal work |
| `codex/pathable-navigation` | **Person 1 working branch** (local agent & voice) |
| `codex/pathable-perception` | Person 2 working branch |
| `codex/pathable-cloud` | Person 3 working branch |

**Never** force-push, reset, or discard commits on any branch without team consensus.
All PRs target `codex/pathable-v3`; do **not** merge directly to `main`.

---

## Scope Boundaries — What Each Agent May Edit

### Person 1 (`codex/pathable-navigation`)

**Owns:**
- `production/v3/local_agent.py` — decision table, routing, `Observation`, `RouteMap`
- `production/v3/voice.py` — offline TTS with priority/debounce
- `production/v3/replay_demo.py` — end-to-end A→D scripted replay
- `production/v3/test_local_agent.py`
- `production/v3/test_local_navigation_voice.py`
- `production/v3/test_voice.py`
- `production/v3/test_navigation_spec.py` — new spec-compliance tests
- `production/map_graph.json` — six-node prototype graph
- `requirements.txt` (repo root)
- `AGENTS.md` (this file)

**Must NOT edit** (owned by other roles):
- `production/v3/vision.py` — YOLO pipeline (Person 2)
- `production/v3/calibrated_observation.py` — floor projector (Person 2)
- `production/v3/calibrate_*.py`, `camera_*.py`, `marker_*.py` (Person 2)
- `production/production_server.py` — cloud server (Person 3)
- `production/iot_sensor_hub/` (Person 3)
- Any evaluation benchmark or AWS integration scripts

---

## Map Graph Specification (v3 Prototype)

Six ArUco junction nodes on a single flat floor:

```
A (Entrance) ──12 m──► B (Junction) ──15 m──► C (Junction) ──12 m──► D (Lab)
                         │
                        10 m
                         │
                         ▼
                        E (Junction) ──24 m──► F (Junction) ──10 m──► D
```

| Edge  | Length | Role |
|-------|--------|------|
| A – B | 12 m   | Entry corridor |
| B – C | 15 m   | Primary (blockage target) |
| C – D | 12 m   | Final segment (primary) |
| B – E | 10 m   | Reroute fork |
| E – F | 24 m   | Reroute corridor |
| F – D | 10 m   | Reroute final |

Primary route A→B→C→D = **39 m**.
Reroute B→E→F→D = **44 m**.

---

## Decision Table (Section 8 of Proposal v3)

| Priority | Condition | Action | Voice Output |
|----------|-----------|--------|--------------|
| 0 | Centre clear, confidence ≥ 0.60 | `CONTINUE` | *(silent)* |
| 1 | Centre near/medium, conf ≥ 0.60, one side clear | `STEP_ASIDE` | *"Obstacle ahead. Step slightly right/left."* |
| 2 | Moving person in centre OR conf 0.40–0.60 | `WAIT_AND_REOBSERVE` | *"Please wait."* |
| 3 | Required avoidance side is unknown | `TURN_TO_LOOK` | *"Turn slightly left/right so I can check that side."* |
| 4 | Centre near + both sides occupied ≥ 6/10 frames, conf ≥ 0.60 | `REROUTE` | *"Route blocked. Turn left at this junction towards E."* |
| 5 | conf < 0.60 after 2 re-obs, no alt path, or camera timeout > 1.0 s | `STOP_AND_ESCALATE` | *"Please stop and stay where you are. I am contacting your companion."* |

> [!WARNING]
> `STOP_AND_ESCALATE` must **immediately** preempt and discard all queued speech.
> `CONTINUE` must always be **silent** — no voice output.

---

## Observation Schema

```python
@dataclass(frozen=True)
class Observation:
    timestamp: float          # Unix seconds
    obstacle_class: str|None  # COCO class name or None
    confidence: float         # 0.0–1.0
    left: Zone                # "clear" | "occupied" | "unknown"
    centre: Zone
    right: Zone
    distance: Distance        # "near" | "medium" | "far" | "unknown"
    moving: bool              # Farneback optical-flow flag
    node: str|None            # ArUco junction ID if at marker
    # Extended spec fields (added in navigation spec update):
    persistence_count: int    # Frames obstacle persisted in ring buffer
    current_edge: tuple|None  # (from_node, to_node) edge being traversed
    heading: float|None       # Compass bearing degrees (0=North)
```

**Ring buffer:** 10-frame deque; blockage confirmed when `sum(buffer) ≥ 6`.
**5-frame mean confidence** is tracked separately for smoothing.

---

## Latency Budgets

| Operation | Budget |
|-----------|--------|
| Decision + route planning | ≤ 10 ms |
| Voice dispatch (queue put) | ≤ 50 ms (p95) |
| YOLO11n-seg inference | ≤ 100 ms (target) |
| End-to-end frame loop | ≤ 200 ms |

---

## Running Tests & Demo

```powershell
# From production/v3/
python -m pytest test_local_agent.py test_local_navigation_voice.py test_voice.py test_navigation_spec.py -v
python replay_demo.py --voice-mode mock
```

All tests must pass with exit code 0 before any PR is created.

---

## Safety Disclaimer

> [!CAUTION]
> This system is a **research prototype** for the OpenCV AI Competition 2026.
> Spoken walking instructions are NOT certified safe for live physical deployment.
> Before any human trial:
> - Complete full camera intrinsic + floor homography calibration on the actual route.
> - Measure moving-camera error and negative-detection reliability.
> - Station a trained safety spotter at all times during corridor trials.
> - Obtain appropriate ethics/safety approvals from your institution.
>
> The replay demo uses synthetic observations only. No live camera or voice
> output constitutes a navigation safety guarantee.
