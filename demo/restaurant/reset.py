"""Put the demo customer back to its starting state, ready to be shown again.

    bash demo/restaurant/reset.sh

Showing the demo changes it: invoices get uploaded, corrected, approved and sent to the books. This
undoes all of that in the local database and contacts no model:

  - the three invoices kept for uploading live (customer.HELD_BACK) are taken out, with what was read
    from their pages, so the next upload is read afresh in front of the audience;
  - anything else uploaded during a showing is taken out;
  - every other document loses its corrections, approval and export, and the automatic checks are run
    again in order, which is code;
  - export batches and channels are removed, and the ledger accounts are set as customer.py sets them;
  - the customer login is the only member of the customer's own people, with a password kept in
    demo/restaurant/.login (not in git) so the same one works every time.

The pages of the documents that stay are not read again: their answers are kept as they are. The
three invoices to upload are written to demo/restaurant/data/live/.

It works on the database directly because nothing in the product may un-send an invoice from the
books, and nothing should. This is a tool for a local demo, not an operation a customer has.
"""

import asyncio
import json
import secrets
import sys
from pathlib import Path

from customer import CUSTOMER, HELD_BACK, LOGIN, STATEMENT, file_name, invoice_files
from factory.db import SessionLocal
from factory.models import (
    AgentVersion,
    Channel,
    Deployment,
    DocumentReading,
    ExportBatch,
    InboxDocument,
    Membership,
    Operation,
    Organization,
    User,
)
from factory.portal import assess, processed
from factory.reading import Reader
from factory.security import passwords
from sqlalchemy import delete, select

HERE = Path(__file__).parent
KEPT_LOGIN = HERE / ".login"
SETTINGS = {
    "auto_approve_clean": False,
    "terms_days": 28,
    "accounts": [
        {"code": "5000", "name": "Food cost"},
        {"code": "5100", "name": "Produce"},
        {"code": "6200", "name": "Supplies"},
    ],
    "default_account": "5000",
    "supplier_accounts": {"Gordon Food Service": "5000"},
    # Xero needs a tax type on every line. This is the name of a rate in a new US Xero organisation; it must
    # be changed to match the organisation a file is imported into.
    "tax_code": "Tax Exempt (0%)",
    "date_format": "mdy",
}


class Forgetter(Reader):
    """Walks a document exactly as a reading would, and instead of reading each page drops what is kept
    of it. An empty answer makes the walk try every way up as well, so those are dropped too."""

    dropped = 0

    async def _read(self, digest, prompt, images, label, count_page):
        result = self.db.execute(
            delete(DocumentReading).where(
                DocumentReading.org_id == self.org_id, DocumentReading.content_hash == digest
            )
        )
        self.dropped += result.rowcount
        return ""


async def forget(db, operation, data, name):
    version = db.get(AgentVersion, db.get(Deployment, operation.deployment_id).version_id)
    reader = Forgetter(db, operation.org_id)
    try:
        await reader.read(data, name, reading=version.spec.get("reading"))
    finally:
        await reader.close()
    return reader.dropped


def main():
    invoices = invoice_files()
    live = HERE / "data" / "live"
    live.mkdir(parents=True, exist_ok=True)
    for number in HELD_BACK:
        (live / file_name(number)).write_bytes(invoices[number][1])
    baseline = {file_name(number) for number in invoices if number not in HELD_BACK} | {STATEMENT[0]}

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == CUSTOMER, Organization.kind == "customer"))
        if org is None:
            sys.exit(f"There is no {CUSTOMER} workspace yet. Set it up first: see demo/restaurant/README.md.")
        operations = list(db.scalars(select(Operation).where(Operation.org_id == org.id)))
        invoice_agent = next((item for item in operations if item.kind == "invoice"), None)
        if invoice_agent is None:
            sys.exit("The workspace has no invoice agent. Run customer.py first.")

        dropped = sum(
            asyncio.run(forget(db, invoice_agent, invoices[number][1], file_name(number))) for number in HELD_BACK
        )
        documents = list(db.scalars(select(InboxDocument).where(InboxDocument.org_id == org.id)))
        removed = [document for document in documents if document.name not in baseline]
        for document in removed:
            db.delete(document)
        kept = [document for document in documents if document.name in baseline]
        missing = sorted(baseline - {document.name for document in kept if document.status == "processed"})
        if missing:
            db.rollback()
            sys.exit(
                f"{len(missing)} of the starting documents are not in the workspace (first: {missing[0]}). "
                "Run customer.py with the app started to read them, then reset again."
            )
        for document in kept:
            document.corrected = document.reviewed_by = document.reviewed_at = None
            document.approved_by = document.approved_at = document.export_id = None
            document.deliveries, document.stage = {}, "new"
        db.execute(delete(ExportBatch).where(ExportBatch.org_id == org.id))
        db.execute(delete(Channel).where(Channel.org_id == org.id))
        for operation in operations:
            operation.enabled = True
            if operation.kind == "invoice":
                operation.settings = dict(SETTINGS)
        db.flush()
        for operation in operations:
            # Oldest first, as they arrived: each is judged against the ones before it.
            for document in processed(db, operation):
                assess(db, operation, document)

        owner = db.scalar(select(User).where(User.email == LOGIN))
        if owner is None:
            db.rollback()
            sys.exit(f"The customer login {LOGIN} does not exist. Run customer.py first.")
        others = db.scalars(
            select(Membership).where(
                Membership.org_id == org.id, Membership.role == "customer", Membership.user_id != owner.id
            )
        )
        for member in others:
            db.delete(member)
        password = json.loads(KEPT_LOGIN.read_text())["password"] if KEPT_LOGIN.exists() else secrets.token_urlsafe(12)
        owner.password_hash = passwords.hash(password)
        db.commit()
        KEPT_LOGIN.write_text(json.dumps({"email": LOGIN, "password": password}) + "\n")
        KEPT_LOGIN.chmod(0o600)

        stages = {}
        for document in db.scalars(select(InboxDocument).where(InboxDocument.org_id == org.id)):
            stages[document.stage] = stages.get(document.stage, 0) + 1
    print(f"{CUSTOMER} is at its starting state: {len(kept)} documents, {stages}.")
    print(f"Taken out: {len(removed)} documents, {dropped} kept page readings of the invoices to upload live.")
    print(f"To upload live: {live}/  ({', '.join(file_name(number) for number in HELD_BACK)})")
    print(f"Sign in at http://localhost:3000/portal as {LOGIN} / {password}")


if __name__ == "__main__":
    main()
