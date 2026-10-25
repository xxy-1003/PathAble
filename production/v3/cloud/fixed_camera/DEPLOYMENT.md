# Local laptop demo deployment — 26 October 2026

## Connection details

- Region: `ap-southeast-2` (Sydney).
- Dedicated stack: `pathable-fixed-camera-demo`, `UPDATE_COMPLETE`.
- API base: `https://pqrtq5b8og.execute-api.ap-southeast-2.amazonaws.com/api/v2`.
- Local dashboard: `http://localhost:8003/`.
- Callback: `http://localhost:8003/callback.html`.
- Cognito issuer: `https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_xbrH1dE6o`.
- Public app client: `6uasthmvrjkbslpj2dt1udi5uh` (no client secret).
- Managed login domain: `https://pathable-demo-xbrh1de6o.auth.ap-southeast-2.amazoncognito.com`.

The original `pathable-fixed-camera` stack, other Cognito pools, EC2 instance,
`main`, and integration branch were preserved. The frontend runs on the laptop;
it does not require public website hosting. AWS still supplies authentication,
the API and durable storage. Use `localhost`, rather than `127.0.0.1`, for sign-in
because the callback and browser access policy use that exact origin.

## Reviewer and camera login

Start `node production/v3/cloud/reviewer/serve.mjs` from the dashboard checkout.
Its ignored `auth-config.local.json` must contain the issuer, client ID,
`loginOrigin` and `apiBase` listed above. Reload after changing this file.

Choose **Reviewer sign-in** and use `reviewer-demo`. Choose **Camera / laptop
sign-in** in a separate tab and use `camera-demo`. Passwords are kept in the
operator's private local credential file outside this repository; they are not
in this document. Each button starts a fresh authorization-code flow with PKCE,
state and nonce. Do not reuse a copied login URL containing an old transaction.

Scopes are `openid pathable/reviewer pathable/map` for reviewer login and
`openid pathable/camera pathable/map` for camera login. The backend separately
allowlists the corresponding subjects; requesting a reviewer scope does not
make the camera account a reviewer. No EC2 key, IAM access key or API key is
used by these application clients.

On the camera tab, choose **Copy camera access token**, then in the local
PowerShell session that will launch the camera:

```powershell
$env:PATHABLE_AUTH_TOKEN = Get-Clipboard -Raw
Set-Clipboard -Value ''
```

Never print or commit this environment variable. Person 1's `AwsDeviceClient`
takes `api_base_url='https://pqrtq5b8og.execute-api.ap-southeast-2.amazonaws.com'`
and `api_prefix='/api/v2'` separately. Pass the token from the environment as
`auth_token`; do not duplicate `/api/v2` in both arguments. The same camera/map
token supports laptop map polling. Fixed assignment is `camera-b-01`, B / B-C,
destination D. A reviewer token is supplied automatically to the pinned API
after dashboard login. Tokens last 15 minutes; sign in again when expired.
Closing/reloading the dashboard clears its in-memory session.

## Deployed resources and package

- Lambda: `pathable-fixed-camera-demo-ApiFunction-XJoHKlsvAK5N`, Python 3.12,
  x86_64, active and last update successful.
- DynamoDB: `pathable-fixed-camera-demo-StateTable-YM0C5EQBWOJ1`.
- Private photos: `pathable-fixed-camera-demo-photosbucket-rbvuk6f2praz`.
- Artifact SHA-256: `e76bd27914fef9bfca8accf545bda0dcf9be5d4aaebf8bcc4a1fd69a69aa9929`.
- Lambda `CodeSha256`: `52vSeRT++b/Kisz1Rb2g3Pm+XUquv4vMSh/WmmmqmSk=`.
- Artifact size: 26,982,190 bytes.

The zip contains only this backend package and its dependencies, not local
credentials, images, databases, OpenCV or YOLO. `requirements-release.txt`
records the exact deployed dependency versions. The Linux binary-wheel builder
can prepare an equivalent dependency/source package without Docker (zip hashes
can differ because packaging timestamps are not normalized):

```powershell
python production/v3/cloud/fixed_camera/package_release.py --output .test-tmp/release --artifact-bucket YOUR_APPROVED_ARTIFACT_BUCKET
```

The builder requires pip and PyYAML in the local build environment. It does not
upload or deploy. Review the generated manifest/template, then upload through
the approved AWS connection and review a CloudFormation change set. The shared
SAM artifact bucket was reused under our own hash-named prefix only.

Two deployment fixes were required and verified against AWS: unauthenticated
OPTIONS preflight with authenticated data methods, and partition-correct
regional S3 signing via `S3_REGIONAL_ENDPOINT`. The new bucket's general S3
address returned HTTP 307; regional links loaded successfully in the dashboard.

## Verified evidence

- All **46 focused backend tests passed**, with two dependency deprecation
  warnings, using the release dependency versions. Earlier 249-test local
  baseline is recorded in `VERIFICATION.md`; the full suite was not repeated
  for this deployment update.
- `cfn-lint` passed. Native CloudFormation Guard 3.2.1 passed five selected
  registry rules: DynamoDB PITR, S3 public read/write prohibition, encryption
  and TLS. This is a scoped check, not a full security assessment.
- CloudFormation change-set pre-deployment checks passed. No existing resource
  was replaced or deleted. Persistent CloudTrail trails were absent; service
  event history provides reduced auditability.
- Actual unsigned API request returned HTTP 401. Actual camera-token attempt
  to approve its own report returned HTTP 403.
- Both demo accounts completed managed login with the actual browser flow.
- Person 1 client branch `codex/aws-device-client-fixes` at `3b35554` uploaded
  the synthetic JPEG via the compact compatibility API, submitted report
  `430fcac8-4d35-47e2-b0f8-5462642647f2`, and observed PENDING at map version 1.
  The overlap evidence was injected (8/10 frames, score 0.88), not YOLO output.
- Person 3's actual dashboard loaded that report and the private S3 image.
  Approval through the signed-in reviewer UI was recorded by AWS. DynamoDB
  then held version 2 with B-C blocked and all metric distances null.
- Person 1 client downloaded that update and selected B-E-F-D. A recorder saw
  exactly one `speak()` call. Recreating the client from its outbox, polling
  again and retrying the original report did not repeat speech or create a
  second map update.
- A separate consistent DynamoDB read confirmed the map and report. S3
  `HeadObject` confirmed the 629-byte JPEG, content type and AES256 encryption.
  The pending report also survived the Lambda code update before approval.
- Live resource checks confirmed all four S3 public-access blocks, encryption,
  seven-day photo expiry, DynamoDB PITR, exact Cognito issuer/audience and
  browser origin. Neither data nor photos are stored in Lambda memory/JSON.
- A second synthetic report, `fdb8f951-ec71-45c1-b9f6-1e493d10df07`, exercised
  a lost intake reply: AWS returned 201, the client deliberately discarded that
  reply locally, and a real retry with the same ID returned 200. A separate
  DynamoDB scan found one copy of each of the two test reports.
- The signed-in reviewer rejected that second report through the dashboard.
  Person 1's client observed REJECTED while the map stayed at version 3,
  B-C stayed open, the route stayed B-C-D and speech calls stayed at zero.
  Retrying the rejected report returned its existing terminal status. A
  continuing overlap episode stayed suppressed; a later episode received a
  distinct local ID (not submitted to AWS).

Local screenshots and machine-readable smoke results are outside Git in the
operator workspace outputs/test folder. No tokens, passwords or private signed
links are included in this evidence record.

## Remaining demo work

1. Run Person 1's actual mounted camera and configured image region against
   this API. Verify repeated overlap, upload, manual approval and laptop update.
2. Confirm the same audible speech during that camera-driven run. A standalone
   replay through Person 1's actual Windows SAPI backend now completes, and the
   operator confirmed the full B-E-F-D announcement was clearly audible. This
   exposed and fixed a COM thread ownership bug in `voice.py`; the device fix
   branch `5bc22ed` passed 246 tests and 2 subtests. A saved SAPI WAV replay is
   outside Git. It is synthesized replay, not a live-camera audio recording.
3. Coordinate and review integration of the backend, login/dashboard and device
   fix branches into `codex/pathable-v3`; this deployment did not merge them.

After that synthetic verification, the owner explicitly authorized a demo reset.
A conditional administrative write reopened B-C at **version 3**, retaining the
earlier approved report and all its evidence. The real camera run is pending
because the USB camera is disconnected. Do not silently reopen the map when the
camera no longer sees a chair. There is no reopening endpoint in this phase's
contract. Photos expire after seven days; old reports eventually lose images.

Role-escalation negative cases beyond the camera self-approval check, canonical
direct-S3 upload, server-side/network outage fault injection, long-duration
operation and physical corridor clearance remain unverified in AWS. The lost
reply case above injects a client-side failure after actual AWS success.
Canonical protocol and transaction conflict cases have local automated coverage.
No physical walking safety is established. Distances and clearances remain unknown.

Cleanup and retained-storage behavior are described in `OPERATIONS.md`. Do not
delete shared identity or artifact resources. Stack deletion retains the photo
bucket and table until the owner explicitly decides to remove their data.
