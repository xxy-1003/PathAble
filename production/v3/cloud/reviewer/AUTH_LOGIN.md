# Local application login

The dashboard supports Cognito managed login through a public app client with
authorization code + PKCE. It requires no app-client secret or AWS access keys.
The default preview remains a clearly labelled fixture; signing in alone does
not mean reports/maps are connected to a deployed AWS backend.

## Operator steps

1. Start `node production/v3/cloud/reviewer/serve.mjs` from the repository root.
2. Open **http://localhost:8003/** on the demo laptop. The registered development
   callback is **http://localhost:8003/callback.html**. Use `localhost` consistently;
   browser sign-in transaction storage is bound to that origin.
3. Choose **Reviewer sign-in** and use `reviewer-demo`, or **Camera / laptop sign-in**
   and use `camera-demo`. These are distinct demo users with no email attributes.
   Passwords are private local operator material, outside this repository.
4. After login, Cognito returns to the same local dashboard. Reviewer credentials
   connect automatically only when the configured API address is available.
   The backend still enforces the exact reviewer/camera subject allowlists.
5. For the camera client, **Copy camera access token** is an explicit user action.
   On that laptop, `$env:PATHABLE_AUTH_TOKEN = Get-Clipboard` transfers it to the
   process environment without putting the token text in shell history. Clear
   the clipboard afterward. Do not paste credentials/tokens into chat, source,
   notes, recordings or logs. The camera token cannot become dashboard reviewer
   credentials. Follow Person 1's client launch instructions separately.

No public website hosting is required. Cognito itself is an AWS-hosted login
service, and the planned API/storage still require deployment to AWS.

## Public configuration and build

Copy `auth-config.example.json` to ignored `auth-config.local.json`, supplying
the user-pool issuer, public client ID, exact login origin and approved backend
API address ending in `/api/v2`. Never add a client secret. An empty `apiBase`
allows sign-in verification but no automatic connection to a backend.

The local preview serves that file as `auth-config.json`; it never serves private
credential files or `node_modules`. A hosted version is outside this local-demo
scope. A deployed API must allow the exact origin `http://localhost:8003`.

`oidc-client-ts` 3.5.0 is bundled locally; there are no external CDN scripts.
Dependencies and build tool versions are pinned in `package-lock.json`.
To reproduce the checked-in browser bundle:

```powershell
cd production/v3/cloud/reviewer
npm ci
npm run build:auth
npm test
```

## Session handling

- The maintained OIDC library handles PKCE, one-time state, callback processing
  and nonce checking. No custom JWT decoder substitutes for protocol checks.
- Only the temporary PKCE/state/nonce transaction is kept in sessionStorage.
  Access, ID and refresh tokens remain in page memory and are not stored in
  localStorage/sessionStorage, URLs, logs or source configuration.
- The callback query is removed from the address bar before processing. Errors
  use generic messages instead of echoing codes, tokens or signed URLs.
- Reviewer credentials are sent automatically only to the configured API.
  An edited API address cannot silently receive the signed-in token.
- Reloading or **Clear local sign-in** discards the local session. This button
  is not global Cognito logout. Sign-in explicitly prompts for login so the
  operator can choose the right reviewer/camera account.
- Access tokens expire after 15 minutes in the demo setup. Automatic refresh
  is disabled. Sign in again when needed; the current camera client must be
  restarted with a fresh environment token when its credentials expire.

## Demo account scope and evidence

The username-only pool is a controlled demonstration setup with self-signup
disabled and no email/SMS recovery. An administrator must reset lost credentials.
The previous email-based pools/users are preserved. No invitation messages are
sent for the username-only users. MFA is not enabled for these demo identities;
this is not a production identity/security configuration.

Sign-in tests do not establish deployed API authorisation, durable storage,
camera reporting, map synchronisation or audible speech. Those require the
coordinated acceptance checklist after backend deployment. Never record a
password, a token or the private operator credential file as demo evidence.
