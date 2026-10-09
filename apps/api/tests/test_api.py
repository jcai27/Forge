import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from factory.api import app, limits
from factory.db import get_db
from factory.models import AgentVersion, Approval, BusinessRecord, Membership, Organization, Project, User
from factory.security import passwords, token_for
from factory.workflow import TERMINAL, advance


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    org, user, *_ = seeded
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def test_agent_creation_and_immutable_edit(client, seeded, db):
    org, user, agent, version, suite, connection = seeded
    result = client.post(
        "/agents",
        json={
            "project_id": agent.project_id,
            "request": "Generate customer quotes from supplier prices",
            "connection_ids": [connection.id],
        },
    )
    assert result.status_code == 201, result.text
    created = result.json()
    assert created["template"] == "quotes"
    assert created["version"]["spec"]["tools"]
    spec = created["version"]["spec"]
    spec["instructions"] += "\nVerify totals."
    edit = client.post(f"/agents/{created['id']}/versions", json=spec)
    assert edit.status_code == 201, edit.text
    db.expire_all()
    assert db.get(AgentVersion, created["version"]["id"]).spec["instructions"] != spec["instructions"]


def test_tenant_boundaries_and_roles(client, seeded, db):
    other = Organization(name="Other")
    user = User(email="other@example.invalid", password_hash=passwords.hash("test-password"))
    db.add_all([other, user])
    db.flush()
    db.add(Membership(org_id=other.id, user_id=user.id, role="viewer"))
    project = Project(org_id=other.id, name="Private")
    db.add(project)
    db.commit()
    assert client.post("/agents", json={"project_id": project.id, "request": "Process orders"}).status_code == 404
    org, _, agent, version, suite, connection = seeded
    client.headers["Authorization"] = "Bearer " + token_for(user.id, other.id)
    for path in [
        f"/agents/{agent.id}",
        f"/integrations/{connection.id}",
        f"/agents/{agent.id}/versions",
        f"/suites/{suite.id}/cases",
    ]:
        assert client.get(path).status_code == 404
    assert client.get("/agents").json()["items"] == []
    assert client.post("/projects", json={"name": "Unauthorized"}).status_code == 403
    assert client.post(f"/versions/{version.id}/approve").status_code == 403


def test_secrets_are_encrypted_and_never_returned(client, db):
    result = client.post(
        "/integrations",
        json={
            "name": "API",
            "kind": "rest",
            "config": {"base_url": "https://example.com", "allowed_hosts": ["example.com"]},
            "secret": "sk-test-sensitive-credential",
            "permissions": {"read": True},
        },
    )
    assert result.status_code == 201
    from factory.models import Connection

    row = db.get(Connection, result.json()["id"])
    assert "sk-test-sensitive" not in row.encrypted_secret
    assert "sk-test-sensitive" not in result.text
    assert "encrypted_secret" not in result.text
    assert (
        client.post("/integrations", json={"name": "Bad", "kind": "rest", "config": {"api_key": "secret"}}).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_approval_deployment_invocation_rollback(client, seeded, db):
    org, user, agent, initial, suite, connection = seeded
    assert client.post(f"/versions/{initial.id}/approve").status_code == 409
    job = client.post(f"/agents/{agent.id}/builds", json={}).json()
    from factory.models import BuildJob

    for _ in range(300):
        row = db.get(BuildJob, job["id"])
        await advance(db, row)
        db.commit()
        if row.state in TERMINAL:
            break
    assert row.state == "READY_FOR_REVIEW"
    db.refresh(agent)
    version_id = agent.best_version_id
    approved = client.post(f"/versions/{version_id}/approve")
    assert approved.status_code == 200, approved.text
    deployment = client.post(f"/agents/{agent.id}/deployments", json={"version_id": version_id})
    assert deployment.status_code == 201, deployment.text
    deployment_id = deployment.json()["id"]
    request = {"input": {"text": "Harbor Bistro: 2 kg red toms"}, "idempotency_key": "unique-order"}
    invocation = client.post(f"/deployments/{deployment_id}/invoke", json=request)
    assert invocation.status_code == 200, invocation.text
    run = invocation.json()
    assert run["status"] == "waiting_for_approval"
    assert client.post(f"/deployments/{deployment_id}/invoke", json=request).json()["id"] == run["id"]
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == run["id"]))
    approval = db.scalar(select(Approval).where(Approval.run_id == run["id"]))
    decision = client.post(f"/approvals/{approval.id}/resolve", json={"approved": True})
    assert decision.status_code == 200, decision.text
    assert db.scalar(select(BusinessRecord).where(BusinessRecord.key == run["id"]))
    assert client.get(f"/runs/{run['id']}").json()["events"]
    assert client.post(f"/deployments/{deployment_id}/pause").status_code == 200
    assert (
        client.post(f"/deployments/{deployment_id}/invoke", json={**request, "idempotency_key": "blocked"}).status_code
        == 409
    )
    rolled = client.post(f"/deployments/{deployment_id}/rollback")
    assert rolled.status_code == 201, rolled.text
    assert rolled.json()["version_id"] == version_id


def test_file_import_visibility_and_revocation(client, seeded, db):
    result = client.post("/integrations", json={"name": "Uploaded data", "kind": "file"}).json()
    imported = client.post(
        f"/integrations/{result['id']}/import", files={"file": ("catalog.csv", b"name,price\nRice,220\n", "text/csv")}
    )
    assert imported.status_code == 200, imported.text
    source = imported.json()
    assert source["model_visible"] is False
    assert client.patch(f"/data-sources/{source['id']}", json={"model_visible": True}).status_code == 200
    assert client.post(f"/integrations/{result['id']}/revoke").json()["status"] == "revoked"
    assert client.post(f"/integrations/{result['id']}/test").status_code == 409
