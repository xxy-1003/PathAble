# Person 1 review fixes — 25 October 2026

Follow-up branch: `codex/aws-device-client-fixes`.
Person 1 base: `a42119c25d76e01eac47ef48bba14d95462509c8`.
Integration base: `e9e0046ef7851d54c5e2214a1a50638544fdc503`.
Final commit: the commit containing this handoff, reported in the chat; retrieve
with `git log -1 --format=%H -- production/v3/AWS_DEVICE_FIXES_HANDOFF.md`.

No main/integration merge or AWS deployment was performed. Person 1's original
branch, Person 2's backend and Person 3's dashboard code were preserved.

## Reviewed problems and fixes

| Confirmed problem | Resulting behaviour |
| --- | --- |
| Outbox files were written but never read after restart | Restore the same event ID, immutable image/checksum, uploaded photo reference and submitted/review status. Requeue only unsent reports; poll submitted pending ones. Atomic writes and context checks prevent silent replacement of damaged/foreign records. |
| HTTP 409 was accepted as a successful report | Only a valid 200/201 matching the queued identity is accepted. 409 is a conflict. Permanent errors stop automatic attempts; temporary errors have a bounded attempt budget and preserved retry metadata. |
| Stale/incomplete maps were marked as applied | Validate project map ID, integer monotonic versions, all six nodes and all six unique prototype edges, strict blocked flags, abstract weights and null measurement fields before changing state. Retain the previous graph on failure. |
| Only B–C was copied into the local graph | Replace the complete validated graph using every closure and route weight. A blocked alternative edge cannot be silently traversed; no available route yields an empty proposal and a stop message. |
| Active report was never cleared | Poll report status independently of map version. Terminal approval/rejection releases the active record. Suppress the same sustained episode until a non-qualifying monitor result rearms a later report. Camera disappearance never reopens an edge. |

Related corrections: UTC observation conversion with timezone validation, no
fabricated default detection score/count, cached/unknown map labels, durable speech
checkpoints, no priority clearing of camera STOP warnings by a route proposal,
and bounded/local persistence failures that remain explicit rather than claiming
recoverable submission. New CLI flags expose outbox location, polling, timeout and
submission attempt budget. Existing manual/camera demos remain available.

## Verification actually performed

- Full v3 regression suite: **244 tests passed, 2 subtests passed**. Two existing
  test collection/deprecation warnings; no failures.
- 31 new regression cases cover restart, corrupt/foreign state, disk failure,
  conflict/permanent/transient errors, stale/incomplete maps, alternative-edge
  closures, route weights, speech checkpoint/restart, independent rejection
  polling, episode rearming, identity matching and STOP queue preservation.
- `live_navigation.py --help` succeeds and exposes the new options.
- `git diff --check` succeeds.
- Final focused device-client/recovery run: **40 tests passed**. The original
  localhost mock demonstration also passed with a fresh isolated outbox; its
  printed speech is not audio evidence despite its legacy "LIVE" success label.
- `verify_device_backend_contract.py` passed over an ephemeral localhost HTTP
  service using actual Person 1 device code, Person 2 backend `63de1ad` and Person
  3 API client/controller `3750c0b`, without changing either teammate's code:
  - Synthetic JPEG/photo/report intake leaves the map at version 1 and route B-C-D.
  - Device restart restores the same submitted report without another submission.
  - Dashboard approval confirms version 2; laptop client computes B-E-F-D and
    records one speech call. Duplicate report retry returns its approved record.
  - Same-map client restart does not repeat that speech call.
  - Fresh isolated dashboard rejection leaves version 1 and B-C-D unchanged.
    Rejection is detected despite the unchanged version. A later monitor episode
    submits a distinct event successfully.

Run instructions are in [AWS_DEVICE_CLIENT_GUIDE.md](AWS_DEVICE_CLIENT_GUIDE.md).
The Node dashboard controller is exercised directly in the localhost check;
this does not constitute a new browser UI or accessibility test.

## Contract and remaining gates

The device intentionally retains Person 2's supported compact `/api/v2/photos`
and `/api/v2/reports` compatibility routes. It does not claim to implement the
canonical presign/direct-S3 flow. The backend verifies actual JPEG bytes; local
unit byte fixtures and mock-server checks are not real photo evidence.

The authoritative cloud JSON keeps `distance:null` and `distance_source:unmeasured`.
Its `route_weight` is converted to RouteMap's internal cost slot solely for graph
search; it is not a measurement or a claim of physical metres.

The local check uses explicit unauthenticated development mode, memory storage,
a generated synthetic JPEG and recorded speech **calls**, without audio hardware.
It proves neither JWT enforcement, AWS persistence, physical camera reporting nor
audible playback. Before live use, Person 2 must complete deployment/authentication,
the team must agree on evidence privacy/retention, and Persons 1–3 must run the
camera → AWS → human approval → laptop → audible recording acceptance cases.
The device does not perform automatic image redaction. No Bedrock, COOL, marker
localisation, corridor-clearance certification or safe walking claim is added.

Old context-free outboxes must be reconciled/migrated with the owner before reuse;
do not delete them to force new IDs. Stored evidence/metadata currently remain
local until deliberate owner cleanup. Keep outbox directories separate per API/
camera and preserve unresolved events during credential or network repairs.
