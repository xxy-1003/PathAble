# PathAble human-review dashboard (Person 3)

Application sign-in is now available. Read [AUTH_LOGIN.md](AUTH_LOGIN.md) for
reviewer/camera username-demo login, local configuration and session handling.
Use **http://localhost:8003/** for sign-in so the registered callback matches.

Standalone reviewer page for **camera report → human review → authoritative map**.
The legacy scripted `/api/v1` dashboard remains unchanged. This page uses the
published **`/api/v2` contract revision 1.1** on Person 2's `codex/aws-backend`
commit `63de1ad3a57a55608118c0b6a9d83844ce98f652`. No backend code is copied or
modified. See [HANDOFF.md](HANDOFF.md) and [ACCEPTANCE.md](ACCEPTANCE.md).

## Start with fixture practice

Requires Node.js 22+; no npm packages or AWS credentials.
From the repository root:

```powershell
node production/v3/cloud/reviewer/serve.mjs
```

Open <http://127.0.0.1:8003>. The server binds only to your laptop and serves an
explicit list of dashboard files. It does not expose the rest of the repository.
Stop it with Ctrl+C. This address is not a remote teammate demo link.

1. Leave **Fixture practice** selected. Select the pending B–C report.
2. Inspect the synthetic gray image and unknown measurements. Enter optional notes.
3. Choose Approve or Reject. The fixture map changes only after a simulated successful
   response. This is practice in browser memory, not a report sent to AWS.
4. Use **Connect / reset** for a fresh case. Use **Simulate connection failure**
   to check errors and retries. Approval is disabled until an image loads.

The fixture JSON and 629-byte JPEG are exact synthetic files from Person 2's
published contract. They are not corridor evidence.

## Connect to Person 2's deployed API

Obtain the approved API base address (including `/api/v2`) and the reviewer
application sign-in process from Person 2. An AWS console/CLI login is **not**
a reviewer application token. Do not use AWS secret access keys here.

1. Person 2 must allow the exact dashboard origin (locally
   `http://127.0.0.1:8003`) in the API's `DashboardOrigin` configuration. Do not
   change the backend's origin settings independently or widen them to `*`.
2. Sign in through the team's approved application identity provider to obtain
   an **access token** with `pathable/reviewer` scope and an allowlisted subject.
   Keep the token on your laptop; never paste it into chat or commit it.
3. Select **API connection**, enter the HTTPS API address and access token in the
   page, then Connect. Review the service status and selected report before deciding.
4. Refresh to fetch current reports and map state; use the status filter and Load
   more if needed. This dashboard uses manual refresh, not background polling.

The token is held only in page memory and cleared from the input after connection.
The Reviewer sign-in button uses Cognito managed login with PKCE. Only its temporary
transaction state/nonce/verifier uses sessionStorage; tokens are never stored there
or in localStorage. There is no automatic token refresh. On 401, sign in again or
reconnect with a fresh manually provided token. See AUTH_LOGIN.md for the complete
setup and the difference between clearing local credentials and provider logout.
The UI displays the reviewer identity returned in the saved server review; the
request body cannot choose a reviewer identity.

Images use a temporary private URL obtained via `/reports/{event_id}/photo`.
The API bearer token is never attached to an image request. Image requests send
no Referer. Expired, missing and failed images show a retry state; a stalled
image load times out after 15 seconds. URLs and image bytes are not persisted.
Do not make the S3 bucket public. The backend remains responsible for private
storage, authorised URLs, retention and image privacy handling.

No page status proves laptop map application, speech, surveyed distance or safe
corridor clearance. API mode also supports explicit localhost development and
labels that connection **NOT AWS**.

## Failures and concurrent reviews

- Approve/Reject, navigation and connection controls are disabled during a request.
- The page sends `{action, expected_map_version, notes}` using the displayed full
  map version. It changes review status only after a successful server response,
  then fetches the full authoritative map. A failed map read is labelled stale
  even if the review itself was confirmed saved.
- Timeout, 429 and 503 leave the decision unconfirmed. **Retry same decision**
  preserves the exact original body for the API's idempotency rules. Alternatively,
  Refresh reconciles current report/map state. Notes and other decisions are
  disabled until reconciliation or retry.
- A 409 requires Refresh and a deliberate new decision. The page never silently
  resubmits using a newer map version. A different terminal decision is forbidden.
- No report, pending state or failed request is shown as an approved closure.
  A shared edge without a closure is never described as physically clear.

## Verify

```powershell
node --test production/v3/cloud/reviewer/tests/reviewer.test.mjs
```

For a local browser/contract check, use a checkout containing Person 2's backend
and a Python environment with its `requirements-dev.txt` installed. Example
from this dashboard checkout, with a sibling backend checkout:

```powershell
& '..\pathable-person5\.venv\Scripts\python.exe' production/v3/cloud/reviewer/tests/local_contract_server.py --backend-root '..\pathable-person5'
```

That test helper runs **the actual backend app**, seeds a synthetic JPEG/report,
enables only the local dashboard origin and binds port 8002 on localhost. Storage
is deliberately in memory and local auth is disabled by the backend's development
mode. It is not suitable for remote hosting or AWS proof. No backend files change.

Connect the dashboard to `http://127.0.0.1:8002/api/v2`, leaving the token empty
for this local test only. Run HTTP contract checks with:

```powershell
node production/v3/cloud/reviewer/tests/local-api-smoke.mjs
```

The smoke check creates synthetic local reports and reviews. Restart the test
helper for an isolated map before filming a fresh approval/rejection case.

For team hosting, publish only the static dashboard files through the team's
approved HTTPS host. Hosting, TLS, application sign-in and API deployment must be
coordinated with Person 2. No public deployment was performed in this workstream.
