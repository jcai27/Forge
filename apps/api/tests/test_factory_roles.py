import json

import httpx
import pytest
from agents import Agent, Model, ModelResponse, Usage
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory.api import app, limits
from factory.builder import persist_version
from factory.config import settings
from factory.db import get_db, uid
from factory.evaluation import can_promote, evaluate_suite
from factory.models import AgentVersion, EvaluationCase, Membership, UsageRecord
from factory.schemas import AgentSpec, Budget
from factory.security import token_for
from factory.workflow import advance, new_job


@pytest.mark.asyncio
async def test_factory_transport_does_not_retry_an_uncertain_http_request(db, seeded, monkeypatch):
    _, _, agent, *_ = seeded
    job = new_job(db, agent, Budget())
    job.state = "DESIGNING"
    db.commit()
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "Explicit local HTTP failure", "type": "server_error"}})

    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-transport-contract")
    monkeypatch.setattr(
        "factory.builder.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        ),
    )
    await advance(db, job)
    db.commit()
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert len(requests) == 1 and requests[0].url.path == "/v1/responses"
    assert job.state == "FAILED" and job.error == "InternalServerError"
    assert record.status == "uncertain" and job.spent == record.reserved_cost > 0
    assert record.cost == record.tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["pause", "cancel", "provider_error", "lease_transfer", "redirect"])
async def test_factory_dispatch_preserves_user_control_and_uncertain_usage(db, seeded, monkeypatch, action):
    from datetime import timedelta

    from factory.api import redirect_build
    from factory.db import now
    from factory.models import BuildJob
    from factory.schemas import RedirectBuild
    from factory.security import Principal
    from factory.workflow import control, worker_tick

    org, user, agent, original, *_ = seeded
    job = new_job(db, agent, Budget())
    job.state = "DESIGNING"
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    class ControlledProvider(ConfigurationProvider):
        async def get_response(self, *args, **kwargs):
            # A separate transaction proves the worker released its lock before I/O.
            with sessions() as other:
                pending = other.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
                assert pending.status == "pending" and pending.reserved_cost > 0
                if action == "lease_transfer":
                    transferred = other.get(BuildJob, job.id)
                    transferred.lease_owner = "another-worker"
                    transferred.lease_until = now() + timedelta(seconds=60)
                    other.commit()
                elif action == "redirect":
                    changed = AgentSpec.model_validate(original.spec)
                    changed.purpose = "Revised restaurant orders with customer alias support"
                    changed.rules["resolve_aliases"] = True
                    redirect_build(
                        job.id,
                        RedirectBuild(
                            expected_version_id=original.id,
                            reason="Use the newly clarified customer alias requirements",
                            spec=changed,
                        ),
                        Principal(user.id, org.id, "admin"),
                        other,
                    )
                elif action != "provider_error":
                    control(other, other.get(BuildJob, job.id), action)
                    other.commit()
            if action == "provider_error":
                raise RuntimeError("Explicit simulated transport failure after dispatch")
            return await super().get_response(*args, **kwargs)

    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-provider-contract")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": ControlledProvider([])}))
    await worker_tick(sessions)
    db.expire_all()
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)) == (
        2 if action == "redirect" else 1
    )
    if action == "provider_error":
        assert job.state == "FAILED" and record.status == "uncertain"
        assert job.spent == record.reserved_cost > 0
        assert record.cost == record.tokens == 0
    elif action == "lease_transfer":
        assert job.state == "DESIGNING" and job.lease_owner == "another-worker"
        assert record.status == "recorded" and record.tokens == 30
    elif action == "redirect":
        assert job.state == "BUILDING" and job.lease_owner is None
        assert job.checkpoint["version_id"] != original.id
        assert db.get(AgentVersion, job.checkpoint["version_id"]).spec["rules"]["resolve_aliases"] is True
        assert record.status == "recorded" and record.tokens == 30
    else:
        assert job.state == ("PAUSED" if action == "pause" else "CANCELLED")
        assert record.status == "recorded" and record.tokens == 30
        assert record.reserved_cost == 0 and job.spent == pytest.approx(record.cost)


def authored_proposal():
    scenarios = [
        ("Tomatoes", 2, 900),
        ("Rice", 2, 880),
        ("Milk", 2, 720),
        ("Butter", 1, 1300),
        ("Onions", 3, 720),
        ("Flour", 2, 560),
    ]
    return {
        "rationale": "Independently authored catalog and customer pricing expectations for isolated review.",
        "cases": [
            {
                "name": f"Proposed {name}",
                "split": ["development", "regression", "validation"][i % 3],
                "source": "synthetic",
                "critical": i % 3 == 1,
                "input": {"text": f"Harbor Bistro: {qty} {'litre' if name == 'Milk' else 'kg'} {name}"},
                "assertions": [
                    {"path": "total_cents", "value": cents},
                    {"path": "tool_sequence", "value": ["prepare_operation"]},
                ],
            }
            for i, (name, qty, cents) in enumerate(scenarios)
        ],
    }


class ProposalProvider(Model):
    def __init__(self, calls, unsafe=False):
        self.calls, self.unsafe = calls, unsafe

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        self.calls.append(
            json.loads(next(item["content"] for item in input if isinstance(item, dict) and item.get("role") == "user"))
        )
        proposal = authored_proposal()
        proposal["cases"][0]["assertions"][0]["value"] = 901
        if self.unsafe:
            proposal["cases"][0]["source"] = "live_read_only"
            proposal["cases"][0]["environment"] = {"live_connection_ids": ["unapproved"]}
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=json.dumps(proposal), annotations=[])],
                )
            ],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


class ConfigurationProvider(Model):
    """Provider contract fixture echoes authorized configuration, never evaluation scores."""

    def __init__(self, calls, invalid_scope=False):
        self.calls, self.invalid_scope = calls, invalid_scope

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        payload = json.loads(
            next(item["content"] for item in input if isinstance(item, dict) and item.get("role") == "user")
        )
        self.calls.append(payload)
        spec = payload.get("baseline", payload.get("spec"))
        if self.invalid_scope:
            spec["tools"].append(uid())
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=json.dumps(spec), annotations=[])],
                )
            ],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_scope", [False, True])
async def test_background_architect_persists_requirements_and_accounts_success_or_failure(
    db, seeded, monkeypatch, invalid_scope
):
    org, _, agent, initial, *_ = seeded
    calls = []
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(
        "factory.builder.Agent",
        lambda **kwargs: Agent(**{**kwargs, "model": ConfigurationProvider(calls, invalid_scope)}),
    )
    job = new_job(db, agent, Budget())
    for _ in range(3):
        await advance(db, job)
        db.commit()
    usage = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert len(calls) == 1
    assert usage.role == "requirements_architect" and usage.tokens == 30
    assert usage.cost == job.spent == pytest.approx(30 * settings().estimated_token_cost)
    if invalid_scope:
        assert job.state == "FAILED" and job.error == "PermissionError"
        assert db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)) == 1
    else:
        assert job.state == "BUILDING"
        generated = db.get(AgentVersion, job.checkpoint["version_id"])
        assert generated.id != initial.id
        assert generated.spec["requirements"]["objective"] == agent.request
        assert generated.spec["requirements"]["side_effect_permissions"] == "explicit_human_approval"
        assert generated.spec["design_metrics"]["tokens"] == 30


@pytest.mark.asyncio
async def test_factory_budget_rejects_provider_before_dispatch(db, seeded, monkeypatch):
    _, _, agent, *_ = seeded
    calls = []
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(
        "factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": ConfigurationProvider(calls)})
    )
    job = new_job(db, agent, Budget(max_cost=0))
    for _ in range(3):
        await advance(db, job)
        db.commit()
    assert job.state == "BUDGET_EXHAUSTED"
    assert calls == [] and job.spent == 0


@pytest.mark.asyncio
async def test_optimizer_records_usage_and_receives_only_development_evidence(db, seeded, monkeypatch):
    _, _, agent, initial, *_ = seeded
    calls = []
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(
        "factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": ConfigurationProvider(calls)})
    )
    job = new_job(db, agent, Budget())
    evidence = [
        {
            "case": "Development alias",
            "input": {"text": "Harbor Bistro: 2 kg chook"},
            "output": {"flags": ["missing_sku:chook"]},
            "failed_checks": [{"category": "structured_accuracy", "passed": False}],
        }
    ]
    job.state = "OPTIMIZING"
    job.checkpoint = {**job.checkpoint, "diagnosis": {"development_failures": evidence}}
    await advance(db, job)
    db.commit()
    assert job.state == "RETESTING"
    assert len(calls) == 1 and calls[0]["development_failures"] == evidence
    assert set(calls[0]) == {"spec", "development_failures"}
    assert calls[0]["spec"]["requirements"]["required_systems"] == initial.spec["connection_ids"]
    generated = db.get(AgentVersion, job.checkpoint["version_id"])
    assert generated.id != initial.id and "unchanged configuration" in generated.hypothesis
    usage = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert usage.role == "optimizer" and usage.tokens == 30
    assert usage.cost == job.spent == pytest.approx(30 * settings().estimated_token_cost)


@pytest.mark.asyncio
async def test_quality_policy_uses_measured_case_count_latency_and_objective(db, seeded):
    org, user, agent, initial, suite, _ = seeded
    spec = AgentSpec.model_validate(initial.spec)
    spec.rules.update(resolve_aliases=True, fuzzy_match=True)
    spec.quality_policy.minimum_cases = 100
    version = persist_version(db, agent, spec)
    evaluation = await evaluate_suite(db, version, suite)
    db.commit()
    assert evaluation.scorecard["score"] == 1
    assert evaluation.scorecard["distinct_cases"] == 36
    assert not can_promote(evaluation.scorecard, evaluation.scorecard, {"objective": "cost"})
    assert not can_promote(evaluation.scorecard, policy={"maximum_mean_latency_ms": 0})
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            response = client.post(f"/versions/{version.id}/approve")
            assert response.status_code == 409 and "distinct scenarios" in response.text
            member = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
            member.role = "editor"
            db.commit()
            changed = version.spec.copy()
            changed["quality_policy"] = {**changed["quality_policy"], "minimum_cases": 1}
            assert client.post(f"/agents/{agent.id}/versions", json=changed).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", [False, True])
async def test_test_designer_requires_review_then_executes_real_cases_without_duplicate_import(
    db, seeded, monkeypatch, unsafe
):
    org, user, agent, version, suite, _ = seeded
    for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == suite.id)):
        db.delete(case)
    db.commit()
    calls = []
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(
        "factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": ProposalProvider(calls, unsafe)})
    )
    job = new_job(db, agent, Budget())
    job.state = "BUILDING"
    await advance(db, job)
    db.commit()
    assert len(calls) == 1
    assert set(calls[0]) == {"requirements", "input_schema", "output_schema", "rules", "tools"}
    assert db.scalar(select(func.count()).select_from(EvaluationCase).where(EvaluationCase.suite_id == suite.id)) == 0
    usage = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert usage.role == "test_designer" and usage.tokens == 30
    if unsafe:
        assert job.state == "FAILED" and job.error == "PermissionError"
        return
    assert job.state == "WAITING_FOR_APPROVAL"
    assert len(job.checkpoint["test_proposals"]["cases"]) == 6
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            corrected = json.loads(json.dumps(job.checkpoint["test_proposals"]))
            assert corrected["cases"][0]["assertions"][0]["value"] == 901
            corrected["cases"][0]["assertions"][0]["value"] = 900
            member = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
            member.role = "editor"
            db.commit()
            assert client.post(f"/builds/{job.id}/test-proposals/accept", json=corrected).status_code == 403
            member.role = "admin"
            db.commit()
            response = client.post(f"/builds/{job.id}/test-proposals/accept", json=corrected)
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "BUILDING"
            assert client.post(f"/builds/{job.id}/test-proposals/accept", json=authored_proposal()).status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert db.scalar(select(func.count()).select_from(EvaluationCase).where(EvaluationCase.suite_id == suite.id)) == 6
    # Explicit deterministic execution mode runs the actual SDK fixture tool and grading,
    # rather than trusting the designer's expectations or overriding scorecards.
    monkeypatch.setattr(settings(), "execution_mode", "demo")
    for _ in range(30):
        await advance(db, job)
        db.commit()
        if job.state in {"FAILED", "READY_FOR_REVIEW", "BUDGET_EXHAUSTED"}:
            break
    assert job.state == "READY_FOR_REVIEW", (job.state, job.checkpoint)
    assert job.checkpoint["validation_scorecard"]["passed"] == 2
