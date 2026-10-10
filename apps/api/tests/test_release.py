"""Feedback and release: tenant playbook, read-only shadow comparison, the dossier, and cases from real runs."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from factory.api import app, limits
from factory.builder import persist_version
from factory.db import get_db, uid
from factory.evaluation import evaluate_case
from factory.fixtures import business_snapshot
from factory.models import (
    AgentRecord,
    Approval,
    BuildIteration,
    BuildJob,
    Connection,
    Deployment,
    EvaluationCase,
    EvaluationRun,
    ExecutionEvent,
    Invocation,
    Membership,
    Organization,
    Project,
    User,
)
from factory.release import playbook, shadow_run
from factory.runtime import emit, execute
from factory.schemas import AgentSpec, GeneratedTool
from factory.security import Principal, passwords, token_for


def promoted(db, org_id, agent, hypothesis):
    spec = AgentSpec(name="n", purpose="p", template=agent.template, instructions="i")
    from factory.models import AgentVersion

    number = (db.scalar(select(func.max(AgentVersion.number)).where(AgentVersion.agent_id == agent.id)) or 0) + 1
    version = AgentVersion(
        org_id=org_id, agent_id=agent.id, number=number, spec=spec.model_dump(), hypothesis=hypothesis
    )
    db.add(version)
    db.flush()
    job = BuildJob(org_id=org_id, agent_id=agent.id, budget={}, checkpoint={})
    db.add(job)
    db.flush()
    db.add(
        BuildIteration(
            org_id=org_id, job_id=job.id, number=1, version_id=version.id, scorecard={}, diagnosis={}, promoted=True
        )
    )
    db.flush()


def other_agent(db, org_id, project_id, template="orders"):
    agent = AgentRecord(org_id=org_id, project_id=project_id, name="Other", request="Another agent", template=template)
    db.add(agent)
    db.flush()
    return agent


def test_playbook_is_scoped_to_the_tenant_template_and_real_ideas(db, seeded):
    org, _, agent, *_ = seeded
    sibling = other_agent(db, org.id, agent.project_id)
    promoted(db, org.id, sibling, "Resolve customer aliases before catalog lookup")
    promoted(db, org.id, sibling, "Initial candidate")
    promoted(db, org.id, sibling, "User configuration revision; requires fresh evaluation")
    promoted(db, org.id, agent, "An idea from this same agent")
    quotes = other_agent(db, org.id, agent.project_id, template="quotes")
    promoted(db, org.id, quotes, "A quotes-only idea")
    stranger = Organization(name="Another tenant")
    db.add(stranger)
    db.flush()
    project = Project(org_id=stranger.id, name="Theirs")
    db.add(project)
    db.flush()
    promoted(db, stranger.id, other_agent(db, stranger.id, project.id), "Another tenant's private idea")

    ideas = playbook(db, org.id, "orders", exclude_agent_id=agent.id)
    assert ideas == ["Resolve customer aliases before catalog lookup"]
    assert playbook(db, stranger.id, "orders") == ["Another tenant's private idea"]


async def deployed(db, seeded, inputs):
    """A deployment of the baseline version with real recorded invocations."""
    org, user, agent, initial, _, _ = seeded
    deployment = Deployment(org_id=org.id, agent_id=agent.id, version_id=initial.id, active=True, policy={})
    db.add(deployment)
    db.flush()
    runs = []
    for text in inputs:
        run = await execute(db, initial, {"text": text})
        db.add(Invocation(org_id=org.id, deployment_id=deployment.id, idempotency_key=uid(), run_id=run.id))
        runs.append(run)
    spec = AgentSpec.model_validate(initial.spec)
    spec.rules["resolve_aliases"] = True
    candidate = persist_version(db, agent, spec, "Resolve aliases")
    db.commit()
    return deployment, runs, candidate


@pytest.mark.asyncio
async def test_shadow_run_compares_read_only_and_changes_nothing(db, seeded):
    org, user, agent, initial, _, _ = seeded
    deployment, runs, candidate = await deployed(
        db, seeded, ["Harbor Bistro: 2 kg Tomatoes", "Harbor Bistro: 2 kg chook"]
    )
    approvals = db.scalar(select(func.count()).select_from(Approval))
    before = business_snapshot(db, org.id)
    actor = Principal(user.id, org.id, "admin")
    report = await shadow_run(db, actor, candidate)
    db.commit()
    assert report["compared"] == 2 and report["identical"] == 1
    assert report["baseline_version_id"] == initial.id and report["candidate_version_id"] == candidate.id
    difference = report["different"][0]
    assert difference["baseline_run_id"] == runs[1].id
    assert {"flags", "lines", "total_cents"} <= set(difference["changed_fields"])
    # Read-only: no approval was staged and the business state is byte-for-byte unchanged.
    assert db.scalar(select(func.count()).select_from(Approval)) == approvals
    assert business_snapshot(db, org.id) == before
    stored = db.scalar(select(ExecutionEvent).where(ExecutionEvent.kind == "shadow_report"))
    assert stored.payload["candidate_version_id"] == candidate.id

    with pytest.raises(ValueError, match="already the deployed"):
        await shadow_run(db, actor, initial)
    deployment.active = False
    db.flush()
    with pytest.raises(ValueError, match="active deployment"):
        await shadow_run(db, actor, candidate)


@pytest.mark.asyncio
async def test_shadow_run_needs_explicit_authorization_for_external_reads(db, seeded):
    org, user, agent, initial, _, _ = seeded
    _, _, candidate = await deployed(db, seeded, ["Harbor Bistro: 2 kg Tomatoes"])
    email = Connection(
        org_id=org.id,
        name="Mail",
        kind="email",
        config={"provider": "mock"},
        permissions={"read": True, "write": False},
        status="connected",
    )
    db.add(email)
    db.flush()
    spec = AgentSpec.model_validate(candidate.spec)
    spec.connection_ids = [*spec.connection_ids, email.id]
    external = persist_version(db, agent, spec, "Adds an external system")
    with pytest.raises(PermissionError, match="authorize read-only"):
        await shadow_run(db, Principal(user.id, org.id, "admin"), external)


@pytest.fixture
def http(db, seeded):
    org, user, *_ = seeded
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def member(db, org, role):
    user = User(email=f"{role}-{uid()}@example.invalid", password_hash=passwords.hash("test-password"))
    db.add(user)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=role))
    db.commit()
    return {"Authorization": "Bearer " + token_for(user.id, org.id)}


@pytest.mark.asyncio
async def test_dossier_gathers_reach_code_provenance_and_open_items(db, seeded, http):
    org, _, agent, initial, _, connection = seeded
    _, _, candidate = await deployed(db, seeded, ["Harbor Bistro: 2 kg Tomatoes"])
    spec = AgentSpec.model_validate(candidate.spec)
    spec.generated_tools = [
        GeneratedTool(
            name="noop_tool",
            description="Does nothing.",
            code="def run(input, call):\n    return {}\n",
            capabilities={"records": spec.tools[0]},
        )
    ]
    version = persist_version(db, agent, spec, "Adds a generated tool")
    emit(
        db,
        org.id,
        "improvement_hypothesis",
        {"version_id": version.id, "research_sources": ["https://docs.example/aliases"]},
    )
    db.commit()
    body = http.get(f"/versions/{version.id}/dossier").json()
    assert body["version"] == {
        "id": version.id,
        "number": version.number,
        "hypothesis": "Adds a generated tool",
        "approved": False,
        "deployed": False,
    }
    assert body["quality_gate"]["passed"] is False and body["quality_gate"]["reason"]
    assert body["reach"]["connections"][0]["name"] == connection.name
    assert {tool["name"] for tool in body["reach"]["tools"]} >= {"prepare_operation"}
    assert body["generated_code"][0]["reviewed"] is False
    from factory.models import ToolDefinition

    assert body["generated_code"][0]["capabilities"] == {"records": db.get(ToolDefinition, spec.tools[0]).name}
    assert body["provenance"]["research_sources"] == ["https://docs.example/aliases"]
    assert body["shadow"] is None
    items = " | ".join(body["open_items"])
    for expected in (
        "Quality gate",
        "not been reviewed",
        "No shadow comparison",
        "Public web pages",
        "Not yet approved",
    ):
        assert expected in items, items

    report = http.post(f"/versions/{version.id}/shadow", json={"limit": 5})
    assert report.status_code == 200, report.text
    after = http.get(f"/versions/{version.id}/dossier").json()
    assert after["shadow"]["compared"] == 1
    assert "No shadow comparison" not in " | ".join(after["open_items"])

    # Shadow runs are an administrator action, and nothing here crosses tenants.
    assert http.post(f"/versions/{version.id}/shadow", json={}, headers=member(db, org, "editor")).status_code == 403
    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    assert http.get(f"/versions/{version.id}/dossier", headers=outsider).status_code in (403, 404)
    assert http.post(f"/versions/{version.id}/shadow", json={}, headers=outsider).status_code in (403, 404)


@pytest.mark.asyncio
async def test_a_real_run_becomes_a_test_case_only_by_explicit_authorization(db, seeded, http):
    org, user, agent, initial, suite, _ = seeded
    # An alias the baseline cannot resolve: the run is flagged and needs attention.
    _, runs, _ = await deployed(db, seeded, ["Harbor Bistro: 2 kg chook", "Harbor Bistro: 2 kg Tomatoes"])
    flagged = runs[0]
    assert flagged.status == "needs_attention"
    listed = http.get(f"/agents/{agent.id}/feedback").json()["items"]
    assert [(item["run_id"], item["already_a_case"]) for item in listed] == [(flagged.id, False)]
    assert listed[0]["reason"] == "The run needed attention"

    correction = {
        "name": "Chook is the customer's word for chicken",
        "split": "development",
        "assertions": [{"path": "lines.0.sku", "value": "SKU-002"}],
    }
    path = f"/runs/{flagged.id}/case"
    assert http.post(path, json=correction).status_code == 422, "authorization is not implied"
    assert (
        http.post(path, json={**correction, "authorize_data_use": True}, headers=member(db, org, "editor")).status_code
        == 403
    )
    bad = http.post(path, json={**correction, "authorize_data_use": True, "assertions": [{"op": "eval", "value": 1}]})
    assert bad.status_code == 422
    assert http.post(path, json={**correction, "authorize_data_use": True, "assertions": []}).status_code == 422
    before = db.scalar(select(func.count()).select_from(EvaluationCase))
    created = http.post(path, json={**correction, "authorize_data_use": True})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "production_input" and body["authorized_by"] == user.id
    assert body["input"] == flagged.input and body["suite_id"] == suite.id
    assert db.scalar(select(func.count()).select_from(EvaluationCase)) == before + 1
    # The reviewer's expectation is the answer; the agent's own output was not copied in.
    assert body["assertions"] == correction["assertions"]
    assert http.get(f"/agents/{agent.id}/feedback").json()["items"][0]["already_a_case"] is True

    # The new case runs in an isolated fork like any other and fails until the agent is improved.
    case = db.get(EvaluationCase, body["id"])
    evaluation = EvaluationRun(org_id=org.id, version_id=initial.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    result = await evaluate_case(db, evaluation, initial, case)
    assert not result.passed and "structured_accuracy" in result.failures

    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    assert http.post(path, json={**correction, "authorize_data_use": True}, headers=outsider).status_code in (403, 404)
    assert http.get(f"/agents/{agent.id}/feedback", headers=outsider).status_code in (403, 404)


@pytest.mark.asyncio
async def test_live_optimizer_is_shown_only_this_tenants_playbook(db, seeded, monkeypatch):
    import json

    from agents import Agent, Model, ModelResponse, Usage
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    from factory.config import settings
    from factory.evaluation import development_evidence, evaluate_suite
    from factory.schemas import Budget
    from factory.workflow import advance, new_job

    org, _, agent, initial, suite, _ = seeded
    promoted(db, org.id, other_agent(db, org.id, agent.project_id), "Resolve customer aliases before catalog lookup")
    stranger = Organization(name="Another tenant")
    db.add(stranger)
    db.flush()
    project = Project(org_id=stranger.id, name="Theirs")
    db.add(project)
    db.flush()
    promoted(db, stranger.id, other_agent(db, stranger.id, project.id), "Another tenant's private idea")
    evaluation = await evaluate_suite(db, initial, suite, ("development", "regression"))
    job = new_job(db, agent, Budget(investigator_turns=0))
    job.state = "OPTIMIZING"
    job.checkpoint = {**job.checkpoint, "diagnosis": {"development_failures": development_evidence(db, evaluation)}}
    db.commit()
    payloads = []

    class Recorder(Model):
        async def get_response(
            self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        ):
            content = next(i["content"] for i in input if isinstance(i, dict) and i.get("role") == "user")
            payloads.append(json.loads(content))
            text = ResponseOutputText(type="output_text", text=json.dumps({"hypothesis": ""}), annotations=[])
            reply = ResponseOutputMessage(
                type="message", role="assistant", id=uid(), status="completed", content=[text]
            )
            return ModelResponse(output=[reply], usage=Usage(requests=1, total_tokens=30), response_id=uid())

        async def stream_response(self, *args, **kwargs):
            raise NotImplementedError
            yield

    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": Recorder()}))
    await advance(db, job)
    db.commit()
    # An unchanged proposal is a rejected attempt; nothing is persisted or re-evaluated.
    assert job.state == "OPTIMIZING" and job.error is None, (job.state, job.error)
    assert job.checkpoint["attempts"][-1]["rejected_before_evaluation"] == "UnchangedProposal"
    assert payloads[0]["playbook"] == ["Resolve customer aliases before catalog lookup"]
    assert "Another tenant" not in json.dumps(payloads)
