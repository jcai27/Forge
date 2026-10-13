"""Prove the mailbox intake against a real mailbox, changing nothing in it.

    cd apps/api && uv run python ../../scripts/mailbox_check.py connect   # then send the mailbox an invoice
    cd apps/api && uv run python ../../scripts/mailbox_check.py check     # take it in, show it processed
    cd apps/api && uv run python ../../scripts/mailbox_check.py newest    # or: the newest attachment already there
    cd apps/api && uv run python ../../scripts/mailbox_check.py disconnect

Credentials come from the environment and are never printed (see docs/MAILBOXES.md for how to get them):

    MAILBOX_HOST       imap.gmail.com, outlook.office365.com, ...
    MAILBOX_USER       the mailbox's address
    MAILBOX_PASSWORD   an app password, for Gmail and most servers
    MAILBOX_CLIENT_ID  for a Microsoft mailbox instead of a password: the registered application's id,
    MAILBOX_TENANT     its tenant (default "common"), and the refresh token in MAILBOX_REFRESH_TOKEN or in
                       .outlook-token as scripts/outlook_signin.py leaves it

The app must be running. It signs in to a workspace that has an invoice agent (FACTORY_EMAIL and
FACTORY_PASSWORD; by default the Steel City Diners demo login) and uses that workspace's own mailbox
channel, so what is proven is the product's path, not a copy of it.

connect opens the mailbox once to prove the details and note where it stands: only mail arriving after
that is ever read. Send the mailbox one email with an invoice attached, from anywhere, then run check.
newest is for when no new mail can be sent: it reads up to the 30 newest messages, read-only, and puts
the newest PDF or image through the same agent as an upload would.

Either way the flags of every message are read before and after, and must be the same: nothing is
marked as read, moved or deleted.
"""

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from factory.mailbox import MailboxError, _position, check_mailbox, connect  # noqa: E402

STATE = ROOT / ".mailbox-check.json"
NEEDED = "Set MAILBOX_HOST, MAILBOX_USER and MAILBOX_PASSWORD (or MAILBOX_CLIENT_ID with a refresh token). See docs/MAILBOXES.md."


def details():
    host, user = os.environ.get("MAILBOX_HOST"), os.environ.get("MAILBOX_USER")
    client_id = os.environ.get("MAILBOX_CLIENT_ID")
    token_file = ROOT / ".outlook-token"
    secret = os.environ.get("MAILBOX_PASSWORD")
    if client_id:
        secret = os.environ.get("MAILBOX_REFRESH_TOKEN") or (
            token_file.read_text().strip() if token_file.exists() else None
        )
    if not (host and user and secret):
        sys.exit("No mailbox credentials in the environment, so nothing was contacted. " + NEEDED)
    config = {"host": host.strip().lower(), "username": user, "folder": os.environ.get("MAILBOX_FOLDER", "INBOX")}
    if client_id:
        config.update(auth="microsoft", client_id=client_id, tenant=os.environ.get("MAILBOX_TENANT", "common"))
    return config, secret


def flags(config, secret):
    """Every message's flags, by UID, read without changing them."""
    client = connect(config, secret)
    try:
        status, data = client.uid("FETCH", "1:*", "(FLAGS)")
        found = {}
        for item in data or []:
            text = item.decode(errors="replace") if isinstance(item, bytes) else ""
            if "UID " in text:
                found[text.split("UID ")[1].split()[0].rstrip(")")] = text[text.find("FLAGS") :]
        return found, _position(client, config)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def workspace(api):
    login = {
        "email": os.environ.get("FACTORY_EMAIL", "steel@demo.test"),
        "password": os.environ.get("FACTORY_PASSWORD", "steelcity"),
    }
    session = api.post("/auth/login", json=login)
    if session.status_code != 200:
        sys.exit("Could not sign in to the workspace. Set FACTORY_EMAIL and FACTORY_PASSWORD.")
    api.headers["Authorization"] = "Bearer " + session.json()["token"]
    operation = next((item for item in api.get("/portal/me").json()["operations"] if item["kind"] == "invoice"), None)
    if operation is None:
        sys.exit("That workspace has no invoice agent to send the document through.")
    return operation


def shown(api, document_id):
    document = api.get(f"/portal/documents/{document_id}").json()
    answer = document.get("answer") or {}
    print(
        f"  {document['name']}: {document['status']}, {document['stage']}, from {document['sender'] or document['source']}"
    )
    print(
        "  read as: "
        + ", ".join(f"{key} {value}" for key, value in answer.items() if not isinstance(value, list))[:300]
    )
    for item in document.get("exception_list", []):
        print(f"  held: {item['message']}")
    return document["status"] == "processed"


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("connect", "check", "newest", "disconnect"):
        sys.exit(__doc__)
    config, secret = details()
    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=600) as api:
        operation = workspace(api)
        try:
            if action == "connect":
                body = {
                    "kind": "mailbox",
                    "name": "Mailbox check",
                    "host": config["host"],
                    "username": config["username"],
                    "password": secret,
                    "folder": config["folder"],
                }
                if config.get("auth"):
                    body.update(client_id=config["client_id"], tenant=config["tenant"])
                made = api.post(f"/portal/operations/{operation['id']}/channels", json=body)
                if made.status_code != 201:
                    sys.exit(
                        f"The mailbox could not be connected: {made.json().get('error', {}).get('message', made.text)}"
                    )
                STATE.write_text(json.dumps({"channel": made.json()["id"]}))
                print(f"Connected {config['username']} on {config['host']}, read-only. Nothing in it was read.")
                print("Now send that mailbox one email with an invoice attached (a PDF or a photo), then run: check")
            elif action == "check":
                if not STATE.exists():
                    sys.exit("Run connect first.")
                before, _ = flags(config, secret)
                taken = api.post(f"/portal/channels/{json.loads(STATE.read_text())['channel']}/check", json={})
                if taken.status_code != 200:
                    sys.exit(f"The check failed: {taken.text[:300]}")
                print(f"{taken.json()['taken_in']} new document(s) taken in.")
                documents = api.get(f"/portal/operations/{operation['id']}/documents", params={"limit": 20}).json()[
                    "items"
                ]
                arrived = [item for item in documents if item["source"] == "mailbox"][
                    : max(1, taken.json()["taken_in"])
                ]
                done = all([shown(api, item["id"]) for item in arrived]) if taken.json()["taken_in"] else False
                after, _ = flags(config, secret)
                same = all(after.get(uid) == value for uid, value in before.items())
                print(
                    "The mailbox is as it was: no message was marked, moved or deleted."
                    if same
                    else "FLAGS CHANGED: "
                    + str({uid: (before[uid], after.get(uid)) for uid in before if after.get(uid) != before[uid]})
                )
                sys.exit(0 if done and same else 1)
            elif action == "newest":
                before, position = flags(config, secret)
                rewound = {"validity": position["validity"], "uid": max(0, position["uid"] - 30)}
                _, files = check_mailbox(config, secret, rewound, 30)
                after, _ = flags(config, secret)
                same = all(after.get(uid) == value for uid, value in before.items())
                if not files:
                    sys.exit("None of the 30 newest messages has a PDF or image attached.")
                item = files[-1]
                print(f"Newest attachment: {item['name']} from {item['sender']} ({len(item['data']):,} bytes)")
                kind = "application/pdf" if item["data"][:5] == b"%PDF-" else "image/jpeg"
                made = api.post(
                    f"/portal/operations/{operation['id']}/documents",
                    files={"file": (item["name"], item["data"], kind)},
                )
                done = made.status_code == 201 and shown(api, made.json()["id"])
                print("The mailbox is as it was: no message was marked, moved or deleted." if same else "FLAGS CHANGED")
                sys.exit(0 if done and same else 1)
            else:
                if STATE.exists():
                    api.delete(f"/portal/channels/{json.loads(STATE.read_text())['channel']}")
                    STATE.unlink()
                print("Disconnected. The stored password or token is gone with the channel.")
        except MailboxError as error:
            sys.exit(f"The mailbox could not be read: {error}")


if __name__ == "__main__":
    main()
