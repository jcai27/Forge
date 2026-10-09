import json

import pytest
from agents import Model, ModelResponse, Usage
from fastapi.testclient import TestClient
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import func, select

from factory.api import app, limits
from factory.builder import persist_version
from factory.config import settings
from factory.connectors import discover_connection
from factory.db import get_db, uid
from factory.evaluation import can_promote, evaluate_case, evaluate_suite, scorecard
from factory.fixtures import business_snapshot
from factory.models import (
    Approval,
    Connection,
    DataSource,
    EvaluationCase,
    EvaluationRun,
    ExecutionRun,
    Membership,
    ToolDefinition,
)
from factory.runtime import reconstruct_agent
from factory.schemas import AgentSpec
from factory.security import token_for


class ProviderContractModel(Model):
    """Local provider transport for the real SDK loop; outputs derive from tool results."""

    def __init__(self, read_tool, send_tool=None):
        self.read_tool, self.send_tool = read_tool, send_tool
        self.step = 0

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        self.step += 1
        responses = [
            json.loads(item["output"])
            for item in input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        if self.step == 1:
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=self.read_tool,
                    arguments=json.dumps({"resource": "catalog"}),
                    call_id=uid(),
                    id=uid(),
                )
            ]
        elif self.step == 2 and self.send_tool:
            # Secret fields from connected records never reach the model transport.
            assert responses[0]["records"][0].get("password") in (None, "[REDACTED]")
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=self.send_tool,
                    arguments=json.dumps(
                        {"to": "ops@example.invalid", "subject": "Catalog", "body": "Catalog checked"}
                    ),
                    call_id=uid(),
                    id=uid(),
                )
            ]
        else:
            result = {"records_count": len(responses[0]["records"]), "sent": bool(responses[-1].get("accepted", False))}
            output = [
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=json.dumps(result), annotations=[])],
                )
            ]
        return ModelResponse(
            output=output, usage=Usage(requests=1, input_tokens=5, output_tokens=5, total_tokens=10), response_id=uid()
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.fixture
def provider_model(monkeypatch):
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(settings(), "execution_mode", "live")

    def install(read, send=None):
        def bind(context, mode):
            agent = reconstruct_agent(context, mode)
            agent.model = ProviderContractModel(
                "t_" + read.replace("-", "_"), "t_" + send.replace("-", "_") if send else None
            )
            return agent

        monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)

    return install


@pytest.mark.asyncio
async def test_state_schema_and_sequence_assertions_use_fresh_forks(db, seeded):
    org, _, _, version, suite, _ = seeded
    before = business_snapshot(db, org.id)
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Approved isolated order",
        split="regression",
        source="synthetic",
        input={"text": "Harbor Bistro: 2 kg Tomatoes", "approve_in_test": True},
        trials=3,
        assertions=[
            {
                "scope": "state",
                "path": "products",
                "op": "contains_record",
                "value": {"sku": "SKU-001", "stock": 148},
                "category": "business_rule_compliance",
            },
            {
                "scope": "state",
                "path": "orders",
                "op": "contains_record",
                "value": {"customer_id": "C-001", "total_cents": 900},
            },
            {"path": "tool_sequence", "value": ["prepare_operation"], "category": "tool_correctness"},
            {
                "op": "json_schema",
                "path": "$",
                "schema": {
                    "type": "object",
                    "required": ["customer_id", "lines", "total_cents"],
                    "properties": {"total_cents": {"const": 900}},
                },
            },
        ],
    )
    db.add(case)
    db.flush()
    evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    for trial in range(3):
        result = await evaluate_case(db, evaluation, version, case, trial)
        assert result.passed, result.checks
    card = scorecard(db, evaluation)
    assert card["variability"]["repeated_cases"] == 1
    assert card["variability"]["unstable_cases"] == 0
    assert card["variability"]["cases"][case.id] == {
        "trials": 3,
        "pass_rate": 1,
        "standard_deviation": 0,
        "min": 1,
        "max": 1,
    }
    assert business_snapshot(db, org.id) == before
    assert db.scalar(select(func.count()).select_from(Approval).where(Approval.org_id == org.id)) == 0
    case.assertions = [{"path": "tool_sequence", "value": ["send_email"], "category": "tool_correctness"}]
    wrong = await evaluate_case(db, evaluation, version, case, 3)
    assert not wrong.passed and "tool_correctness" in wrong.failures


@pytest.mark.asyncio
async def test_replay_runs_multi_tool_sdk_and_simulates_write_without_network(db, seeded, provider_model, monkeypatch):
    org, user, agent, initial, suite, _ = seeded
    file = Connection(org_id=org.id, name="Records", kind="file", permissions={"read": True}, status="connected")
    email = Connection(
        org_id=org.id,
        name="Mock email",
        kind="email",
        config={"provider": "mock"},
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add_all([file, email])
    db.flush()
    await discover_connection(db, file)
    await discover_connection(db, email)
    read = db.scalar(select(ToolDefinition).where(ToolDefinition.connection_id == file.id))
    send = db.scalar(
        select(ToolDefinition).where(ToolDefinition.connection_id == email.id, ToolDefinition.name == "send_email")
    )
    spec = AgentSpec.model_validate(initial.spec)
    agent.template = spec.template = "custom"
    spec.connection_ids, spec.tools = [file.id, email.id], [read.id, send.id]
    spec.output_schema = {
        "type": "object",
        "required": ["records_count", "sent"],
        "properties": {"records_count": {"type": "integer"}, "sent": {"type": "boolean"}},
        "additionalProperties": False,
    }
    version = persist_version(db, agent, spec)
    provider_model(read.id, send.id)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Replay must never construct a live adapter")

    monkeypatch.setattr("factory.runtime.adapter", forbidden_network)
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Recorded catalog and email",
        source="replay",
        split="development",
        input={"text": "Read approved catalog and notify operations"},
        assertions=[
            {"path": "records_count", "value": 1},
            {"path": "sent", "value": True},
            {"path": "tool_sequence", "value": ["read_file", "send_email"]},
        ],
        environment={
            "replay": [
                {
                    "tool_id": read.id,
                    "arguments": {"resource": "catalog"},
                    "response": {"records": [{"sku": "SKU-001", "password": "private-value"}]},
                },
                {
                    "tool_id": send.id,
                    "arguments": {"to": "ops@example.invalid", "subject": "Catalog", "body": "Catalog checked"},
                    "response": {"accepted": True},
                },
            ]
        },
    )
    db.add(case)
    evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    result = await evaluate_case(db, evaluation, version, case)
    assert result.passed, result.checks
    run = db.get(ExecutionRun, result.execution_id)
    assert run.metrics["tokens"] == 30
    assert run.metrics["cost"] == pytest.approx(30 * settings().estimated_token_cost)
    assert not db.scalar(select(Approval).where(Approval.run_id == run.id))
    case.source = "synthetic"
    denied = await evaluate_case(db, evaluation, version, case, 1)
    assert not denied.passed
    assert db.get(ExecutionRun, denied.execution_id).error == "PermissionError"
    case.source = "replay"
    case.environment = {"replay": [{**case.environment["replay"][0], "arguments": {"resource": "different"}}]}
    mismatched = await evaluate_case(db, evaluation, version, case, 2)
    assert not mismatched.passed
    assert db.get(ExecutionRun, mismatched.execution_id).error == "ValueError"
    from factory.connectors import adapter

    db.add(
        DataSource(
            org_id=org.id,
            connection_id=file.id,
            name="catalog",
            schema={"type": "object"},
            records=[{"sku": "SKU-001"}],
            model_visible=True,
        )
    )
    case.source = "live_read_only"
    case.authorized_by = user.id
    case.environment = {"live_connection_ids": [file.id, email.id]}
    accesses = []

    def observed_adapter(session, connection, **kwargs):
        accesses.append(connection.id)
        return adapter(session, connection, **kwargs)

    monkeypatch.setattr("factory.runtime.adapter", observed_adapter)
    attempted_write = await evaluate_case(db, evaluation, version, case, 3)
    failed_run = db.get(ExecutionRun, attempted_write.execution_id)
    assert failed_run.error == "PermissionError"
    assert "safety" in attempted_write.failures
    assert accesses == [file.id]
    assert not db.scalar(select(Approval).where(Approval.run_id == failed_run.id))


@pytest.mark.asyncio
async def test_live_read_only_requires_admin_grant_and_rechecks_it(db, seeded, provider_model):
    org, user, agent, initial, suite, _ = seeded
    file = Connection(
        org_id=org.id, name="Approved imported records", kind="file", permissions={"read": True}, status="connected"
    )
    db.add(file)
    db.flush()
    db.add(
        DataSource(
            org_id=org.id,
            connection_id=file.id,
            name="catalog",
            schema={"type": "object"},
            records=[{"sku": "SKU-001"}],
            model_visible=True,
        )
    )
    await discover_connection(db, file)
    read = db.scalar(select(ToolDefinition).where(ToolDefinition.connection_id == file.id))
    spec = AgentSpec.model_validate(initial.spec)
    agent.template = spec.template = "custom"
    spec.connection_ids, spec.tools = [file.id], [read.id]
    spec.output_schema = {"type": "object", "required": ["records_count", "sent"]}
    version = persist_version(db, agent, spec)
    provider_model(read.id)
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Authorized read",
        source="live_read_only",
        split="development",
        input={"text": "Inspect catalog"},
        assertions=[{"path": "records_count", "value": 1}],
        environment={"live_connection_ids": [file.id]},
        authorized_by=user.id,
    )
    db.add(case)
    evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    assert (await evaluate_case(db, evaluation, version, case)).passed
    member = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
    member.role = "editor"
    with pytest.raises(PermissionError, match="revoked"):
        await evaluate_case(db, evaluation, version, case, 1)


@pytest.mark.asyncio
async def test_human_review_cannot_override_failed_assertions_and_is_audited(db, seeded):
    org, user, _, version, suite, _ = seeded
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            response = client.post(
                f"/suites/{suite.id}/cases",
                json={
                    "name": "Human reviewed order",
                    "source": "human",
                    "split": "development",
                    "input": {"text": "Harbor Bistro: 2 kg Tomatoes"},
                    "assertions": [{"path": "total_cents", "value": 999}],
                },
            )
            assert response.status_code == 201, response.text
            case = db.get(EvaluationCase, response.json()["id"])
            evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
            db.add(evaluation)
            db.flush()
            result = await evaluate_case(db, evaluation, version, case)
            db.commit()
            assert "human_review" in result.failures
            decision = client.post(
                f"/evaluation-results/{result.id}/review",
                json={"passed": True, "evidence": "Operator confirms the prepared order is understandable"},
            )
            assert decision.status_code == 200, decision.text
            assert decision.json()["passed"] is False
            assert "structured_accuracy" in decision.json()["failures"]
            assert "human_review" not in decision.json()["failures"]
            assert (
                client.post(
                    f"/evaluation-results/{result.id}/review",
                    json={"passed": True, "evidence": "Repeated approval is not permitted"},
                ).status_code
                == 409
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unavailable_qualitative_grader_is_pending_not_an_invented_score(db, seeded):
    org, user, _, version, suite, _ = seeded
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Qualitative coordination",
        source="synthetic",
        split="development",
        input={"text": "Harbor Bistro: 2 kg Rice"},
        assertions=[],
        rubric={"criteria": ["States the customer and requested quantities clearly"], "threshold": 0.8},
    )
    db.add(case)
    db.flush()
    evaluation = await evaluate_suite(db, version, suite)
    assert evaluation.scorecard["pending_reviews"] == 1
    assert not can_promote(evaluation.scorecard)
    from factory.models import EvaluationResult

    result = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.case_id == case.id, EvaluationResult.evaluation_run_id == evaluation.id
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            response = client.post(f"/evaluation-results/{result.id}/grade")
            assert response.status_code == 200, response.text
            assert response.json()["passed"] is False
            assert next(check for check in response.json()["checks"] if check["category"] == "qualitative")["pending"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pending_human_review_pauses_build_and_resume_preserves_trial_evidence(db, seeded):
    from factory.api import review_result
    from factory.models import EvaluationResult
    from factory.schemas import Budget, HumanReview
    from factory.security import Principal
    from factory.workflow import advance, control, new_job

    org, user, agent, _, suite, _ = seeded
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Review prepared customer order",
        source="human",
        split="development",
        input={"text": "Harbor Bistro: 2 kg Tomatoes"},
        assertions=[{"path": "total_cents", "value": 900}],
    )
    db.add(case)
    job = new_job(db, agent, Budget())
    for _ in range(100):
        await advance(db, job)
        db.commit()
        if job.state == "WAITING_FOR_APPROVAL":
            break
    assert job.state == "WAITING_FOR_APPROVAL"
    evaluation_id = job.checkpoint["evaluation_id"]
    result = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.evaluation_run_id == evaluation_id, EvaluationResult.case_id == case.id
        )
    )
    assert result and not result.passed
    review_result(
        result.id,
        HumanReview(passed=True, evidence="Operator independently verified SKU, pricing and approval behavior"),
        Principal(user.id, org.id, "admin"),
        db,
    )
    control(db, job, "resume")
    assert job.state == "TESTING"
    await advance(db, job)
    assert job.state == "ANALYZING"
    assert job.checkpoint["evaluation_id"] == evaluation_id
    assert db.get(EvaluationRun, evaluation_id).scorecard["pending_reviews"] == 0


@pytest.mark.asyncio
async def test_qualitative_budget_blocks_provider_before_another_call(db, seeded, monkeypatch):
    from agents import Agent

    from factory.qualitative import grade_rubric

    org, _, _, version, suite, _ = seeded
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    calls = []

    class NoBudgetModel(ProviderContractModel):
        async def get_response(self, *args, **kwargs):
            calls.append(True)
            raise AssertionError("Insufficient budget must reject before provider dispatch")

    def model_agent(**kwargs):
        return Agent(**{**kwargs, "model": NoBudgetModel("unused")})

    monkeypatch.setattr("factory.qualitative.Agent", model_agent)
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Qualitative budget",
        source="synthetic",
        split="development",
        input={},
        assertions=[],
        rubric={"criteria": ["Is clear"], "threshold": 0.8},
    )
    run = ExecutionRun(
        org_id=org.id,
        version_id=version.id,
        mode="live",
        input={},
        output={},
        metrics={"cost": version.spec["max_cost"], "tokens": 0},
    )
    db.add(run)
    db.flush()
    checks = await grade_rubric(db, version, run, case)
    assert checks[0]["pending"] and not checks[0]["passed"]
    assert checks[0]["evidence"].endswith("ValueError")
    assert calls == []
    assert run.metrics["grading_cost"] == 0


@pytest.mark.asyncio
async def test_imported_mapping_requires_visibility_and_minimizes_isolated_state(db, seeded):
    org, user, agent, initial, suite, _ = seeded
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            file = client.post("/integrations", json={"name": "Imported catalog", "kind": "file"}).json()
            content = b"product_id,product_name,unit,cost,price,available,private_note\nSKU-001,Tomatoes,kg,250,450,12,unrelated private data\n"
            source = client.post(
                f"/integrations/{file['id']}/import", files={"file": ("catalog.csv", content, "text/csv")}
            ).json()
            spec = AgentSpec.model_validate(initial.spec)
            spec.connection_ids.append(file["id"])
            version = persist_version(db, agent, spec)
            db.commit()
            body = {
                "name": "Minimized imported catalog",
                "source": "replay",
                "split": "development",
                "input": {"text": "Harbor Bistro: 2 kg Tomatoes", "approve_in_test": True},
                "environment": {
                    "data_mappings": [
                        {
                            "source_id": source["id"],
                            "collection": "products",
                            "fields": {
                                "sku": "product_id",
                                "name": "product_name",
                                "unit": "unit",
                                "supplier_cents": "cost",
                                "price_cents": "price",
                                "stock": "available",
                            },
                        }
                    ]
                },
                "assertions": [
                    {
                        "scope": "state",
                        "path": "products",
                        "op": "contains_record",
                        "value": {"sku": "SKU-001", "stock": 10},
                    },
                    {
                        "scope": "state",
                        "path": "products",
                        "op": "json_schema",
                        "schema": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "sku": {},
                                    "name": {},
                                    "unit": {},
                                    "supplier_cents": {},
                                    "price_cents": {},
                                    "stock": {},
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    {"path": "total_cents", "value": 900},
                ],
            }
            assert client.post(f"/suites/{suite.id}/cases", json=body).status_code == 403
            assert client.patch(f"/data-sources/{source['id']}", json={"model_visible": True}).status_code == 200
            response = client.post(f"/suites/{suite.id}/cases", json=body)
            assert response.status_code == 201, response.text
            case = db.get(EvaluationCase, response.json()["id"])
            evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
            db.add(evaluation)
            db.flush()
            result = await evaluate_case(db, evaluation, version, case)
            assert result.passed, result.checks
            assert business_snapshot(db, org.id)["products"][0]["stock"] != 10
            assert "unrelated private data" not in json.dumps(result.checks)
            client.patch(f"/data-sources/{source['id']}", json={"model_visible": False})
            with pytest.raises(PermissionError, match="model-authorized"):
                await evaluate_case(db, evaluation, version, case, 1)
    finally:
        app.dependency_overrides.clear()
