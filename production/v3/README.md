# PathAble v3: prototype integration

This combines the navigation, perception, cloud workflow, benchmark, and evaluation work.
It follows the one-floor, six-node scope and implements the offline decision table with
multi-frame blockage confirmation, Dijkstra routing, low-confidence rechecks,
camera timeout, active perception, and offline voice guidance.

## Local navigation and voice verification

Run from this directory with Python 3.11+:

```powershell
python -m unittest -v test_local_agent.py test_local_navigation_voice.py test_voice.py
python replay_demo.py
```

The offline voice layer (`voice.py`) operates non-blockingly using `pyttsx3` or native Windows
SAPI with automatic graceful fallback to mock mode in headless environments or systems without
an active audio output device. It enforces:
- `STOP_AND_ESCALATE` takes immediate priority, clearing any pending queue.
- `CONTINUE` is normally silent.
- `STEP_ASIDE`, `TURN_TO_LOOK`, `WAIT_AND_REOBSERVE`, and `REROUTE` speak appropriate instructions
  with debouncing cooldowns to prevent repeat spamming.
- The scripted A-to-D route replay demonstrates the entire journey from Entrance (A) to Lab (D)
  covering all six decision actions: `CONTINUE`, `STOP_AND_ESCALATE`, `WAIT_AND_REOBSERVE`,
  `REROUTE`, `TURN_TO_LOOK`, `STEP_ASIDE`, plus `ARRIVED`.

> [!NOTE]
> The replay uses labelled, synthetic observations. It proves routing, active perception, and
> offline voice decision logic without camera or AWS dependencies. Spoken walking instructions
> are **not** claimed to be safe for live guidance until camera calibration, physical floor
> distance measurements, and moving-camera error have been tested on site with a safety spotter.

## Integration fixes and recorded evidence

The live viewer no longer generates calibration from a C920 model name. Use
`calibrate_camera.py` with the physically measured checkerboard, then
`calibrate_floor.py` with surveyed floor points. New files record their measured
calibration method; older generated optical-bench defaults are rejected.
Verify the ruler measurement, mount, axes, and camera-file hash before use.

From this directory, `python live_navigation.py --camera N --voice-mode mock`
is a conservative inspection loop. Only add `--same-pose-verified` when the
current fixed mount matches the surveyed pose. A moving chest camera cannot
automatically reuse a stationary floor mapping. Unoccupied zones remain unknown
even with an active detector; absent detections do not establish a clear route.
The viewer connects the local voice engine, while its mock mode has no audible
output. `SpeechRecord.latency_ms` is explicitly scoped to queue dispatch;
`audible_start_latency_ms` remains unavailable until physically measured.

The cloud service defaults to recorded evidence or unknown values. Its scripted
demo requires `--simulation` and is labelled accordingly. See `cloud/README.md`.
The evaluation gate reads the recorded benchmark's native `run.json` format;
physical trials, real calibration, and capture-to-audible-speech timings still
need to be collected. See `evaluation/measured_data_guide.md`.

## Camera selection

The team's primary camera is now a Logitech USB webcam labelled HD 1080p.
The exact model has not been confirmed. The laptop's integrated camera is only
for fallback desk tests; the Android phone displays the checkerboard or ArUco
marker during calibration and ID checks. The fast decision loop runs on the
laptop. The older Android APK is a separate on-phone warning prototype.

Connect the USB webcam, close other apps using it, and run
`python camera_probe.py --backend dshow` in a normal local terminal. Identify
which reported index belongs to the Logitech webcam by opening a preview with
`python marker_id_probe.py --camera N --backend dshow`, replacing `N` with the
reported index. Do not assume the USB camera is index 0. If DShow cannot read
it, try `--backend msmf`. A failed probe inside a sandbox does not prove the
physical webcam is absent.

Use the **same USB camera, resolution and fixed mount** for calibration and
later tests. A camera mounted at a different angle or height needs its floor
mapping checked again; calibration from the laptop's integrated camera must
not be reused. Measure frame dropouts and delay on the actual device. If the
camera stops providing fresh frames, navigation must stop.

Next integration gate: calibrate the printed markers, camera and floor on the
actual route, then produce `Observation` instances from recorded clips before
enabling live voice directions. Use a safety spotter for any human corridor trial.

For the model go/no-go check, create a dedicated Python 3.11 or 3.12 environment,
install `requirements-vision.txt`, run `download_model.ps1`, then run
`python model_probe.py models\\yolo11n-seg.onnx`.
It forces the new DNN engine, rejects a missing segmentation output, and prints
the output tensor shapes. A blank-frame run is only a compatibility check;
it is not evidence of correct masks, object classes, or 700 ms speech latency.

`python camera_vision_probe.py --camera N --backend dshow --frames 10` uses the
camera without saving images. It reports detection classes, segmentation-mask
coverage of the lower L/C/R zones, and model inference time. It does **not**
give voice directions: floor-distance calibration, route-position verification,
and whole-pipeline timing remain required before connecting camera results to
the decision agent. On 23 October 2026, the local built-in camera and official
Ultralytics YOLO11n-seg ONNX model completed two ten-frame runs with OpenCV 5's
forced new DNN engine; the median **inference-only** times were 69.5 and 59.6 ms.
These short runs do not establish detection accuracy or the proposal's latency
target.

## Junction and floor calibration

For a printed target, print `output/pdf/PathAble_Markers_and_Checkerboard.pdf`
on A4 at **actual size / 100%**. Pages 1-6 are markers 0-5 for junctions A-F;
their outer black squares must be 150 mm wide. Page 7 has a 9 x 6 inner-corner
checkerboard with 18 mm squares. If a print is scaled, reprint it.

If no printer is available, open `phone_checkerboard.svg` **on the phone** as a
standalone image. It has 10 columns x 7 rows of squares (9 x 6 inner corners)
and a white margin. The QR in `output/qr/phone_checkerboard_qr.png` opens that
SVG directly on the phone. Hold the phone in portrait, lock auto-rotation, and leave
browser zoom unchanged for the whole calibration. Measure the displayed width
of several adjacent squares with a ruler, divide by their count, and use that
physical side length for `--square-mm`; do not assume CSS or PDF millimetres
equal physical screen millimetres. Keep the whole checkerboard and white margin
visible, avoid glare, and do not let the screen dim or rotate during captures.

Use the **same camera and fixed mount** for every calibration and later run.
For a printed target, run
`python calibrate_camera.py --camera N --backend dshow`.
For the phone screen, run
`python calibrate_camera.py --camera N --backend dshow --target phone_screen --square-mm MEASURED_VALUE`.
Use the USB webcam index found by `camera_probe.py` in place of `N`.
Move and tilt the checkerboard across the camera view, pressing SPACE
for 20 varied detected views. The tool saves intrinsics and distortion in
ignored `calibration/camera.json` only if its RMS reprojection error is at most
1.5 px; no calibration images are saved. After
checking the actual target size with a ruler, set `verified_target_size` to `true` and write
the mount description in that JSON. A different webcam requires its own file and calibration.

With a marker in front of the calibrated camera, run
`python marker_pose_probe.py calibration/camera.json --camera N --backend dshow`.
It reports marker IDs and marker-relative pose, with a reprojection check.
Turn-left/right guidance still needs measured wall-marker orientations in the
map, so this probe does not issue navigation instructions.

Before printing markers or calibrating the camera, you can test **ID recognition
only** with a phone screen. Open an ArUco generator on the phone, choose 4x4
(50, 100, 250, 1000), ID 0, and show the whole marker with a white margin.
Close the Windows Camera app so it releases the webcam. From this directory run
`.\.venv\Scripts\python.exe marker_id_probe.py --camera 0 --backend dshow`.
If the window says `Detected: 0 -> A`, the recognition check passed; press Q to
exit. If camera 0 fails, run `camera_probe.py` in the same terminal to find a
working index/backend. A phone-screen marker does not validate its physical
size, camera calibration, pose, or floor distance.

For floor distance, fix the camera in its demonstration mount and place at
least eight **measured** visible reference points across the flat floor. Run
`python capture_floor_frame.py` when no people are in view. Then run
`python inspect_floor_pixels.py calibration/floor_frame.png` and click the
reference points to read pixel coordinates. Start from
`floor_points_template.csv`; enter each point's image `(x,y)` and measured
floor `(x,y)` in metres, using a stated origin and axes. Mark at least six
spread-out points `fit` and two separate points `check`; do not use the same
point for both. Run `python calibrate_floor.py points.csv
calibration/camera.json`. It undistorts pixels, fits `cv.USAC_MAGSAC`, and
rejects a held-out error over 0.15 m. The resulting JSON still needs its
`floor_origin_and_axes`, `camera_floor_xy_m` (the measured floor position
directly below the lens), and `fixed_mount_verified` fields confirmed. Measure
and record the floor origin and axes, then enter the camera point as `[x, y]`
in that metre coordinate system. Complete the camera JSON's
`verified_target_size` and `mount_description` **before** floor calibration;
editing that camera file later invalidates the floor file's camera hash, so
rerun `calibrate_floor.py`. Pixels outside the measured fit region remain
distance-unknown rather than extrapolated.

`calibrated_observation.py` accepts a frame only at the calibrated resolution
and only when the caller explicitly supplies `same_pose_verified=True` for a
stationary recorded-frame experiment. Missing flags, a changed camera file,
contact outside the measured region, and values close to 1.0 m or 2.5 m
boundaries yield `unknown`. Those bands are provisional demo settings, not
measured safety thresholds. A frame with no target-class detection also has
`unknown` zones: it is **not** proof of an empty corridor. Live walking and
voice guidance remain unvalidated until moving-camera error and negative-detection
reliability have been measured on the actual route.
