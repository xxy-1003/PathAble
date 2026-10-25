# Person 3 handoff

Working branch: `codex/aws-review-dashboard`.

Integration base, fetched and inspected on 25 October 2026:
`e9e0046ef7851d54c5e2214a1a50638544fdc503`.
The final commit is the commit containing this handoff; retrieve it with
`git log -1 --format=%H -- production/v3/cloud/reviewer` (also reported in the chat).
No merge into integration or main was performed.

## Files and ownership

All changes are under `production/v3/cloud/reviewer/`:

- `index.html`, `reviewer.css`, `dashboard.mjs`: accessible reviewer page, modes,
  private-image loading/retry, notes, filters, errors, authoritative map display.
- `api.mjs`: dedicated `/api/v2` HTTP client, endpoint/response checks and labels.
- `controller.mjs`: confirmed review state, request locking, identical retry and
  stale-map handling. It never mutates map edges locally.
- `fixture.mjs`, `fixtures.json`, `synthetic.jpg`: clearly labelled browser-memory
  practice. JSON/JPEG copied exactly from Person 2's synthetic contract fixtures.
- `serve.mjs`: localhost static preview, no API proxy.
- `tests/reviewer.test.mjs`: 16 focused tests.
- `tests/local_contract_server.py`: optional localhost helper importing Person 2's
  existing app with in-memory synthetic data, no backend code edits.
- `tests/local-api-smoke.mjs`: six actual localhost API contract checks.
- `README.md`, `ACCEPTANCE.md`, this file: launch, contract assumptions, actual
  outcomes, remaining gates and recording instructions.

Backend, camera/client modules, legacy dashboard, unrelated modules and main were
left unchanged. The previous backend checkout and its uncommitted AGENTS.md toolkit
setup change were preserved in place. Parent `sources/` was not modified.

## Contract decision and assumptions for Person 2

Source: `codex/aws-backend` at `63de1ad3a57a55608118c0b6a9d83844ce98f652`,
`production/v3/cloud/fixed_camera/HANDOFF.md` revision 1.1, `CONTRACT.md`,
`models.py` and `app.py`. The brief's expected `/api/v1` paths are superseded by
the already published dedicated `/api/v2` contract because v1 has legacy semantics.

| Operation | Exact agreed endpoint / body |
| --- | --- |
| Health | GET `/api/v2/health` |
| List reports | GET `/api/v2/tickets?status=PENDING&limit=50&cursor=...`; `{items,next_cursor}` |
| Inspect ticket | GET `/api/v2/tickets/T-{event_id}` |
| Private image | GET `/api/v2/reports/{event_id}/photo`; `{url,expires_in}` |
| Review | POST `/api/v2/tickets/T-{event_id}/review`; `{action:"APPROVE" or "REJECT",expected_map_version,notes}` |
| Review result | `{report,map_version}` with PENDING/APPROVED/REJECTED report status |
| Map | GET `/api/v2/map` and `/api/v2/map/version` |

No frontend-generated reviewer ID is sent. AWS requests use a reviewer access JWT;
the backend verifies subject allowlist/scope. The saved review's `reviewer_id` is
displayed after confirmation. Dashboard origin and reviewer application sign-in
are deployment prerequisites, not facts inferred from AWS console sign-in.

Canonical event/ticket fields and unknown measurements follow the published fixture.
The dashboard sends the currently displayed map version for a deliberate review;
409 requires refresh/reinspection. It never silently refreshes and retries a changed
body. Duplicate/ambiguous retries preserve the original body.

## Coordination needed before live demonstration

Person 2 supplies/deploys the authorised API, identity-provider/app-client sign-in
process, exact CORS dashboard origin and durable private storage. This version has
manual access-token entry; it does not implement managed-login/PKCE without the
team's issuer, client ID and callback configuration. Do not use AWS keys as a shortcut.

Person 1 supplies the event/image and independently applies the shared map, route
and speech. The dashboard makes no claim that a laptop received a map just because
the review succeeded. Checklist A–G and final recording remain coordinated live gates.

No messages were sent to teammates, deployment performed, public evidence uploaded,
or integration merged. Review/coordinate these changes with both owners before
merging into `codex/pathable-v3`. The local actual-API check requires Person 2's
backend checkout; integration alone does not yet contain that package.
