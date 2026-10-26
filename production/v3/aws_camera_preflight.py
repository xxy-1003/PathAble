"""Check camera credentials and saved state without uploading photos or reports."""
import argparse
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from aws_device_client import AwsDeviceClient, RequestRejected


def preflight(api_url, outbox_dir, token):
    token = (token or "").strip()
    # Format check only. The API verifies the JWT signature, expiry and access.
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise RequestRejected("A camera access token is required. Use Camera / laptop sign-in, then Copy camera access token. Paste it into the launcher's hidden prompt, not into chat.")
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise RequestRejected("Use the HTTPS API base address without /api/v2; the launcher adds that prefix.")
    client = AwsDeviceClient(api_base_url=api_url, auth_token=token,
                             outbox_dir=Path(outbox_dir), http_timeout_s=12)
    if client._recovery_error:
        raise RequestRejected(client.last_error or "Saved camera state could not be recovered. Preserve this outbox and inspect it before retrying.")
    code, body = client._http_request("GET", "/map/version")
    if code != 200:
        client._raise_api_error("Camera sign-in check", code)
    if (not isinstance(body, dict) or body.get("map_id") != "prototype" or
            type(body.get("version")) is not int or body["version"] < 1):
        raise RequestRejected("The API returned an invalid map version. Camera upload has not started.")
    pending = sum(r.status == "PENDING" and not r.submitted_at for r in client._reports.values())
    return body["version"], pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--outbox-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        version, pending = preflight(args.api_url, args.outbox_dir, os.getenv("PATHABLE_AUTH_TOKEN"))
    except (ConnectionError, OSError, ValueError) as err:
        # Only our safe transport/validation messages are shown; never a token.
        message = str(err) if isinstance(err, ConnectionError) else "Could not read camera configuration or saved state."
        print("Camera not started: " + message)
        return 1
    print(f"AWS map access confirmed (version {version}). Camera permission is checked on upload.")
    if pending:
        print(f"{pending} saved unsent report(s) will be retried with their existing IDs.")
    print("No photo or report was uploaded by this connection check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
