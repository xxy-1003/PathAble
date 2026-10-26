# PathAble cloud workflow

For the current fixed-camera report → human approval → shared-map phase, use
[the separate Person 2 backend](fixed_camera/README.md) and its
[shared API contract](fixed_camera/CONTRACT.md). The legacy service below is
preserved; its routes and infrastructure are not the deployment for that phase.

The service supports event intake, map holds, and facilities review. AWS
provisioning and physical trial performance remain unverified.

The default service uses `CloudRecheckTools`. Missing models, recordings,
motion pairs, or surveyed clearance produce explicit unknown evidence. Client
class labels and zone occupancy cannot become cloud detection or metric width.
Unknown evidence keeps an edge blocked without a timer that silently reopens it.
Repeated unavailable or simulated reports cannot establish a lasting closure.

## Install and test

From the repository root, install the combined requirements and run:

```powershell
python -m pip install -r requirements.txt
python -m pytest production/v3 -q
```

The OpenCV distribution is pinned once in `requirements-vision.txt`; do not
install a second OpenCV wheel into the same environment.

## Local service and scripted demonstration

```powershell
python production/v3/cloud/infra/local_server.py --port 8000
```

The service exposes `/api/v1/events`, `/api/v1/map`, `/api/v1/tickets`, and
`/api/v1/traces`. `/api/v1/health` reports its evidence mode. Without configured
measurement providers, re-check results remain unavailable.

For canned workflow demonstrations, start a separate local process explicitly:

```powershell
python production/v3/cloud/infra/local_server.py --port 8000 --simulation
```

Then open [the local dashboard](http://127.0.0.1:8000/dashboard/). The corridor
panel is a scripted animation, not a live webcam. Demo submissions are enabled
only in the server's simulation mode. Results, traces, and tickets carry a
`simulated` evidence label. `demo_end_to_end.py` is also explicitly simulated.
Do not use these values as physical or AWS results, or mix a demo process's map
state with a real trial process.

## Recorded re-check interface

Configure `PATHABLE_MODEL_PATH` with the ONNX model and
`PATHABLE_KEYFRAME_ROOT` with the private local evidence directory before
starting the default server. Event filenames resolve only within this directory.
Unreadable or escaped paths produce unavailable evidence.

Detection calls the shared `SegmentationDetector` on decoded frames. The
motion tool computes a frame-flow heuristic from real pairs; camera motion
and actual moving objects still require ground-truth evaluation.

Metric free width requires a trusted server-side `clearance_provider` passed
to `CloudRecheckTools`. It receives resolved keyframe paths and returns a
`ClearanceResult` with observed evidence, surveyed `free_clearance_m`, and a
`measurement_source` audit reference. Until that provider and its physical
geometry are verified, width and threshold comparison stay null. Zone labels,
object range, and a projected bounding-box span are insufficient to assert
accessible free width. The 1.20 m comparison is a project rule; this prototype
does not certify compliance with an accessibility standard.

Use `SlowLoopOrchestrator(recheck_tools=tools)` to supply configured tools.
This preserves the workflow while keeping unavailable evidence visible.

## Rule and review boundaries

With observed evidence, rules support temporary motion reports, uncertainty,
and repeated restricted-clearance reports eligible for facilities review.
Simulation can exercise those branches only with an explicit opt-in. History
records carry their evidence origin; simulated or unavailable history cannot
qualify a recorded lasting-closure decision. Pending or expired human-review
holds do not automatically reopen. Temporary reports cannot override a closure
already approved by facilities staff.

The offline Bedrock tie-breaker is a simulator and identifies its model as
`offline-tiebreaker-simulator`; it is not proof of a deployed AWS model call.
The infrastructure template is a plan, not deployment evidence. Keep the
submission report awaiting evidence until recordings, labels, calibration,
latency, and the recorded benchmark files pass the evaluation gate and review.
