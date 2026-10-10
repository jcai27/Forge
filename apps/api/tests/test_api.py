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


def test_usage_reports_observed_cost_separately_from_unknown_reservations(client, seeded, db):
    from factory.models import UsageRecord
    from factory.schemas import Budget
    from factory.workflow import new_job

    org, user, agent, *_ = seeded
    job = new_job(db, agent, Budget())
    other = Organization(name="Other usage tenant")
    db.add(other)
    db.flush()
    db.add_all(
        [
            UsageRecord(org_id=org.id, job_id=job.id, role="requirements_architect", cost=0.2, tokens=40),
            UsageRecord(org_id=org.id, job_id=job.id, role="optimizer", status="uncertain", reserved_cost=0.4),
            UsageRecord(org_id=other.id, role="optimizer", cost=99, reserved_cost=99),
        ]
    )
    db.commit()
    summary = client.get("/metrics").json()
    assert summary["cost"] == 0.2 and summary["reserved_cost"] == 0.4
    build = client.get(f"/builds/{job.id}").json()
    assert build["factory_observed_cost"] == 0.2 and build["factory_reserved_cost"] == 0.4
    rows = client.get("/usage").json()
    assert rows["total"] == 2 and all(row["org_id"] == org.id for row in rows["items"])


@pytest.mark.asyncio
async def test_redirect_retests_new_version_without_resetting_history_or_budgets(client, seeded, db):
    from copy import deepcopy

    from factory.models import BuildIteration, BuildJob, EvaluationRun

    _, _, agent, initial, *_ = seeded
    created = client.post(f"/agents/{agent.id}/builds", json={}).json()
    job = db.get(BuildJob, created["id"])
    for _ in range(100):
        await advance(db, job)
        db.commit()
        if job.iteration == 1:
            break
    assert job.state == "OPTIMIZING" and job.checkpoint["best_scorecard"]["score"] < 0.95
    old_checkpoint = deepcopy(job.checkpoint)
    old_budget, old_spent, old_created = dict(job.budget), job.spent, job.created_at
    assert client.post(f"/builds/{job.id}/pause", json={}).status_code == 200
    spec = deepcopy(initial.spec)
    spec["rules"].update(resolve_aliases=True, fuzzy_match=True)
    spec["purpose"] = "Process restaurant orders with customer aliases and conservative fuzzy SKU matching"
    spec["requirements"]["objective"] = spec["purpose"]
    body = {
        "expected_version_id": initial.id,
        "reason": "Resolve catalog aliases before preparing restaurant orders",
        "spec": spec,
    }
    unsafe = deepcopy(body)
    unsafe["spec"]["guardrails"]["require_approval"] = False
    assert client.post(f"/builds/{job.id}/redirect", json=unsafe).status_code == 403
    redirected = client.post(f"/builds/{job.id}/redirect", json=body)
    assert redirected.status_code == 201, redirected.text
    revised_id = redirected.json()["version"]["id"]
    assert client.post(f"/builds/{job.id}/redirect", json=body).status_code == 409
    db.expire_all()
    assert job.iteration == 1 and job.spent == old_spent and job.budget == old_budget and job.created_at == old_created
    assert job.state == "BUILDING" and job.checkpoint["version_id"] == revised_id
    assert "best_scorecard" not in job.checkpoint and "evaluation_id" not in job.checkpoint
    assert db.get(EvaluationRun, old_checkpoint["evaluation_id"]).status == "completed"
    assert db.scalar(select(BuildIteration).where(BuildIteration.job_id == job.id)).version_id == initial.id
    assert db.get(AgentVersion, initial.id).spec["rules"]["resolve_aliases"] is False
    for _ in range(100):
        await advance(db, job)
        db.commit()
        if job.state in TERMINAL:
            break
    assert job.state == "READY_FOR_REVIEW" and job.iteration == 2
    assert job.checkpoint["best_version_id"] == revised_id
    assert job.checkpoint["validation_scorecard"]["score"] == 1
    body["expected_version_id"] = revised_id
    assert client.post(f"/builds/{job.id}/redirect", json=body).status_code == 409
    # A build at its limit cannot obtain another iteration through redirection.
    job.state = "PAUSED"
    job.budget = {**job.budget, "max_iterations": job.iteration}
    db.commit()
    exhausted = client.post(f"/builds/{job.id}/redirect", json=body)
    assert exhausted.status_code == 409 and "iterations remain" in exhausted.text


def test_redirect_requires_tenant_ownership_and_writer_role(client, seeded, db):
    from factory.schemas import Budget
    from factory.workflow import new_job

    org, user, agent, initial, *_ = seeded
    job = new_job(db, agent, Budget())
    db.commit()
    body = {
        "expected_version_id": initial.id,
        "reason": "Update requirements for this current build",
        "spec": initial.spec,
    }
    member = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org.id))
    member.role = "viewer"
    db.commit()
    assert client.post(f"/builds/{job.id}/redirect", json=body).status_code == 403
    other = Organization(name="Other redirect tenant")
    db.add(other)
    db.flush()
    db.add(Membership(org_id=other.id, user_id=user.id, role="admin"))
    db.commit()
    client.headers["Authorization"] = "Bearer " + token_for(user.id, other.id)
    assert client.post(f"/builds/{job.id}/redirect", json=body).status_code == 404


def test_profile_reads_do_not_exhaust_credential_limits_and_errors_keep_cors(client):
    from factory.config import settings

    origin = settings().cors_origins[0]
    for _ in range(35):
        assert client.get("/auth/me", headers={"Origin": origin}).status_code == 200
    for _ in range(30):
        assert client.post("/auth/demo", headers={"Origin": origin}).status_code == 200
    limited = client.post("/auth/demo", headers={"Origin": origin})
    assert limited.status_code == 429
    assert limited.headers["Access-Control-Allow-Origin"] == origin
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["X-Content-Type-Options"] == "nosniff"
    assert limited.headers["Cache-Control"] == "no-store"


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
