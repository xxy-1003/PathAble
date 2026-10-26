# Competition submission integration

Prepared on 26 October 2026 from `codex/pathable-v3` at `e9e0046`.

## Included work

| Workstream | Included source |
| --- | --- |
| Canonical report/ticket contract, private photos, durable backend | `codex/aws-backend` at `63de1ad`, inherited by deployment branch |
| AWS deployment fixes and recorded checks | `codex/aws-deployment` at `77b27fd` |
| Device retry/map sync, Windows speech and live launcher | `codex/aws-device-client-fixes`, including `33a398b` |
| Reviewer dashboard and Cognito PKCE sign-in | `codex/aws-review-login` at `efba607` |

The integration additionally preserves actual obstacle classes in camera reports
and corrects the startup model label. The nine previously uncommitted camera and
token files were saved in `33a398b`. Existing private local settings, camera photos,
outboxes, model binaries, virtual environments and machine-specific toolkit rules
are not part of this snapshot.

## Overlapping teammate backend branch

`feature/pathable-backend-improvements` at `d47d971` was compared with the backend
used by the deployed demo. Both descend from canonical contract commit `a082765`.
Its direct-upload/report/ticket flow is already covered by the later backend's
canonical, local-persistence and S3 adapter tests. Its presign response uses a
different status code and its rewrite would also remove operational audit events
and loosen some of the current contract's location/destination validation.

The deployed backend implementation is retained rather than replacing it with
that overlapping rewrite. The teammate branch remains available unchanged for
separate review; this is not a claim that every commit on every branch is merged.

## Evidence boundaries

The historical AWS deployment details are in
[`DEPLOYMENT.md`](production/v3/cloud/fixed_camera/DEPLOYMENT.md).
The subsequent real camera screen reached `AWAITING_REVIEW` and showed cloud map
v4 with B–C already closed and a B–E–F–D proposal. That does not establish that a
new report caused a new closure; reviewer/API evidence must be checked separately.
## Integration verification — 26 October 2026

- Full `production/v3` Python suite: **304 passed, 2 subtests passed**; three
  dependency deprecation warnings.
- Reviewer Node.js suite: **22 passed**.
- Actual three-workstream code on localhost: approval changes map v1 to v2,
  proposes B–E–F–D and records one speech call; same-map restart does not repeat
  it. Rejection keeps v1 unchanged, and a later detection episode creates a
  distinct report.
- PowerShell launcher parses successfully. Git whitespace checks pass.
- The fixed-camera CloudFormation template passes `cfn-lint`.

The local workflow uses a synthetic JPEG and records speech calls. It does not
exercise the USB camera, contact live AWS or verify audible playback. No AWS
resources or shared map state were changed during this integration.

Physical corridor clearance, distance and safe walking guidance remain unverified.
No absence of detections is presented as permission to move forward. This phase
does not require Bedrock, COOL, marker localisation or public frontend hosting.

## Release handling

The combined work is reviewed against `codex/pathable-v3`. Keep `main` unchanged
until the team reviews the final snapshot. Retain the existing branches during
submission; delete them only through a separate team cleanup decision. The
`v1.0-competition-demo` tag freezes the reviewed competition source.
