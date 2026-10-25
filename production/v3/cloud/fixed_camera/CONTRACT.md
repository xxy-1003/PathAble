# Fixed-camera API contract v1.0

Published contract for Person 1 (camera and laptop), Person 2 (backend), and
Person 3 (reviewer dashboard). Base path: `/api/v2`. This is a separate service
from the legacy `/api/v1` slow-loop workflow. AWS deployment is not yet verified.

## Workflow and ownership

1. Person 1 uploads a privacy-reviewed JPEG, then submits a report referencing it.
2. Backend stores the photo privately and creates a `PENDING` report. Intake does
   **not** change the shared map.
3. Person 3 displays pending reports and a temporary private photo URL, then sends
   `APPROVE` or `REJECT` with the report's `expected_map_version`.
4. Only `APPROVE` blocks B-C in the shared map and increments its version.
   `REJECT` leaves the map unchanged; it never reopens an existing block.
5. Person 1 polls map version (suggested every 3 seconds), downloads a newer full
   map, applies it, reroutes locally, and speaks once per applied version.
   On network failure retain the last known map and show a stale/offline state.

Fixed placement is server configuration: `CAMERA_ID=camera-b-01`,
`CAMERA_NODE=B`, `CAMERA_EDGE=B-C`. The local development defaults match these.
Camera location is not junction-marker localisation. Camera identities
must agree with configuration; clients cannot choose another edge. No COOL,
Bedrock, metric inference, automatic expiry, or automatic reopening in this API.
Human approval records a reported obstruction, not measured corridor clearance
or certified walking safety. Local safety decisions remain on the laptop.

## Authentication

AWS uses API Gateway JWT authorisation. Send `Authorization: Bearer <access token>`.
Tokens must contain `pathable/camera`, `pathable/reviewer`, or `pathable/map` scope
as listed below. Reviewer identity comes from authenticated `sub`, never from a
request body and must be in the server `ReviewerSubjects` allowlist. Camera token
`sub` must match server `CameraSubject` configuration.
No AWS secret keys belong in the camera client or dashboard. Local mode is
explicitly unauthenticated and must bind only to `127.0.0.1`.

## Endpoints

| Method and path | Scope | Request / response |
| --- | --- | --- |
| GET `/health` | any configured scope | storage mode, version; no deployment claim |
| POST `/photos` | camera | `{camera_id, jpeg_base64}` -> `201 {photo_id, sha256}` |
| POST `/reports` | camera | example below -> `201` report; identical retry `200` |
| GET `/reports?status=PENDING&limit=50&cursor=...` | reviewer | `{items, next_cursor}`; omit status for all |
| GET `/reports/{report_id}` | reviewer | report including current review state |
| GET `/reports/{report_id}/photo` | reviewer | `{url, expires_in:300}`; private, do not log URL |
| POST `/reports/{report_id}/review` | reviewer | `{action, expected_map_version, notes}` -> report and map version |
| GET `/map/version` | map or reviewer | `{map_id:"prototype", version}` |
| GET `/map` | map or reviewer | full map described below |

Maximum decoded JPEG: 512 KiB. Photo upload retries may create another photo;
unused photos expire after seven days. Photos are immutable, randomly named and
private. Upload before report; report cannot reference another camera's photo.
Do not upload faces or personal information without suitable privacy handling.

Example report (UUID chosen once and reused unchanged for retries):

```json
{
  "report_id": "106ec786-00f6-4f97-819d-01b492ae0768",
  "camera_id": "camera-b-01",
  "photo_id": "67282b30-5afc-4eee-bd01-b55de06c6298",
  "observed_at": "2026-10-25T09:00:00Z",
  "obstacle_class": "chair",
  "confidence": 0.85,
  "overlap_count": 6,
  "frame_count": 10,
  "distance_m": null,
  "clearance_m": null,
  "measurement_source": null
}
```

For this camera-region phase, all three measurement fields must be `null`.
Pixel overlap is evidence of a region overlap, not a distance or clearance.
`observed_at` must include a timezone. Reports include server `received_at`,
`node:"B"`, `edge_key:"B-C"`, `status`, `expected_map_version`, and nullable
`review`. Review stores authenticated reviewer, timestamp, action and notes.
Identical report retry returns its current state; changed body with same ID is
`409`. Single report review is terminal: same reviewer/action/version/notes retry returns
the same result; changed decision returns `409`. Stale expected map version is
`409`; fetch the map and report again before a deliberate resubmission.

Full map: `{map_id, version, nodes, edges}`. Nodes are A-F. Each undirected edge
contains `{from, to, distance:null, distance_source:"unmeasured",
route_weight:1, blocked:false}`. These weights choose a prototype route without
claiming surveyed metres. Do not interpret `blocked:false` as physical clearance.
B-C is blocked on approval, leaving B-E-F-D as the alternate graph route.
No marker or physical clearance claims may be inferred from this graph.

Errors use `{detail:...}` (gateway auth errors may use `{message:...}`):
`401/403` unauthenticated/forbidden, `404` unknown
resource, `409` conflict, `413` oversized photo, `422` invalid payload, `503`
storage unavailable, `410` photo retention ended. Retry timeouts/503 with backoff and the same report ID.
Never announce a successful map update before a successful API response.

## Status and evidence

Contract was published ahead of implementation so clients could work in parallel.
The implementation's generated `openapi.json` provides field-level schemas.
AWS proof must separately record stack outputs, authenticated upload/report/
review calls, cross-process durable reads and laptop sync evidence. A template,
local test or simulated storage is not deployed AWS evidence.
