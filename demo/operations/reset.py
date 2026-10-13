"""Put the operations demo back to its starting state, ready to be shown again.

    bash demo/operations/reset.sh

Showing it uploads documents, and may correct or approve some. This undoes that in the local database
and calls no model:

  - any document that is not one of the workspace's starting documents (data/baseline) is taken out,
    with the records it wrote: that is the ones kept for uploading live (data/live), and anything else;
  - every starting document loses its corrections and approval, and the checks are run again in order,
    which writes its records afresh. That is code; no page is read again;
  - channels are removed.

It works on the database directly, like demo/restaurant/reset.py, and for the same reason: it is a tool
for a local demo, not something a customer can do.
"""

import sys

from documents import DATA, LABELS
from factory.db import SessionLocal
from factory.models import Channel, InboxDocument, Operation, OperationsRecord, Organization
from factory.portal import assess, processed
from sample import GROUP
from sqlalchemy import delete, select


def main():
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == GROUP, Organization.kind == "customer"))
        if org is None:
            sys.exit(f"There is no {GROUP} workspace yet. Run bash demo/operations/build.sh first.")
        operations = {item.name: item for item in db.scalars(select(Operation).where(Operation.org_id == org.id))}
        removed = kept = 0
        missing = []
        for kind, label in LABELS.items():
            operation = operations.get(label)
            if operation is None:
                missing.append(f"the {label} agent")
                continue
            baseline = {path.name for path in (DATA / "baseline" / kind).glob("*.pdf")}
            held = list(db.scalars(select(InboxDocument).where(InboxDocument.operation_id == operation.id)))
            for document in held:
                if document.name not in baseline or document.status != "processed":
                    db.execute(delete(OperationsRecord).where(OperationsRecord.document_id == document.id))
                    db.delete(document)
                    removed += 1
                else:
                    document.corrected = document.reviewed_by = document.reviewed_at = None
                    document.approved_by = document.approved_at = None
                    document.stage = "new"
                    kept += 1
            absent = baseline - {document.name for document in held if document.status == "processed"}
            if absent:
                missing.append(f"{len(absent)} of the {label} documents")
            operation.enabled = True
        db.execute(delete(Channel).where(Channel.org_id == org.id))
        db.flush()
        for operation in operations.values():
            # Oldest first, as they arrived: a second copy of a document is judged against the first.
            for document in processed(db, operation):
                assess(db, operation, document)
        db.commit()
        written = db.scalar(
            select(OperationsRecord.id)
            .where(OperationsRecord.org_id == org.id, OperationsRecord.source == "agent")
            .limit(1)
        )
    print(f"{GROUP} is at its starting state: {kept} documents kept, {removed} taken out.")
    if missing or not written:
        sys.exit(
            "Not all of the starting state is there: "
            + (", ".join(missing) or "no agent has written a record")
            + ". Run bash demo/operations/build.sh."
        )
    print(f"To upload live: {DATA / 'live'}/")


if __name__ == "__main__":
    main()
