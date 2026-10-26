# Username-demo sign-in verification — 25 October 2026

Source branch: `codex/aws-review-login`, based on dashboard `3750c0b`.

- **22 Node tests passed**: existing 16 reviewer behaviour tests plus six focused
  authentication checks for code/PKCE configuration, token-store separation,
  role/scope validation, expiry, API destination pinning and permitted origins.
- JavaScript syntax checks passed. `git diff --check` passed.
- Cognito's API confirmed two enabled users, `reviewer-demo` and `camera-demo`,
  both in CONFIRMED state with no email attributes. Invitations were suppressed.
  Random strong passwords were generated on the operator laptop and supplied
  through the authorised AWS API, never copied into source or chat output.
- The local operator credential file is outside Git and has Windows inheritance
  removed, with access granted to the current Windows user. It is not served by
  the dashboard's explicit file allowlist.
- The local public auth settings were switched to the username-only demo pool
  and no longer request an email scope. Browser navigation from the Reviewer
  sign-in button reached Cognito's managed login with **Username** and Password
  fields, code response type, S256 challenge, nonce/state and the registered
  `http://localhost:8003/callback.html` return address.
- Password entry and completed sign-in for the new demo users have not been
  browser-tested in this verification. CONFIRMED state alone is not an end-to-end
  token/API authorisation test. The earlier email accounts/pools are preserved.

The API address is still empty in local auth configuration because the backend
has not been deployed. Signing in does not turn fixture data into AWS data. Real
JWT enforcement, reviewer/camera separation at the deployed API, S3/DynamoDB
durability, camera uploads and audible reroute recording remain unverified.

No public website was hosted. The Node preview binds only to the demo laptop.
Only the Cognito login service is AWS-hosted in this step. No email recovery is
available for these username demo identities; administrator reset is required.
