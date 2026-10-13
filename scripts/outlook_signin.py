"""Sign in to a Microsoft mailbox once, to get the token the mailbox intake keeps.

    MAILBOX_CLIENT_ID=<application id> uv run python scripts/outlook_signin.py

Outlook.com and Microsoft 365 take no password for IMAP, only a token from signing in. This asks
Microsoft for a short code, shows you where to type it, waits while you sign in and consent in your own
browser, and writes the refresh token to .outlook-token (readable by you only, not in git). Nothing is
printed that is secret. MAILBOX_TENANT defaults to "common"; use "consumers" for a personal
Outlook.com account or the tenant's id for a work one. docs/MAILBOXES.md says how to register the
application the id belongs to.
"""

import os
import sys
import time
from pathlib import Path

import httpx

SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
KEPT = Path(__file__).resolve().parents[1] / ".outlook-token"


def main():
    client_id = os.environ.get("MAILBOX_CLIENT_ID")
    if not client_id:
        sys.exit("Set MAILBOX_CLIENT_ID to the id of the application you registered. See docs/MAILBOXES.md.")
    base = f"https://login.microsoftonline.com/{os.environ.get('MAILBOX_TENANT', 'common')}/oauth2/v2.0"
    with httpx.Client(timeout=30) as web:
        asked = web.post(f"{base}/devicecode", data={"client_id": client_id, "scope": SCOPE}).json()
        if "device_code" not in asked:
            sys.exit(f"Microsoft would not start a sign-in: {asked.get('error_description', asked)}"[:400])
        print(f"Open {asked['verification_uri']} and enter the code {asked['user_code']}")
        print("Sign in as the mailbox's owner and agree to let the application read mail. Waiting...")
        deadline = time.time() + int(asked.get("expires_in", 900))
        while time.time() < deadline:
            time.sleep(int(asked.get("interval", 5)))
            granted = web.post(
                f"{base}/token",
                data={
                    "client_id": client_id,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": asked["device_code"],
                },
            ).json()
            if granted.get("refresh_token"):
                KEPT.write_text(granted["refresh_token"])
                KEPT.chmod(0o600)
                print(f"Signed in. The token is in {KEPT.name}; scripts/mailbox_check.py will find it there.")
                return
            if granted.get("error") not in ("authorization_pending", "slow_down"):
                sys.exit(f"Microsoft refused: {granted.get('error_description', granted.get('error'))}"[:400])
    sys.exit("The code expired before the sign-in was finished. Run this again.")


if __name__ == "__main__":
    main()
