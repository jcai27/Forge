import asyncio
import os
import uuid

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from factory.builder import design, persist_version
from factory.connectors import discover_connection
from factory.db import Base, make_engine
from factory.fixtures import seed_business, seed_suite
from factory.models import AgentRecord, Connection, Membership, Organization, Project, User
from factory.security import passwords


@pytest.fixture
def db(tmp_path):
    test_url = os.getenv("TEST_DATABASE_URL")
    schema = "test_" + uuid.uuid4().hex if test_url else None
    engine = make_engine(test_url or f"sqlite:///{tmp_path}/test.db")
    if schema:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    if schema:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
    engine.dispose()


@pytest.fixture
def seeded(db):
    org = Organization(name="Fixture Org")
    user = User(email="test@example.invalid", password_hash=passwords.hash("test-password"))
    db.add_all([org, user])
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="admin"))
    project = Project(org_id=org.id, name="Test project")
    connection = Connection(
        org_id=org.id,
        name="Fictional ERP",
        kind="fixture",
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add_all([project, connection])
    db.flush()
    asyncio.run(discover_connection(db, connection))
    seed_business(db, org.id)
    agent = AgentRecord(
        org_id=org.id,
        project_id=project.id,
        name="Orders",
        request="Process restaurant orders safely",
        template="orders",
    )
    db.add(agent)
    db.flush()
    spec = asyncio.run(design(db, agent, [connection.id]))
    version = persist_version(db, agent, spec)
    suite = seed_suite(db, agent)
    db.commit()
    return org, user, agent, version, suite, connection
