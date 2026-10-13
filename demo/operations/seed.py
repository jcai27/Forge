"""Open the sample workspace and fill it: Harbor Table Group, an invented restaurant group.

    bash demo/operations/seed.sh

Writes to the local database directly and contacts nothing. It opens a customer workspace under the
local demo builder (the one the "Open local demo workspace" button signs in to), replaces any sample
records it holds with the generated history (see documents.split for what is left to the agents), and keeps a customer login for it in
demo/operations/.login (not in git). Run it again at any time: the records come out the same.
"""

import json
import secrets
import sys
from pathlib import Path

from documents import split
from factory.db import SessionLocal
from factory.models import Membership, OperationsRecord, Organization, Project, User
from factory.security import passwords
from sample import GROUP, generate
from sqlalchemy import delete, select

HERE = Path(__file__).parent
BUILDER, LOGIN, KEPT = "demo@agentfactory.local", "harbor@demo.test", HERE / ".login"


def main():
    with SessionLocal() as db:
        builder = db.scalar(select(User).where(User.email == BUILDER))
        home = builder and db.scalar(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == builder.id, Organization.kind == "builder")
        )
        if home is None:
            sys.exit('There is no local demo builder yet. Start the app and click "Open local demo workspace" once.')
        org = db.scalar(select(Organization).where(Organization.name == GROUP, Organization.parent_org_id == home.id))
        if org is None:
            org = Organization(name=GROUP, kind="customer", parent_org_id=home.id)
            db.add(org)
            db.flush()
            db.add(Membership(org_id=org.id, user_id=builder.id, role="admin"))
            db.add(Project(org_id=org.id, name="Operations", description="Agents working for this customer"))
        db.execute(
            delete(OperationsRecord).where(OperationsRecord.org_id == org.id, OperationsRecord.source == "sample")
        )
        # The history only: the last week reaches the workspace through agents reading documents.
        records, _ = split(generate())
        db.add_all(OperationsRecord(org_id=org.id, source="sample", **item) for item in records)
        password = json.loads(KEPT.read_text())["password"] if KEPT.exists() else secrets.token_urlsafe(12)
        person = db.scalar(select(User).where(User.email == LOGIN))
        if person is None:
            person = User(email=LOGIN, password_hash=passwords.hash(password))
            db.add(person)
            db.flush()
        person.password_hash = passwords.hash(password)
        if not db.scalar(select(Membership.id).where(Membership.org_id == org.id, Membership.user_id == person.id)):
            db.add(Membership(org_id=org.id, user_id=person.id, role="customer"))
        db.commit()
    KEPT.write_text(json.dumps({"email": LOGIN, "password": password}) + "\n")
    KEPT.chmod(0o600)
    print(f"{GROUP}: {len(records)} sample records.")
    print(f"Sign in at http://localhost:3000/portal as {LOGIN} / {password}")


if __name__ == "__main__":
    main()
