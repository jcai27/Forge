"""Large owned fixture workspace: real configurations, no evaluation scores."""

from sqlalchemy import select

from factory.builder import design, persist_version
from factory.connectors import discover_connection
from factory.fixtures import seed_business
from factory.models import AgentRecord, Connection, EvaluationSuite, Membership, Organization, Project, User
from factory.security import Principal, audit, passwords


async def seed_collections(db):
    org = Organization(name="Collection pagination fixture")
    user = User(
        email="pagination-fixture@example.invalid", password_hash=passwords.hash("local-pagination-fixture-password")
    )
    db.add_all([org, user])
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="admin"))
    seed_business(db, org.id)
    for index in range(53):
        project = Project(org_id=org.id, name=f"Collection Project {index:03d}")
        connection = Connection(
            org_id=org.id,
            name=f"Collection Connection {index:03d}",
            kind="fixture",
            status="connected",
            permissions={"read": True, "write": True},
        )
        db.add_all([project, connection])
        db.flush()
        await discover_connection(db, connection)
        agent = AgentRecord(
            org_id=org.id,
            project_id=project.id,
            name=f"Collection Agent {index:03d}",
            request="Process restaurant orders using approved catalog tools",
            template="orders",
        )
        db.add(agent)
        db.flush()
        spec = await design(db, agent, [connection.id], model_backed=False)
        persist_version(db, agent, spec)
        audit(db, Principal(user.id, org.id, "admin"), "collection_fixture_created", agent.id, {"index": index})
        if index == 0:
            for suite_index in range(53):
                db.add(EvaluationSuite(org_id=org.id, agent_id=agent.id, name=f"Collection Suite {suite_index:03d}"))
    db.commit()
    assert len(list(db.scalars(select(AgentRecord).where(AgentRecord.org_id == org.id)))) == 53
