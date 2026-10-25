# Human-review contract additions — revision 1.1

Integration inspected: `e9e0046ef7851d54c5e2214a1a50638544fdc503` (25 October 2026).
Backend branch before these additions: `2f46dc9`. Do not change dashboard or
camera files on this branch.

## Route decision — tell client implementers before integration

Use the dedicated `/api/v2` service. Proposed `/api/v1` route reuse would conflict
with legacy tickets/maps that can apply holds before approval. This package
preserves that legacy workflow. No `/api/v1` alias is introduced.

New canonical flow:

1. `POST /api/v2/uploads/presign` with `{client_id, content_type:"image/jpeg",
   size_bytes, sha256}`. Response: `{photo_id, method:"PUT", url, headers,
   expires_in:300}`. `sha256` is lowercase hex of the exact JPEG bytes. Accept
   JPEG only, 1–524288 bytes, up to 20 megapixels, privacy-reviewed by the client.
2. PUT those exact bytes to `url` using returned headers. For a browser, let it
   supply Content-Length from the Blob; never send the API bearer token to S3.
   S3 enforces checksum and no-overwrite. URLs expire in 300 seconds. On 403
   expiry, request another upload slot. A lost successful PUT response may be
   retried: 412 means the immutable object already exists; submit the report to
   verify it. An unused slot never creates a report or ticket.
3. `POST /api/v2/reports` with the canonical request below. Backend verifies the
   assigned client/location, photo ownership, actual object bytes, size, JPEG
   structure and checksum. It stores one PENDING report/ticket together in one
   DynamoDB item; no map mutation. A report ID is the event ID.
4. `GET /api/v2/reports/{event_id}` returns current state to the configured
   camera or a reviewer. `GET /api/v2/tickets?status=PENDING` lists tickets, and
   `GET /api/v2/tickets/T-{event_id}` returns the corresponding report/ticket.
5. Reviewer sends `POST /api/v2/tickets/T-{event_id}/review` with
   `{action:"APPROVE", expected_map_version:1, notes:"Reviewed evidence image"}`.
   Response: `{report:<reviewed report/ticket>, map_version:2}`. Only approval
   blocks B-C; rejection records REJECTED and leaves the map unchanged.
6. Person 1 polls `/api/v2/map/version`, downloads `/api/v2/map` on a newer
   version, applies the graph and handles local rerouting and speech.

```json
{
  "schema_id": "pathable.human-review.report.v1",
  "event_id": "106ec786-00f6-4f97-819d-01b492ae0768",
  "client_id": "camera-b-01",
  "timestamp": "2026-10-25T09:00:00Z",
  "edge_key": "B-C",
  "junction": "B",
  "destination": "D",
  "detection_evidence": {
    "obstacle_class": "chair", "confidence": 0.85,
    "overlap_count": 6, "frame_count": 10,
    "evidence_status": "client_reported"
  },
  "image": {"photo_id": "67282b30-5afc-4eee-bd01-b55de06c6298", "sha256": "<64 lowercase hex characters>"},
  "distance_m": null,
  "clearance_m": null,
  "measurement_source": null
}
```

The timestamp must be UTC. Detection fields are client reports, not verified
cloud observations or surveyed persistence history. New responses include
`event_id`, `client_id`, `schema_id`, `timestamp`, `junction`, `destination`,
`image`, `detection_evidence`, `ticket_id`, `status`, `received_at`,
`expected_map_version`, and nullable `review`. Existing compact fields
(`report_id`, `camera_id`, `observed_at`, `photo_id`, flat detection fields) and
the base64 `/photos` route remain supported for compatibility. New clients use
the canonical schema above. The compact input is explicitly a legacy format;
it does not establish missing measurements or cloud-observed evidence.

## Authentication, states and retries

Use the same JWT bearer scopes and camera/reviewer subject restrictions as
[CONTRACT.md](CONTRACT.md). Upload/report submission needs `pathable/camera`;
ticket reads/reviews need an allowlisted `pathable/reviewer`. Individual report
status permits the configured camera as well. The body cannot assign reviewer
identity. AWS credentials are never sent by the camera or dashboard.

States are exactly PENDING, APPROVED, REJECTED. Identical event retry returns 200
and the existing report/ticket; first submission returns 201. Same ID with a
different normalized payload returns 409. Duplicate review by the same reviewer,
with the same action/version/notes, returns the stored result without another
map increment. Review is terminal; stale/concurrent different reviews return
409. Rejection cannot reopen another approved closure. No automatic reopening.

Map/version JSON and unknown measurements follow CONTRACT.md. All distance
values stay null; route weights are abstract. Approval is not a safety claim.

Retry network failures, 429 and 503 with backoff and the same event ID. Refresh
state on 409 before an intentional new decision. Renew sign-in on 401; correct
permissions on 403 (API). Correct 413/422 payload errors; missing image is 422.
Photo retention ended is 410. A successful template/mock test is not deployed
AWS evidence. `fixtures/examples.json` contains synthetic request/response
fixtures; its JPEG is a generated gray image, not camera or corridor evidence.

## Retention and privacy

Current proposed retention is seven days for photos, with report/review metadata
retained until deliberate cleanup. Confirm with the account/project owner before
live uploads. The backend verifies images but does not redact them. Do not claim
redaction or consent verification occurred automatically. Tokens, signed URLs,
image bytes and reviewer notes are excluded from structured operational logs.
