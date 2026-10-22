# PathAble v3: local decision core

This is the first executable slice of the 18 October 2026 proposal. It follows
the one-floor, six-node scope and implements the offline decision table with
multi-frame blockage confirmation, Dijkstra routing, low-confidence rechecks,
and stop decisions when the camera or route is unavailable.

## Available cameras

The team has a laptop with an integrated webcam and an Android phone, but no
separate USB webcam. Use the integrated webcam for model and desk tests. For a
controlled walking demonstration, Windows 11 can expose a linked Android phone
as a **connected camera** if the phone has Android 10+ and a compatible Link to
Windows app. On the laptop, open Settings > Bluetooth & devices > Mobile devices,
pair the phone, and enable **Use as connected camera**. Keep both on the same
Wi-Fi network. Once enabled, the phone appears as a camera to PC applications.
Run `python camera_probe.py` to list OpenCV camera indices; the tool reads a few
frames and saves nothing. These requirements come from [Microsoft's connected
camera instructions](https://support.microsoft.com/en-gb/windows/apps/phonelink/use-your-mobile-device-s-camera).
If no camera appears, try `python camera_probe.py --backend dshow` and then
`python camera_probe.py --backend msmf` in a normal local terminal. A failed
camera probe in a remote or sandboxed execution environment does not establish
that the physical webcam is absent.

The camera connection must be tested for frame dropouts and delay on the actual
devices. If it drops, navigation must stop rather than use an old frame. A
handheld phone changes camera angle, so a floor homography measured for one
position will not give trustworthy distances after moving it. Secure the phone
in one fixed orientation and recalibrate for that phone/mount before any metric
distance or walking guidance claim. The phone is only the camera in this setup;
the fast decision loop and speech still run on the laptop. The older Android
APK is a separate on-phone warning prototype and does not stream frames to v3.

Run from this directory with Python 3.11+:

```powershell
python -m unittest -v test_local_agent.py
python replay_demo.py
```

The replay uses labelled, synthetic observations. It proves routing and
decision behavior only. Camera capture and YOLO11n-seg masks have been tested
as a separate probe. A fixed-pose adapter now converts mask contact pixels
into provisional near/medium/far observations, but it has only synthetic
tests: physical floor distance, ArUco pose on the route, speech, AWS event
intake, shared map, approval, COOL, and measured safety or whole-pipeline
latency targets are **not yet verified**.
The older `production_server.py` is a separate prototype; do not treat its
bounding-box output as the v3 confidence/mask/distance event.

The replay has no camera or model dependency and remains the acceptance test
for the decision module. The model is downloaded locally into ignored `models/`
rather than committed to Git.

Next integration gate: calibrate the printed markers, camera and floor on the
actual route, then produce `Observation` instances from recorded clips before
enabling live voice directions. Use a safety spotter for any human corridor trial.

For the model go/no-go check, create a dedicated Python 3.11 or 3.12 environment,
install `requirements-vision.txt`, run `download_model.ps1`, then run
`python model_probe.py models\\yolo11n-seg.onnx`.
It forces the new DNN engine, rejects a missing segmentation output, and prints
the output tensor shapes. A blank-frame run is only a compatibility check;
it is not evidence of correct masks, object classes, or 700 ms speech latency.

`python camera_vision_probe.py --camera 0 --backend dshow --frames 10` uses the
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
and a white margin. Hold the phone in portrait, lock auto-rotation, and leave
browser zoom unchanged for the whole calibration. Measure the displayed width
of several adjacent squares with a ruler, divide by their count, and use that
physical side length for `--square-mm`; do not assume CSS or PDF millimetres
equal physical screen millimetres. Keep the whole checkerboard and white margin
visible, avoid glare, and do not let the screen dim or rotate during captures.

Use the **same camera and fixed mount** for every calibration and later run.
For the laptop webcam and printed target, run
`python calibrate_camera.py --camera 0 --backend dshow`.
For the phone screen, run
`python calibrate_camera.py --camera 0 --backend dshow --target phone_screen --square-mm MEASURED_VALUE`.
Move and tilt the checkerboard across the camera view, pressing SPACE
for 20 varied detected views. The tool saves intrinsics and distortion in
ignored `calibration/camera.json` only if its RMS reprojection error is at most
1.5 px; no calibration images are saved. After
checking the actual target size with a ruler, set `verified_target_size` to `true` and write
the mount description in that JSON. A different Android phone camera requires
its own file and calibration, even if Windows exposes it as a webcam.

With a marker in front of the calibrated camera, run
`python marker_pose_probe.py calibration/camera.json --camera 0 --backend dshow`.
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
voice guidance remain disabled until moving-camera error and negative-detection
reliability have been measured on the actual route.
