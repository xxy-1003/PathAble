# PathAble

PathAble is an OpenCV AI Competition 2026 prototype for reporting possible indoor
obstructions, reviewing the evidence, and sharing an approved map change with a
laptop route planner and speech output.

**Demo workflow:** USB camera → private AWS photo/report → human review → shared
map update → laptop route proposal and speech.

The competition demo assigns a stationary camera to junction **B**, edge **B–C**,
by configuration. It uses **YOLO11s segmentation through OpenCV DNN**. Sustained
overlap with the configured image region creates a report. A pending report does
not close an edge; a separate reviewer must approve it. An approved B–C closure
produces the proposed route **B → E → F → D**.

This is a controlled software demonstration. Detection does not prove physical
blockage, and no detection does not prove clearance. Distance and clearance stay
unknown. A route proposal is not permission to walk. Bedrock, COOL and marker
localisation are outside this demo; older modules remain in the repository.

## Version to use

Use `main` for the combined competition demo. The `v1.0-competition-demo` tag
identifies the frozen, tested source snapshot; `codex/pathable-v3` remains the
integration branch for subsequent work. Release promotion updates these
instructions without changing the tagged application code.

```powershell
git clone https://github.com/xxy-1003/PathAble.git
cd PathAble
```

See [integration notes](SUBMISSION.md) for branch decisions and verification.

## Try the reviewer page without AWS

Requires Node.js 22 or newer. No camera, Python setup or credentials are needed.

```powershell
node production/v3/cloud/reviewer/serve.mjs
```

Open **http://localhost:8003/**. Leave **Fixture practice · synthetic** selected,
select its report, inspect the synthetic photo, and try approval or rejection.
This mode changes only practice data in the browser. It does not contact AWS.
Stop the server with Ctrl+C. `localhost` is accessible only on that computer.

## Prepare the real camera demo

Use Windows, Python 3.12, Node.js 22+, a USB webcam, and an audio output device.
Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\production\v3\download_model.ps1 -Size s
```

The model downloader verifies its SHA-256. Model binaries are downloaded locally
and are excluded from Git. Use camera index **1** for this team's USB webcam;
another laptop may assign a different index.

For the approved team's existing AWS demo, copy its non-secret login settings:

```powershell
Copy-Item production/v3/cloud/reviewer/auth-config.demo.example.json production/v3/cloud/reviewer/auth-config.local.json
node production/v3/cloud/reviewer/serve.mjs
```

Do this in a fresh checkout; preserve an existing local config if you use another
deployment. The local config is ignored by Git. Public login configuration grants
no access by itself: the owner must provide the separate reviewer and camera demo
accounts privately. Judges without credentials can use fixture practice and the
local tests. Never commit passwords, tokens or AWS access keys.

## Run camera → AWS → reviewer → route

1. Open **http://localhost:8003/** in two tabs. Use **Reviewer sign-in** with
   `reviewer-demo` in one and **Camera / laptop sign-in** with `camera-demo` in
   the other. Use the owner's privately supplied passwords.
2. In the reviewer tab select **API connection · real data** and the configured
   API address, then **Connect / reset**. Its banner must no longer say fixture
   mode. Sign-in supplies the reviewer token automatically.
3. Keep the dashboard server running. In a second PowerShell window, from the
   repository root, start the camera:

   ```powershell
   .\production\v3\run_aws_demo.ps1 -Camera 1 -Python '.\.venv\Scripts\python.exe' -Model '.\production\v3\models\yolo11s-seg.onnx' -Outbox '.test-tmp\competition-demo' -PromptForToken
   ```

4. **After starting the command**, click **Copy camera access token** in the
   camera sign-in tab. Paste it at PowerShell's hidden prompt and press Enter.
   The preflight checks sign-in and saved state before starting an upload.
5. Point the secured webcam at the test area, excluding people and private
   details. Place a supported object, such as a chair, in the blue image region
   long enough to trigger a report. The region represents B–C by assignment;
   it is not a physical clearance measurement. Wait for **AWAITING_REVIEW**.
6. In the reviewer tab click **Refresh**, select the new pending report, inspect
   its photo and choose **Approve** or **Reject**. Approval updates the shared
   map. Rejection leaves the map unchanged.
7. Observe the camera window's authoritative map version and proposed route.
   A newly approved B–C closure should propose B–E–F–D and queue its announcement.
   Listen to the speaker to verify the actual audio. A playback status alone
   does not prove that someone heard it. Press **Q** to exit the camera.

If B–C was already closed by an earlier approved report, another approval may
leave the route unchanged. A fresh local outbox does **not** reset AWS's map.
Coordinate any shared demo-map reset with its owner. Preserve the same outbox
when retrying an interrupted upload so its report ID stays the same. Use a new
outbox name for a deliberately separate test session.

Tokens expire after 15 minutes in this deployment. Sign in again after a 401.
The camera and reviewer accounts have separate permissions. No EC2 login or AWS
secret access key is needed for the application demo.

## Check the software locally

These checks use synthetic data, in-process APIs or emulated AWS adapters. They
do not upload real camera photos or prove deployed AWS or walking safety.

```powershell
.\.venv\Scripts\python.exe -m pip install -r production/v3/cloud/fixed_camera/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest production/v3 -q
node --test production/v3/cloud/reviewer/tests/*.test.mjs
.\.venv\Scripts\python.exe production/v3/verify_device_backend_contract.py --backend-root . --dashboard-root .
```

The last command runs the actual device client, backend and reviewer controller
together on localhost for approval, rejection, restart, map sync and recorded
speech-call checks. Audio hardware and real AWS are outside that check.

## More detail

- [Camera client and retry guide](production/v3/AWS_DEVICE_CLIENT_GUIDE.md)
- [Reviewer dashboard](production/v3/cloud/reviewer/README.md) and [sign-in setup](production/v3/cloud/reviewer/AUTH_LOGIN.md)
- [Shared API contract](production/v3/cloud/fixed_camera/CONTRACT.md)
- [Recorded AWS deployment and checks](production/v3/cloud/fixed_camera/DEPLOYMENT.md)
- [Backend operations and retention](production/v3/cloud/fixed_camera/OPERATIONS.md)
- [Earlier v3 modules and limits](production/v3/README.md)

Deployment notes are historical evidence, not a guarantee that a shared endpoint
will remain available indefinitely. Model and dependency licences remain those
of their respective authors; bundled dashboard notices are in its `vendor/` folder.
