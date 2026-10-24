# Integration review — 24 October 2026

The teammate branches can be combined locally without file conflicts, but the
shared integration is held pending the following evidence and interface fixes.
No local integration merge from this review has been pushed.

| Owner | Checked branch head | Required follow-up |
| --- | --- | --- |
| Person 1 | `e3f0386` navigation | `voice.py` measures queue dispatch, not capture-to-audible-speech latency. Retain it as a component measurement; collect synchronized full-pipeline timings for the submission. |
| Person 2 | `463ce76` perception | `calibrate_logitech_c920.py` writes fixed intrinsics, RMS, floor homography, and held-out error values while labelling them verified. `live_navigation.py` invokes it automatically and sets `same_pose_verified=True`. Require real calibration and explicit pose confirmation before treating any distance as measured. The `allow_clear` path also promotes absent detections to clear with confidence 1.0; this needs validation rather than being counted as evidence of a clear route. |
| Person 3 | `3d2df3a` cloud | `CloudRecheckTools.detect()` returns supplied/fallback classes and fixed coverage instead of running the model. `clearance()` returns hardcoded widths from zone labels. Mark these outputs as simulated or replace them with measured inference and geometry before using them in physical evaluation. |
| Person 4 | `d7cfd6a`, merged into v3 `71aed18` | The benchmark source is integrated. Its README says the recorded 300-keyframe data and AWS results are still absent. A local stock baseline cannot establish a COOL speedup. |
| Person 5 | evaluation branch | The measured gate now reads native benchmark records, preserves missing cost values, requires capture-to-audible-speech latency, and records review of real calibration and absence of simulated outputs. Physical evidence is still required. |

The initial combined test attempt could not verify the full suite: this review
environment lacks OpenCV, FastAPI, and NetworkX, and default temporary-file
locations were inaccessible. These are environment limitations, not evidence
that teammate algorithms fail. Person 5's dependency-free evaluation tests are
run separately. Software tests and a conflict-free merge do not establish
physical trial performance.

Merge after the issues above are resolved and the relevant combined checks
pass. Keep trial footage, participant records, and generated reports private.
