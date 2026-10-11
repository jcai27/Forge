"""Reading a mailbox for documents.

A customer connects the mailbox their invoices arrive in. It is opened over IMAP with TLS on the
standard port, read-only, and only for mail that arrived after it was connected: the position is a
message UID kept on the channel, and nothing older is ever fetched. Messages are not marked, moved
or deleted.

The server name is the customer's to type, so it is treated like any other outbound address: every
address it resolves to must be public, and the connection is made to the address that was checked,
with the certificate still verified against the name.
"""

import email
import imaplib
import re
import socket
import ssl
from email.header import decode_header, make_header
from email.utils import parseaddr

from factory.http_transport import public_addresses

PORT = 993
TIMEOUT = 20
MAX_MESSAGE_BYTES = 25_000_000
MAX_FILE_BYTES = 10_000_000
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
    try:
        client.login(config["username"], password)
    except imaplib.IMAP4.error:
        client.shutdown()
        raise MailboxError("The mail server refused the account name or password") from None
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
    status, data = client.status(_quoted(config.get("folder") or "INBOX"), "(UIDNEXT UIDVALIDITY)")
    found = dict(re.findall(rb"(UIDNEXT|UIDVALIDITY) (\d+)", data[0] or b"")) if status == "OK" else {}
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
                if status == "OK" and fetched and isinstance(fetched[0], tuple):
                    message = email.message_from_bytes(fetched[0][1])
                    sender = parseaddr(message.get("From", ""))[1]
                    files += [{"name": name, "sender": sender, "data": body} for name, body in attachments(message)]
            last = uid
        return {"validity": position["validity"], "uid": last}, files
    except (imaplib.IMAP4.error, OSError):
        raise MailboxError("The mailbox could not be read") from None
    finally:
        _close(client)
