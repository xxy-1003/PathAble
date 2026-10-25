# Camera region demo evidence — 25 October 2026

This is a bounded stationary-camera demonstration, not a completed measured
evaluation package. The submission status remains AWAITING_PHYSICAL_EVIDENCE.

## Recorded examples

| Local recording | Duration | Observed visual sequence |
| --- | --- | --- |
| `20261025-0755-30.7477509.mp4` | 23.1 s | Manual B-C confirmation changes the separate proposed route from B-C-D to B-E-F-D; backend speech status changes from playing to completed. |
| `20261025-0811-19.2103612.mp4` | 39.7 s | Empty region initially leaves B-C-D unchanged; chair enters monitored region; camera-demo trigger proposes B-E-F-D; backend speech status progresses to completed. |
| `20261025-0815-57.3810564.mp4` | 11.0 s | Chair is visible outside the monitored region; sampled frames show zero positive overlap frames and B-C-D remains proposed. |

The review inspected representative frames throughout these videos, not a
frame-by-frame annotation. The operator reports audible speech worked. Recorded
spoken content was not independently listened to or transcribed; backend
completion does not establish recorded audio or capture-to-audible latency.
These single examples do not support a success rate or false-positive rate.

Recordings remain local and have not been uploaded. SHA-256 fingerprints:

```text
0755: 6c8a00f49c7b78ca798a87d3ba559a0e9b1547a387e364063b045af9e7823537
0811: 589026624d19e0e7302906113d9206b31deea4fa08db775d612de18de15fcfe8
0815: 365d77d056ae78a09e35672c31c9a481464fdf0d8e0eebbdf171aa41473d0c30
```

The local camera session `1792915857509535300` records a first trigger with
8 qualifying observations out of 10 and a resulting B-E-F-D proposal. This is
not a latency measurement: the session started before recording and includes
time before chair placement. Two later sessions, `1792916057411160000` and
`1792916134074845700`, contained no trigger at review time. Sessions are not
asserted to be synchronised video ground-truth labels.

## What is and is not verified

- The optional camera-demo route graph reacts to a sustained chair detection
  bounding-box overlap rule. The normal perception agent remains conservative.
- Junction B is assigned by the operator. No full physical route was traversed.
- The trigger is an image-region heuristic, not measured remaining walking
  width, verified floor contact, or proof of physical impassability.
- Thin chair legs can be missed. The new chair-contact filter rejects broad
  seat bottoms and clipped masks; accepted thin extensions remain candidates.
- Small and larger floor setups were explored. Reported larger manual checks
  included OG 133.5 vs 139.6 cm, OH 87 vs 90.3 cm, and a chair-foot point 67.5
  vs 71 cm. Later camera changes invalidate reuse of that pose-specific mapping.
  These are exploratory user-reported checks, not corridor-wide accuracy.
- No verified AWS delivery, cloud metric-clearance provider, recorded COOL
  benchmark, complete measured trial dataset, or safe walking guidance is claimed.

## Integration validation

Full v3 software checks on the combined changes: 204 tests and 2 subtests passed.
One existing Starlette HTTP 422 naming deprecation warning remains. The larger
YOLO11s model was downloaded from the official v8.4.0 release and checksum
verified; it remains ignored, as do local calibration, photos and trial logs.

Use `download_model.ps1 -Size s` to obtain that model on another checkout.
The script's original no-argument nano download is retained.
