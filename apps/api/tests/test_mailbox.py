"""Reading a mailbox: signing in the way each kind of server allows, finding where it stands, taking only new
mail, and choosing what in a message is a document. The server here is a stand-in that answers as Gmail and
Outlook are documented to; docs/MAILBOXES.md says what has and has not been run against the real ones."""

import imaplib
from email.message import EmailMessage

import pytest

from factory import mailbox
from factory.mailbox import MailboxError, attachments, check_mailbox, mailbox_position

PDF = b"%PDF-1.4 " + b"x" * 400


def message(sender="ap@supplier.example", files=(), inline=()):
    mail = EmailMessage()
    mail["From"], mail["Subject"] = f"Accounts <{sender}>", "Invoice"
    mail.set_content("Please find attached.")
    for name, kind, data in files:
        mail.add_attachment(data, maintype=kind.split("/")[0], subtype=kind.split("/")[1], filename=name)
    for name, kind, data in inline:
        mail.add_attachment(
            data, maintype=kind.split("/")[0], subtype=kind.split("/")[1], filename=name, disposition="inline"
        )
    return mail.as_bytes()


class Server:
    """What a mail server would say. A list of (uid, message bytes), and how it wants people to sign in."""

    def __init__(
        self, mail=(), validity=7, password="app-password", oauth=None, tells_position=True, status_works=True
    ):
        self.mail, self.validity, self.password, self.oauth = list(mail), validity, password, oauth
        self.tells_position, self.status_works = tells_position, status_works
        self.calls, self.flags_touched = [], False

    def client(self, host, address):
        return Client(self)


class Client:
    def __init__(self, server):
        self.server, self.untagged = server, {}

    def login(self, user, password):
        self.server.calls.append("LOGIN")
        if self.server.oauth:
            raise imaplib.IMAP4.error("b'LOGIN failed.' BasicAuthBlocked")
        if password != self.server.password:
            raise imaplib.IMAP4.error("b'[ALERT] Application-specific password required'")

    def authenticate(self, mechanism, respond):
        self.server.calls.append(mechanism)
        if respond(b"") != f"user=ap@diner.example\x01auth=Bearer {self.server.oauth}\x01\x01".encode():
            raise imaplib.IMAP4.error("AUTHENTICATE failed")

    def select(self, folder, readonly=False):
        assert readonly, "the mailbox must be opened read-only"
        self.server.calls.append(f"EXAMINE {folder}")
        if self.server.tells_position:
            uidnext = max((uid for uid, _ in self.server.mail), default=0) + 1
            self.untagged = {"UIDVALIDITY": [str(self.server.validity).encode()], "UIDNEXT": [str(uidnext).encode()]}
        return "OK", [b"1"]

    def response(self, name):
        return name, self.untagged.get(name, [None])

    def status(self, folder, names):
        self.server.calls.append("STATUS")
        if not self.server.status_works:
            return "NO", [b"STATUS of the selected mailbox is not supported"]
        uidnext = max((uid for uid, _ in self.server.mail), default=0) + 1
        return "OK", [f"{folder} (UIDNEXT {uidnext} UIDVALIDITY {self.server.validity})".encode()]

    def uid(self, command, *arguments):
        self.server.calls.append(f"UID {command} {arguments[-1]}")
        if command == "SEARCH":
            return "OK", [b" ".join(str(uid).encode() for uid, _ in self.server.mail)]
        uid = int(arguments[0])
        body = dict(self.server.mail)[uid]
        if arguments[1] == "(RFC822.SIZE)":
            return "OK", [f"1 (UID {uid} RFC822.SIZE {len(body)})".encode()]
        # As a busy server answers: an unrelated update first, then the message, then the closing bracket.
        return "OK", [b"3 (FLAGS (\\Recent))", (f"1 (UID {uid} BODY[] {{{len(body)}}}".encode(), body), b")"]

    def store(self, *arguments):
        self.server.flags_touched = True
        raise AssertionError("nothing in a mailbox may be marked")

    def logout(self):
        self.server.calls.append("LOGOUT")

    def shutdown(self):
        pass


@pytest.fixture
def connect(monkeypatch):
    def to(server):
        monkeypatch.setattr(mailbox, "PinnedIMAP", server.client)
        monkeypatch.setattr(mailbox.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("142.250.0.109", 993))])
        return server

    return to


GMAIL = {"host": "imap.gmail.com", "username": "ap@diner.example", "folder": "INBOX"}
OUTLOOK = {**GMAIL, "host": "outlook.office365.com", "auth": "microsoft", "client_id": "c" * 36, "tenant": "common"}


def test_only_mail_that_arrives_after_connecting_is_read_and_nothing_is_marked(connect):
    old = [(40, message(files=[("old.pdf", "application/pdf", PDF)]))]
    server = connect(Server(old))
    start = mailbox_position(GMAIL, "app-password")
    assert start == {"validity": 7, "uid": 40}
    # The folder's own opening said where it stands: the server was not asked again.
    assert "STATUS" not in server.calls and 'EXAMINE "INBOX"' in server.calls
    assert check_mailbox(GMAIL, "app-password", start, 10) == (start, [])
    server.mail += [
        (41, message("billing@gfs.example", [("Invoice 9.pdf", "application/pdf", PDF)])),
        (42, message(files=[("notes.txt", "text/plain", b"hello")])),
        (43, message(files=[("scan.jpg", "image/jpeg", b"\xff\xd8" + b"j" * 500)])),
    ]
    position, files = check_mailbox(GMAIL, "app-password", start, 2)
    # Two messages a check: the first two are read, the third waits, and the position stops at the last one read.
    assert position == {"validity": 7, "uid": 42}
    assert [(item["name"], item["sender"]) for item in files] == [("Invoice 9.pdf", "billing@gfs.example")]
    position, files = check_mailbox(GMAIL, "app-password", position, 2)
    assert position["uid"] == 43 and [item["name"] for item in files] == ["scan.jpg"]
    # Read with BODY.PEEK, in a folder opened read-only: no message was marked as read, moved or deleted.
    assert not server.flags_touched and any("BODY.PEEK[]" in call for call in server.calls)
    # A mailbox rebuilt on the server is taken up from where it stands now, not read again from the start.
    server.validity = 8
    assert check_mailbox(GMAIL, "app-password", position, 10) == ({"validity": 8, "uid": 43}, [])


def test_a_server_that_does_not_say_where_it_stands_on_opening_is_asked(connect):
    server = connect(Server([(5, message())], tells_position=False))
    assert mailbox_position(GMAIL, "app-password") == {"validity": 7, "uid": 5} and "STATUS" in server.calls
    connect(Server(tells_position=False, status_works=False))
    with pytest.raises(MailboxError, match="position"):
        mailbox_position(GMAIL, "app-password")


def test_a_refused_sign_in_says_what_to_do_about_it(connect):
    connect(Server())
    with pytest.raises(MailboxError, match="app password"):
        mailbox_position(GMAIL, "the-ordinary-password")
    # Outlook takes no password at all: the person is told so, not told their password is wrong.
    connect(Server(oauth="access-1"))
    with pytest.raises(MailboxError, match="Microsoft sign-in"):
        mailbox_position({**GMAIL, "host": "outlook.office365.com"}, "an-app-password")


def test_a_microsoft_mailbox_signs_in_with_a_token_and_keeps_the_newest_refresh_token(connect, monkeypatch):
    server = connect(Server([(9, message())], oauth="access-1"))
    asked = []

    def token(config, refresh):
        asked.append((config["client_id"], config["tenant"], refresh))
        return "access-1", "refresh-2"

    monkeypatch.setattr(mailbox, "microsoft_token", token)
    position, files = check_mailbox(OUTLOOK, "refresh-1", {"validity": 7, "uid": 9}, 10)
    assert server.calls[0] == "XOAUTH2" and "LOGIN" not in server.calls
    assert asked == [("c" * 36, "common", "refresh-1")]
    # Microsoft handed back a newer refresh token: the caller is given it to store in place of the old one.
    assert position == {"validity": 7, "uid": 9, "secret": "refresh-2"} and files == []
    # A consent that has lapsed is said plainly, and nothing is retried.
    monkeypatch.setattr(mailbox, "microsoft_token", lambda *a: (_ for _ in ()).throw(MailboxError("sign in again")))
    with pytest.raises(MailboxError, match="sign in again"):
        check_mailbox(OUTLOOK, "refresh-2", position, 10)


def test_a_logo_in_a_signature_is_not_a_document_but_a_photographed_invoice_is():
    import email

    logo, photo = b"\x89PNG" + b"l" * 4_000, b"\xff\xd8" + b"p" * 150_000
    mail = email.message_from_bytes(
        message(
            files=[("Invoice.pdf", "application/pdf", PDF), ("small-attached.png", "image/png", logo)],
            inline=[("logo.png", "image/png", logo), ("IMG_2041.jpg", "image/jpeg", photo)],
        )
    )
    # The attached files are taken whatever their size. Of the pictures in the body, only the one large enough
    # to be a photograph of a page.
    assert [name for name, _ in attachments(mail)] == ["Invoice.pdf", "small-attached.png", "IMG_2041.jpg"]
