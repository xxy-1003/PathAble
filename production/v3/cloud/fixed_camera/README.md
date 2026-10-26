# Person 2: fixed-camera AWS backend

Read the [revision 1.1 handoff and fixtures](HANDOFF.md) first, followed by
[CONTRACT.md](CONTRACT.md) for compatibility details. Person 1 owns the camera and laptop
clients; Person 3 owns the reviewer UI. This package preserves the existing
`cloud/api`, slow-loop, perception and navigation modules without changing their
behaviour. Use this service's `/api/v2` URLs for the new phase.

## Current evidence

The local laptop demo was deployed on 26 October 2026 (Malaysia time).
See [DEPLOYMENT.md](DEPLOYMENT.md) for the deployed API, sign-in settings,
release checks and remaining live-camera/audio verification. The bullets below
describe the original pre-deployment baseline and are superseded by that record
for the dedicated `pathable-fixed-camera-demo` stack.

- Shared API contract published before implementation.
- Local server defaults to durable SQLite and file photos on localhost. Explicit
  memory mode is volatile. Both are unauthenticated development modes, not AWS.
- DynamoDB/S3 adapter tests use Moto emulation, not a real AWS account.
- SAM template and build files are deployment preparation, not deployment proof.
- AWS account, deployed API, durable AWS restart checks and Person 1's live
  camera/laptop integration remain unverified. No physical clearance verified.

## Local development

From repository root, in a Python virtual environment:

```powershell
python -m pip install -r production/v3/cloud/fixed_camera/requirements-dev.txt
python -m production.v3.cloud.fixed_camera.local_server
```

Open `http://127.0.0.1:8002/docs` for interactive request schemas. State and photos
persist in the ignored `.test-tmp/fixed-camera` folder. Use `--volatile` for a
throwaway memory-only session, or `--state-dir <folder>` for a dedicated local
demo. Keep this unauthenticated server on localhost.
The committed `openapi.json` contains request and response schemas for teammates.
It describes bearer authentication for AWS; localhost omits it for development.

```powershell
python -m pytest production/v3/cloud/fixed_camera/tests -q
cfn-lint production/v3/cloud/fixed_camera/template.yaml
python -m production.v3.cloud.fixed_camera.export_openapi
```

## Durable design

One DynamoDB on-demand table stores separate `MAP#prototype`, `REPORT#<UUID>`,
and `PHOTO#<UUID>` items. A report and its one-to-one review ticket are stored
together in the REPORT item, with deterministic `T-<event_id>` identity. No module-global dictionary or local JSON is used by
the AWS handler. Each invocation reads the current map using consistent reads.
Report ID conditional creation makes retries safe. Review atomically updates
the report and checks/replaces the map with a version condition. Concurrent
review conflicts return 409; refresh before making another decision. A repeated
identical review returns the stored decision/version without another update.

The bucket is private, encrypted, denies HTTP and deletes photos after seven
days. Report/audit metadata remains in DynamoDB. Photo endpoints return 410
after retention. JPEG files are size-limited and decoded/verified server-side;
this does not automatically remove personal information. Clients handle privacy
before upload. Unreferenced photos are also covered by the bucket lifecycle.
The canonical upload route returns a 300-second, checksum-bound, no-overwrite
S3 PUT URL; the compatibility `/photos` route accepts base64. The report intake
reads the object and checks its actual JPEG bytes against the declared checksum
and size before storing a pending ticket.

The prototype listing endpoint uses bounded DynamoDB scans with continuation
cursors; follow `next_cursor` even when `items` is empty. This is for a small
demo, not an unbounded production event archive. Map items must remain within
DynamoDB's item size limit. Table point-in-time recovery is enabled. Stack
deletion retains table and bucket; they can continue incurring charges.

Map route weights are abstract, equal weights. All distances and clearances
remain null. Approval blocks B-C but does not certify that B-E-F-D is safe.

## AWS setup and deployment — perform only after access is available

See [OPERATIONS.md](OPERATIONS.md) for exact resource inventory, Cognito setup,
operational logs, privacy/retention boundaries and cleanup instructions.

1. Obtain the team/institution AWS account and permission to create a SAM stack,
   Lambda IAM execution role, API Gateway HTTP API, DynamoDB table, S3 bucket,
   and CloudWatch log group. Agree on the region and budget with its owner.
   There is no fixed cost guarantee; storage, requests, backups and logs cost
   money. Set a budget alert in that account before deployment.
2. Use AWS IAM Identity Center/SSO or another approved temporary sign-in method.
   Configure it locally with `aws configure sso`, then `aws sso login --profile
   pathable`. `aws sts get-caller-identity --profile pathable` verifies account
   and role. Do not paste tokens, passwords or secret access keys into chat.
3. Configure a trusted OAuth/OIDC provider (Cognito is an option): access tokens
   with `sub`, audience/client ID, issuer and `pathable/camera`,
   `pathable/reviewer`, `pathable/map` scopes. Dashboard/laptop sign-in should use
   authorization code with PKCE and no embedded client secret. Separate camera
   and reviewer accounts; restrict scope assignment. Record the fixed camera's
   `sub` and allowed reviewers' `sub` values for stack parameters. Never grant a
   camera subject reviewer privileges. This template expects an existing issuer;
   it does not provision accounts or a login UI. Coordinate login with Persons
   1 and 3 before calling their clients deploy-ready.
4. Install AWS CLI, AWS SAM CLI and Docker Desktop. Run Docker. Build inside the
   Linux Lambda container; the Makefile copies only this package, avoiding YOLO,
   OpenCV, fixtures and model downloads in Lambda:

   ```powershell
   sam build --use-container --template-file production/v3/cloud/fixed_camera/template.yaml
   sam validate --lint --template-file production/v3/cloud/fixed_camera/template.yaml
   sam deploy --guided --profile pathable
   ```

   Choose a dedicated stack name such as `pathable-fixed-camera-dev`. Use your
   approved region. Supply issuer, audience/client ID, camera `sub`, comma-separated
   reviewer subjects and the exact dashboard origin. Review changes before SAM
   creates resources. SAM may create a separate deployment artifact bucket.
5. Take `ApiUrl` from stack outputs. Give teammates only that URL and the public
   sign-in configuration. Each person signs in locally. Verify that an unsigned
   call is rejected and a camera user cannot review a report. Never publish
   access tokens or temporary photo URLs as deployment evidence.
6. Run the evidence sequence below before declaring deployment complete.

## Required live evidence

Record timestamp, region, stack name, code commit and non-secret output IDs.
Keep an evidence note outside credentials/config files.

1. POST a privacy-reviewed JPEG as the camera user; record photo ID and hash.
2. POST one report with null measurements; confirm PENDING and unchanged map.
3. Retry the same report ID; confirm no duplicate. Change the payload with the
   same ID; confirm 409.
4. Sign in as an allowlisted reviewer. Display the stored photo. Approve against
   the current map version; confirm report APPROVED and B-C blocked in one step.
5. Retry approval; confirm no second version change. Attempt stale/different
   review; confirm 409. Confirm camera and unsigned review attempts fail.
6. From a fresh process/session, read report and map and independently inspect
   DynamoDB/S3. This checks durable AWS storage beyond a warm Lambda process.
7. Person 1's laptop polls the new version, applies the map, reroutes B-E-F-D and
   speaks once. Capture actual evidence; a backend test cannot prove this step.
8. Record offline behaviour and the absence of measured clearance. No corridor
   walking trial or safe walking claim follows from a successful cloud demo.

## References

- [DynamoDB all-or-nothing transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
- [SAM HTTP API authorisation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-httpapi-httpapiauth.html)
- [S3 temporary private download URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html)
