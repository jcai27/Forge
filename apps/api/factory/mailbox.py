"""Reading a mailbox for documents.

A customer connects the mailbox their invoices arrive in. It is opened over IMAP with TLS on the
standard port, read-only, and only for mail that arrived after it was connected: the position is a
message UID kept on the channel, and nothing older is ever fetched. Messages are not marked, moved
or deleted.

The server name is the customer's to type, so it is treated like any other outbound address: every
address it resolves to must be public, and the connection is made to the address that was checked,
with the certificate still verified against the name.

Two ways of signing in. Most servers, Gmail among them, take the account name and a password made for
one application (an "app password"). Microsoft's do not, for Outlook.com or Microsoft 365: they take
only a short-lived token got with OAuth, so for those the stored secret is a refresh token and each
check trades it for an access token first. See docs/MAILBOXES.md.
"""

import asyncio
import email
import imaplib
import re
import socket
import ssl
from email.header import decode_header, make_header
from email.utils import parseaddr

from factory.http_transport import pinned_client, public_addresses

PORT = 993
TIMEOUT = 20
MAX_MESSAGE_BYTES = 25_000_000
MAX_FILE_BYTES = 10_000_000
# A picture placed in the body of a message smaller than this is a logo or a signature, not a document.
INLINE_IMAGE_BYTES = 100_000
MICROSOFT_LOGIN = "login.microsoftonline.com"
MICROSOFT_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
FILE_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg")


class MailboxError(Exception):
    """The mailbox could not be read. The message is for the person who connected it."""


class PinnedIMAP(imaplib.IMAP4_SSL):
    """IMAP over TLS to an address that was checked, verifying the certificate against the name."""

    def __init__(self, host, address):
        self.address = address
        super().__init__(host, PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self.address, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def microsoft_token(config, refresh_token):
    """Trade a Microsoft refresh token for an access token: (access token, the refresh token to keep).

    Microsoft may hand back a new refresh token with each trade; the newest is the one to keep. The request
    goes through the pinned transport like any other outbound call, and is made once.
    """
    tenant = str(config.get("tenant") or "common")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", tenant):
        raise MailboxError("The Microsoft tenant is not a tenant name or id")
    url = f"https://{MICROSOFT_LOGIN}/{tenant}/oauth2/v2.0/token"
    form = {
        "client_id": str(config.get("client_id") or ""),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": MICROSOFT_SCOPE,
    }

    async def trade():
        async with pinned_client(url, [MICROSOFT_LOGIN], timeout=TIMEOUT) as client:
            return await client.post(url, data=form)

    try:
        response = asyncio.run(trade())
        granted = response.json() if response.status_code == 200 else {}
    except Exception:
        raise MailboxError("Microsoft's sign-in service could not be reached") from None
    if not granted.get("access_token"):
        raise MailboxError(
            "Microsoft did not accept the sign-in. The consent may have expired or been withdrawn: sign in again "
            "and connect the mailbox afresh."
        )
    return granted["access_token"], granted.get("refresh_token") or refresh_token


def _refused(error):
    """Why a server turned a sign-in down, in words for the person connecting it, from what the server said."""
    said = str(error).lower()
    if "application-specific password" in said or "app password" in said:
        return "This account needs an app password, not its ordinary password. Create one in the account's security settings."
    if (
        "basicauthblocked" in said
        or "basic authentication" in said
        or "authenticate failed" in said
        and "outlook" in said
    ):
        return "This server no longer takes passwords. Outlook and Microsoft 365 mailboxes are connected by Microsoft sign-in."
    if "imap" in said and ("disabled" in said or "not enabled" in said):
        return "IMAP is switched off for this account. Turn it on in the mail settings, or ask your administrator."
    return "The mail server refused the account name or password"


def connect(config, password):
    host = str(config.get("host", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
        raise MailboxError("The mail server must be a host name, such as imap.example.com")
    try:
        addresses = public_addresses(socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM))
    except (OSError, ValueError):
        raise MailboxError("The mail server could not be found, or is not a public address") from None
    try:
        client = PinnedIMAP(host, addresses[0])
    except (OSError, ssl.SSLError, imaplib.IMAP4.error):
        raise MailboxError("The mail server did not accept a secure connection on port 993") from None
    client.kept_secret = password
    try:
        if config.get("auth") == "microsoft":
            access, client.kept_secret = microsoft_token(config, password)
            proof = f"user={config['username']}\x01auth=Bearer {access}\x01\x01".encode()
            client.authenticate("XOAUTH2", lambda _: proof)
        else:
            client.login(config["username"], password)
    except MailboxError:
        client.shutdown()
        raise
    except imaplib.IMAP4.error as error:
        client.shutdown()
        raise MailboxError(_refused(error)) from None
    try:
        status, _ = client.select(_quoted(config.get("folder") or "INBOX"), readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error("select")
    except imaplib.IMAP4.error:
        client.logout()
        raise MailboxError("The folder could not be opened") from None
    return client


def _quoted(folder):
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _position(client, config):
    # Opening the folder already told us: a server need not answer STATUS for the folder that is open, and
    # some do not. It is asked only when the opening left either number out.
    found = {}
    for name in (b"UIDNEXT", b"UIDVALIDITY"):
        _, told = client.response(name.decode())
        if told and told[0] and bytes(told[0]).strip().isdigit():
            found[name] = bytes(told[0]).strip()
    if len(found) < 2:
        status, data = client.status(_quoted(config.get("folder") or "INBOX"), "(UIDNEXT UIDVALIDITY)")
        found.update(dict(re.findall(rb"(UIDNEXT|UIDVALIDITY) (\d+)", data[0] or b"")) if status == "OK" else {})
    if b"UIDNEXT" not in found or b"UIDVALIDITY" not in found:
        raise MailboxError("The mail server did not report the mailbox's position")
    return {"validity": int(found[b"UIDVALIDITY"]), "uid": int(found[b"UIDNEXT"]) - 1}


def mailbox_position(config, password):
    """Where the mailbox stands now. Mail up to here is never taken in."""
    client = connect(config, password)
    try:
        return _position(client, config)
    except (imaplib.IMAP4.error, OSError):
        raise MailboxError("The mailbox could not be read") from None
    finally:
        _close(client)


def _close(client):
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def attachments(message):
    """The PDF and image attachments of a message, as (name, bytes)."""
    found = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = part.get_filename() or ""
        try:
            name = str(make_header(decode_header(name)))
        except (LookupError, ValueError):
            pass
        kind = part.get_content_type()
        if kind not in FILE_TYPES and not name.lower().endswith(EXTENSIONS):
            continue
        data = part.get_payload(decode=True) or b""
        if not data or len(data) > MAX_FILE_BYTES:
            continue
        pictured = kind.startswith("image/") or name.lower().endswith((".png", ".jpg", ".jpeg"))
        if pictured and part.get_content_disposition() != "attachment" and len(data) < INLINE_IMAGE_BYTES:
            # A logo or signature in the body of the message. A photographed invoice is far larger.
            continue
        found.append((name or "attachment" + FILE_TYPES.get(kind, ""), data))
    return found


def check_mailbox(config, password, cursor, limit):
    """Mail that arrived since the cursor: (new cursor, files), each file {name, sender, data}.

    At most limit messages are read in one check; the cursor stops at the last one read, so the rest
    are read next time. A mailbox that was rebuilt on the server (its validity changed) is taken up
    from where it stands now, not read again from the start.
    """
    client = connect(config, password)
    try:
        position = _position(client, config)
        if cursor.get("validity") != position["validity"]:
            return position, []
        last = int(cursor.get("uid", position["uid"]))
        status, data = client.uid("SEARCH", None, f"UID {last + 1}:*")
        if status != "OK":
            raise MailboxError("The mailbox could not be searched")
        # "n:*" always names the newest message, even when it is older than n.
        waiting = sorted(uid for uid in (int(item) for item in (data[0] or b"").split()) if uid > last)
        files = []
        for uid in waiting[:limit]:
            status, sized = client.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size = re.search(rb"RFC822\.SIZE (\d+)", (sized[0] or b"") if status == "OK" else b"")
            if size and int(size.group(1)) <= MAX_MESSAGE_BYTES:
                status, fetched = client.uid("FETCH", str(uid), "(BODY.PEEK[])")
                # A busy server may slip other news in beside the message: the message is the part with a body.
                body = next((part[1] for part in fetched or [] if isinstance(part, tuple)), None)
                if status == "OK" and body:
                    message = email.message_from_bytes(body)
                    sender = parseaddr(message.get("From", ""))[1]
                    files += [{"name": name, "sender": sender, "data": body} for name, body in attachments(message)]
            last = uid
        position = {"validity": position["validity"], "uid": last}
        if client.kept_secret != password:
            # Microsoft issued a newer refresh token: whoever stores the secret keeps this one from now on.
            position["secret"] = client.kept_secret
        return position, files
    except (imaplib.IMAP4.error, OSError):
        raise MailboxError("The mailbox could not be read") from None
    finally:
        _close(client)
