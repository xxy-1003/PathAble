# Verification — 25 October 2026

Base: integration branch `codex/pathable-v3`, commit `e9e0046` fetched from GitHub.
Work branch: `codex/aws-backend`. Shared contract first pushed in `3ea4250`.

## Verified locally

- `python -m pytest production/v3 -q`: **229 passed, 2 subtests passed**.
  This includes 25 new fixed-camera tests plus the existing 204 tests.
  Three dependency/API deprecation warnings; no test failures.
- `cfn-lint production/v3/cloud/fixed_camera/template.yaml`: exit 0.
- `git diff --check`: exit 0.
- Generated OpenAPI matches the committed schema (tested).
- New tests cover pending intake without map mutation, null metric fields,
  invalid evidence, report/review retries, changed-payload conflicts, stale map
  review, simultaneous reviews, expired photo references, immutable S3 writes,
  DynamoDB transaction rollback, a fresh storage-adapter read, JWT role checks,
  camera/reviewer separation, authenticated reviewer identity and Lambda HTTP
  event adaptation. AWS calls use Moto emulation only.
- Windows's restricted runner stalled creating an internal asyncio loopback
  socket. Tests passed with normal local networking; no test requested live AWS.

## Still unverified

- AWS account access and resource-creation permissions are unavailable.
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
