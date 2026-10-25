# Verification — 25 October 2026

Historical local baseline. See [DEPLOYMENT.md](DEPLOYMENT.md) for the subsequent
26 October AWS demo deployment and checks; the original "Still unverified"
list below records the state before AWS access became available.

Base: integration branch `codex/pathable-v3`, commit `e9e0046` fetched from GitHub.
Work branch: `codex/aws-backend`. Shared contract first pushed in `3ea4250`.
Revision 1.1 canonical contract and synthetic fixtures first pushed in `a082765`.
Exact integration base: `e9e0046ef7851d54c5e2214a1a50638544fdc503`.

## Verified locally

- `python -m pytest production/v3 -q`: **249 passed, 2 subtests passed**.
  This includes 45 fixed-camera tests plus the existing 204 tests.
  Three dependency/API deprecation warnings; no test failures.
- `cfn-lint production/v3/cloud/fixed_camera/template.yaml`: exit 0.
- `git diff --check`: exit 0.
- Generated OpenAPI matches the committed schema (tested).
- New tests cover pending intake without map mutation, null metric fields,
  invalid evidence, report/review retries, changed-payload conflicts, stale map
  review, simultaneous reviews, expired photo references, immutable S3 writes,
  DynamoDB transaction rollback, a fresh storage-adapter read, JWT role checks,
  camera/reviewer separation, authenticated reviewer identity and Lambda HTTP
  event adaptation. Canonical tests additionally cover direct presigned uploads,
  actual byte checksum verification, explicit event schema/location/UTC fields,
  one-to-one tickets, fresh-process SQLite/photo persistence and audit-log privacy.
  AWS calls use Moto emulation only.
- Windows's restricted runner stalled creating an internal asyncio loopback
  socket. Tests passed with normal local networking; no test requested live AWS.

## Still unverified

- AWS account access and resource-creation permissions are not available to this
  session. The user is considering personal Free Tier sign-up; that is not proof
  of account activation, credentials, region selection or deployment permission.
  Actual deployed API address: unavailable. AWS region: not yet selected.
- AWS CLI and SAM CLI were not found in the active command path. SAM container
  build, actual deployment, JWT issuer/client configuration and real IAM policy
  behaviour have not been exercised. Static template validation does not prove
  any of those steps.
- Real S3/DynamoDB durability, deployed API requests, camera uploads, dashboard
  integration, laptop map application, rerouting and speech remain unverified.
- Physical corridor dimensions, free clearance and walking safety remain unknown.
  All metric fields in this phase stay null; graph route weights are abstract.

No Bedrock, COOL or junction-marker localisation is invoked by the new package.
Legacy modules are preserved. The only legacy-file change is a README link to
the new service. Parent `sources/` has not been modified.

The earlier AWS template in `cloud/infra/template.yaml` was inspected but is
preserved for the legacy workflow. The separate fixed-camera template adapts
its private S3/DynamoDB/SAM approach with a working handler package, conditional
transactions, JWT authorization, direct upload headers/CORS and no unused AI
resources. Linux SAM container packaging is still unverified.

Inventory, identity-provider configuration and cleanup are in `OPERATIONS.md`.
Canonical upload/review/map handoff and fixture semantics are in `HANDOFF.md`.
