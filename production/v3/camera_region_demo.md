# Fixed-view camera region routing demo

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe production\v3\live_navigation.py --camera 1 --backend dshow --model production\v3\models\yolo11s-seg.onnx --voice-mode auto --start B --dest D --camera-route-demo
```

Keep the camera fixed. The blue rectangle represents a monitored B-C region in
this demonstration. B is operator-assigned; no physical junction localisation
is claimed. This demo does not require floor-distance calibration.

1. Start with no chair in the rectangle and observe for 10 seconds: no reroute.
2. Place a chair outside the rectangle and observe for 10 seconds: no reroute if
   its detected bounding box does not substantially overlap the rectangle.
3. Place the chair inside the rectangle, step aside, and observe. A chair score
   of at least 0.60 and bounding-box overlap of at least 25% of region area count
   as a positive frame. At least six positives spanning one second and 80%
   positive frames in a two-second window trigger the proposed route once.
   Gaps over 0.75 seconds reset accumulated evidence.
4. Verify the bottom panel proposes B-E-F-D and the voice announces the camera
   demo result. R repeats the announcement. B does not manually confirm anything
   in camera mode. Q exits. Restart for a fresh trial.

The camera agent's STOP/unknown state remains visible and separate. Chair box
overlap is a demonstration trigger, not a measurement of floor clearance or
proof that a corridor is impassable. The alternative route is unverified.
Removing the chair never automatically reopens a route or authorises walking.

Per-frame detections and route state are saved locally in
`calibration/camera_route_trials/<session>/observations.jsonl`; the trigger's raw
image is `trigger.png`. These ignored files do not go to GitHub or AWS. Recorded
values are demo evidence, not measured route-completion evaluation results.

The empty photo `passage_clear_07.png` was checked offline without a detection
or trigger. Actual live empty/outside/inside trials remain to be performed.
