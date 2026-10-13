# PathAble Android detection prototype

This is an Android camera app with on-device object recognition and spoken warnings. It adapts the warning rule in [PathAble's Python prototype](https://github.com/xxy-1003/PathAble/blob/main/test/pathable.py): an object is flagged if its box is large and centred in the lower part of the camera frame. The app displays detections, labels possible obstacles, and speaks a warning with a three-second cooldown.

The Android model is Google's **EfficientDet-Lite0 (int8)**, not the desktop prototype's YOLO11 model. It is a MediaPipe-compatible TensorFlow Lite model. The first build downloads the model from Google's [published model URL](https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite) into the app assets. After installation, detection and speech use the phone locally.

## Build an APK on Windows

1. Install Android Studio and SDK Platform 35. Use Android Studio's bundled JDK 17 or another JDK 17 installation.
2. Open this `PathAble-Android` folder as a project. Allow Gradle sync and SDK downloads. The first build needs internet for dependencies and the model.
3. In the Android Studio terminal, run `./gradlew.bat assembleDebug`. This project's `gradlew.bat` downloads Gradle 8.9 on first use.
4. Install `app/build/outputs/apk/debug/app-debug.apk` on an Android 7.0+ phone. The app asks for camera permission on launch.

The debug APK is for personal testing. It is not a signed release build for distribution. The camera preview and analysis need testing on the target phone for orientation, frame rate, audio volume, and detection behaviour.

## Limits

This is a **possible obstacle warning demo**. Box size and image position are not distance measurements. The app does not determine that a route is safe, navigate between checkpoints, or reroute. The model only detects categories it was trained to recognise and can miss visible hazards. Do not use this prototype as a sole mobility aid.

The app source has not been compiled in this workspace because the Android SDK is not installed here and network downloads are unavailable in this environment.
