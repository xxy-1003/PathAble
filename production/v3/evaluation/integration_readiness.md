# Integration fixes — 24 October 2026

## 25 October follow-up

The integrated fixed-camera demo adds manual floor clicking, a Windows speech
fallback, unchanged-STOP speech suppression, conservative chair-contact
rejection, operator-confirmed route changes, route-announcement replay and
visible backend status. An opt-in camera-region chair-overlap demo proposes a
separate route after repeated qualifying detections and saves local trial logs.
Full software validation: 204 tests and 2 subtests passed, with the existing
HTTP 422 naming deprecation warning. See
[the recorded demo evidence](camera_demo_evidence_2026-10-25.md) for the reviewed
inside/outside recordings and the remaining physical/evaluation limits.

The remainder below records the earlier integration baseline.

The integration-fixes branch combines the checked teammate heads:
`e3f0386` navigation, `463ce76` perception, `3d2df3a` cloud,
`d7cfd6a` benchmark (already in v3 `71aed18`), and `51c8ee3` evaluation.

The source issues from the initial review have been corrected:

| Area | Corrected behavior |
| --- | --- |
| Calibration | No camera-model-based generation. Real checkerboard and surveyed floor files record their calibration methods. Old generated defaults are rejected; matching pose needs an explicit flag. |
| Perception | No detections leave zones and distance unknown, including callers using the legacy allow_clear option. |
| Voice | The live inspection loop connects the voice engine. Speech timing identifies queue dispatch explicitly and leaves audible-start latency unavailable. |
| Cloud | The normal tools use configured inference or explicit unknown evidence. Metric width requires a trusted measurement provider with a source reference. Canned values exist only in the opt-in simulator. |
| Rule engine | Simulated or unavailable evidence cannot qualify a recorded decision. Uncertain and human-review holds do not reopen on a timer; temporary reports cannot downgrade an approved closure. |
| Dashboard | The corridor animation is labelled scripted. Demo intake requires simulation mode. Responses, traces, and tickets expose evidence origin. |
| Evaluation | Native benchmark records are checked and missing prices stay unavailable. Measured reports require reviewed physical evidence and capture-to-audible-speech timing. |

## Verification and remaining evidence

Verified on the combined fix branch: 182 tests passed; the mock voice replay,
explicitly simulated cloud replay, in-process HTTP smoke check, and dashboard
JavaScript syntax check passed. One existing HTTP status deprecation warning
does not affect those results. These are software checks only.

Run the combined checks from the repository root after installing requirements:

```powershell
python -m pytest production/v3 -q
python production/v3/replay_demo.py --voice-mode mock
python -m production.v3.cloud.demo_end_to_end
```

Software integration checks do not supply physical trial evidence. The team
still needs actual checkerboard and surveyed-floor calibration, route footage
and ground-truth labels, synchronized capture-to-audible-speech measurements,
a verified cloud clearance provider, and the recorded AWS/COOL benchmark runs.
The default cloud service remains unavailable where those providers are absent.
The legacy `production_server.py` dashboard is a separate heuristic prototype;
do not use its box-size distance bands as measured floor distance or its UI as
the v3 physical evaluation log.

The evaluation report must remain `AWAITING_PHYSICAL_EVIDENCE` until the real
package and named human review pass. See `measured_data_guide.md` for the exact
handoff. Do not replace missing data with simulator output to obtain a score.
