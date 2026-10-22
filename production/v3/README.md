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
decision behavior only. Camera capture, YOLO11n-seg masks, calibrated metric
distance, ArUco pose, speech, AWS event intake, shared map, approval, COOL,
and measured safety or latency targets are **not yet integrated or verified**.
The older `production_server.py` is a separate prototype; do not treat its
bounding-box output as the v3 confidence/mask/distance event.

The replay has no camera or model dependency and remains the acceptance test
for the decision module. The model is downloaded locally into ignored `models/`
rather than committed to Git.

Next integration gate: obtain a pinned OpenCV 5 build and a compatible ONNX
model, verify tensor shapes on the actual laptop, then produce `Observation`
instances from recorded clips before enabling live voice directions. Use a
safety spotter for any human corridor trial.

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
