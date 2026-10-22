# PathAble v3: local decision core

This is the first executable slice of the 18 October 2026 proposal. It follows
the one-floor, six-node scope and implements the offline decision table with
multi-frame blockage confirmation, Dijkstra routing, low-confidence rechecks,
and stop decisions when the camera or route is unavailable.

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

This checkout currently has no ONNX model, pinned Python requirements, or
OpenCV installation in the bundled environment. The replay therefore has no
camera or model dependency and can be used as the acceptance test for the
decision module while the vision environment is prepared.

Next integration gate: obtain a pinned OpenCV 5 build and a compatible ONNX
model, verify tensor shapes on the actual laptop, then produce `Observation`
instances from recorded clips before enabling live voice directions. Use a
safety spotter for any human corridor trial.

For the model go/no-go check, install OpenCV 5 in a dedicated Python 3.11
environment and run `python model_probe.py path\\to\\yolo11n-seg.onnx`.
It forces the new DNN engine, rejects a missing segmentation output, and prints
the output tensor shapes. A blank-frame run is only a compatibility check;
it is not evidence of correct masks, object classes, or 700 ms speech latency.
