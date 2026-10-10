"""The builder harness: read-only investigation, typed patches, and screened multi-candidate rounds."""

import json

import pytest
from agents import Agent, Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory.builder import apply_patch
from factory.config import settings
from factory.db import uid
from factory.evaluation import evaluate_suite
from factory.models import (
    AgentRecord,
    AgentVersion,
    BuildIteration,
    BuildJob,
    Connection,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    ExecutionEvent,
    Organization,
    UsageRecord,
)
from factory.optimizer_tools import REFUSED, Investigation
from factory.schemas import AgentSpec, Budget, Example, SpecPatch
from factory.security import encrypt
from factory.workflow import TERMINAL, advance, new_job, worker_tick


def cases_by_split(db, suite):
    grouped = {}
    for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == suite.id)):
        grouped.setdefault(case.split, []).append(case)
    return grouped


async def call(tools, name, **arguments):
    tool = next(t for t in tools if t.name == name)
    return json.loads(await tool.on_invoke_tool(None, json.dumps(arguments)))


@pytest.mark.asyncio
async def test_investigator_exposes_only_this_tenants_development_split(db, seeded):
    org, _, agent, initial, suite, connection = seeded
    connection.encrypted_secret = encrypt("tenant-credential-9f3a71c2")
    leaky = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Development case that quotes a credential",
        split="development",
        input={"text": "Harbor Bistro: 2 kg Tomatoes; note tenant-credential-9f3a71c2"},
        assertions=[{"path": "lines_count", "value": 1}],
    )
    db.add(leaky)
    db.flush()
    evaluation = await evaluate_suite(db, initial, suite, ("development", "regression", "validation"))
    job = new_job(db, agent, Budget())
    spec = AgentSpec.model_validate(initial.spec)
    investigation = Investigation(db, job, spec, evaluation.id, [{"hypothesis": "earlier"}])
    tools = investigation.tools()
    grouped = cases_by_split(db, suite)
    development_ids = {case.id for case in grouped["development"]}

    listed = await call(tools, "list_cases")
    assert {row["case_id"] for row in listed["cases"]} == development_ids
    detail = await call(tools, "get_case", case_id=grouped["development"][0].id)
    assert detail["trials"] and "checks" in detail["trials"][0] and "tool_sequence" in detail["trials"][0]

    # Regression and held-out cases are refused by identity, even though this run evaluated them.
    for split in ("regression", "validation"):
        refused = await call(tools, "get_case", case_id=grouped[split][0].id)
        assert refused == {"error": REFUSED}
    # A case from another tenant, an unknown id and an unknown tool are refused the same way.
    other_org = Organization(name="Other tenant")
    db.add(other_org)
    db.flush()
    other_agent = AgentRecord(
        org_id=other_org.id, project_id=agent.project_id, name="x", request="y" * 12, template="orders"
    )
    db.add(other_agent)
    db.flush()
    other_suite = EvaluationSuite(org_id=other_org.id, agent_id=other_agent.id, name="other")
    db.add(other_suite)
    db.flush()
    foreign = EvaluationCase(
        org_id=other_org.id,
        suite_id=other_suite.id,
        name="Foreign",
        split="development",
        input={"text": "x"},
        assertions=[],
    )
    db.add(foreign)
    db.flush()
    assert await call(tools, "get_case", case_id=foreign.id) == {"error": REFUSED}
    assert await call(tools, "get_case", case_id=uid()) == {"error": REFUSED}
    assert await call(tools, "get_tool_contract", tool_id=uid()) == {"error": REFUSED}
    assert len(investigation.denied) == 5
    assert (await call(tools, "get_tool_contract", tool_id=spec.tools[0]))["tool_id"] == spec.tools[0]
    assert (await call(tools, "get_attempt_history"))["attempts"] == [{"hypothesis": "earlier"}]

    # Tenant credential values are filtered from everything the tools return.
    quoted = await call(tools, "get_case", case_id=leaky.id)
    assert "tenant-credential-9f3a71c2" not in json.dumps(quoted)
    assert "tenant-credential-9f3a71c2" not in json.dumps(listed)

    # An evaluation owned by another tenant cannot be attached at all.
    foreign_run = EvaluationRun(org_id=other_org.id, version_id=initial.id, suite_id=other_suite.id)
    db.add(foreign_run)
    db.flush()
    with pytest.raises(PermissionError):
        Investigation(db, job, spec, foreign_run.id, [])


@pytest.mark.asyncio
async def test_investigator_call_budget_is_bounded(db, seeded):
    _, _, agent, initial, suite, _ = seeded
    evaluation = await evaluate_suite(db, initial, suite, ("development",))
    job = new_job(db, agent, Budget())
    investigation = Investigation(db, job, AgentSpec.model_validate(initial.spec), evaluation.id, [], call_cap=2)
    tools = investigation.tools()
    assert "cases" in await call(tools, "list_cases")
    assert "cases" in await call(tools, "list_cases")
    assert "budget" in (await call(tools, "list_cases"))["error"].lower()
    assert len(investigation.calls) == 2


def test_patch_cannot_name_locked_fields_and_scope_is_rechecked():
    spec = AgentSpec(
        name="n", purpose="p", template="custom", instructions="base", tools=["t1"], connection_ids=["c1"], max_cost=1
    )
    for locked in ("tools", "connection_ids", "guardrails", "quality_policy", "max_cost", "max_turns", "template"):
        with pytest.raises(ValueError):
            SpecPatch.model_validate({locked: spec.model_dump()[locked]})
    changed = apply_patch(spec, SpecPatch(instructions="better", rules={"margin": 0.3}, tool_notes={"t1": "note"}))
    assert changed.instructions == "better" and changed.rules["margin"] == 0.3
    assert changed.rules["check_inventory"] is True, "rules are merged, not replaced"
    assert changed.tools == ["t1"] and changed.guardrails == spec.guardrails
    assert changed.quality_policy == spec.quality_policy and changed.max_cost == spec.max_cost
    assert apply_patch(spec, SpecPatch()) == spec


def text(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


def tool_call(name, **arguments):
    return ResponseFunctionToolCall(
        type="function_call", name=name, arguments=json.dumps(arguments), call_id=uid(), id=uid()
    )


class ScriptedBuilder(Model):
    """Local provider transport for the real SDK loop. Each step is a tool call or a final answer."""

    def __init__(self, steps):
        self.steps, self.seen_outputs, self.payloads, self.tool_names = list(steps), [], [], []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        items = input if isinstance(input, list) else []
        self.tool_names = [tool.name for tool in tools]
        self.payloads.append(next(i["content"] for i in items if isinstance(i, dict) and i.get("role") == "user"))
        self.seen_outputs = [
            i["output"] for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"
        ]
        step = self.steps.pop(0)
        step = step(self) if callable(step) else step
        return ModelResponse(
            output=[step],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


async def optimizing_job(db, seeded, monkeypatch, steps, budget=None):
    """A build parked at OPTIMIZING with real demo-mode evidence, then switched to a live scripted builder."""
    _, _, agent, initial, suite, _ = seeded
    evaluation = await evaluate_suite(db, initial, suite, ("development", "regression"))
    from factory.evaluation import development_evidence

    job = new_job(db, agent, budget or Budget())
    job.state = "OPTIMIZING"
    job.checkpoint = {
        **job.checkpoint,
        "diagnosis": {"development_failures": development_evidence(db, evaluation)},
        "best_version_id": initial.id,
        "best_scorecard": evaluation.scorecard,
        "best_evaluation_id": evaluation.id,
    }
    db.commit()
    provider = ScriptedBuilder(steps)
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": provider}))
    return job, provider, evaluation


@pytest.mark.asyncio
async def test_live_optimizer_investigates_through_the_sdk_loop_and_returns_a_patch(db, seeded, monkeypatch):
    _, _, agent, initial, suite, _ = seeded
    grouped = cases_by_split(db, suite)
    regression_id = grouped["regression"][0].id

    def read_a_failure(provider):
        listed = json.loads(provider.seen_outputs[0])["cases"]
        failing = next(row for row in listed if not row["passed"])
        return tool_call("get_case", case_id=failing["case_id"])

    job, provider, _ = await optimizing_job(
        db,
        seeded,
        monkeypatch,
        [
            tool_call("list_cases"),
            read_a_failure,
            tool_call("get_case", case_id=regression_id),  # an attempt to read protected evidence
            text({"hypothesis": "Aliases are not resolved", "rules": {"resolve_aliases": True}}),
        ],
    )
    await advance(db, job)
    db.commit()
    assert job.state == "RETESTING", (job.state, job.error)
    created = db.get(AgentVersion, job.checkpoint["version_id"])
    assert created.id != initial.id and created.hypothesis == "Aliases are not resolved"
    assert created.spec["rules"]["resolve_aliases"] is True
    for locked in ("tools", "connection_ids", "guardrails", "quality_policy", "max_cost", "max_turns"):
        assert created.spec[locked] == initial.spec[locked]
    # The model saw a real development case, and only a refusal for the regression case.
    assert provider.tool_names == [
        "list_cases",
        "get_case",
        "get_tool_contract",
        "get_attempt_history",
        "propose_connection",
    ]
    assert json.loads(provider.seen_outputs[1])["trials"]
    assert json.loads(provider.seen_outputs[2]) == {"error": REFUSED}
    regression_names = {case.name for case in grouped["regression"]} | {case.name for case in grouped["validation"]}
    everything_seen = json.dumps(provider.seen_outputs) + json.dumps(provider.payloads)
    assert not any(name in everything_seen for name in regression_names)
    # Every model call was reserved and settled individually.
    records = list(db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id)))
    assert len(records) == 4 and all(r.status == "recorded" and r.role == "optimizer" for r in records)
    assert job.spent == pytest.approx(4 * 30 * settings().estimated_token_cost)
    audit = db.scalar(
        select(ExecutionEvent).where(ExecutionEvent.job_id == job.id, ExecutionEvent.kind == "optimizer_investigation")
    )
    assert len(audit.payload["calls"]) == 2 and len(audit.payload["denied"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["locked_field", "held_out_example", "endless_tools"])
async def test_a_bad_proposal_is_rejected_without_failing_the_build(db, seeded, monkeypatch, violation):
    _, _, agent, initial, suite, _ = seeded
    grouped = cases_by_split(db, suite)
    held_out = grouped["validation"][0]
    if violation == "locked_field":
        steps = [text({"hypothesis": "Grab a tool", "tools": [uid()]})]
    elif violation == "held_out_example":
        example = {"input": held_out.input, "output": {"requires_approval": True}}
        steps = [text({"hypothesis": "Memorise the answer", "examples": [example]})]
    else:
        steps = [tool_call("list_cases") for _ in range(30)]
    job, _, _ = await optimizing_job(db, seeded, monkeypatch, steps, Budget(stagnation_limit=5))
    before = db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id))
    await advance(db, job)
    db.commit()
    assert job.state == "OPTIMIZING" and job.error is None, (job.state, job.error)
    assert db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)) == before
    assert job.checkpoint["stagnation"] == 1
    assert job.checkpoint["attempts"][-1]["rejected_before_evaluation"]
    assert job.checkpoint["version_id"] == initial.id, "the parent is unchanged"
    # The usage of the rejected attempt is still charged.
    assert job.spent > 0


def scripted_proposals(monkeypatch, changes):
    """Replace the optimizer with fixed rule changes so the round mechanics are tested deterministically."""
    calls = []

    async def scripted(spec, development_failures, **kwargs):
        calls.append({"parent": spec.model_copy(deep=True), **kwargs})
        candidate = spec.model_copy(deep=True)
        name, rules = changes[(len(calls) - 1) % len(changes)]
        candidate.rules.update(rules)
        return candidate, name

    monkeypatch.setattr("factory.workflow.optimize", scripted)
    return calls


async def run(db, job, limit=1500):
    for _ in range(limit):
        await advance(db, job)
        db.commit()
        if job.state in TERMINAL:
            return
    raise AssertionError((job.state, job.checkpoint.get("round")))


@pytest.mark.asyncio
async def test_round_screens_candidates_and_fully_evaluates_only_survivors(db, seeded, monkeypatch):
    _, _, agent, initial, suite, _ = seeded
    calls = scripted_proposals(
        monkeypatch,
        [
            ("Bypass stock", {"check_inventory": False}),  # fixes no development failure
            ("Resolve aliases", {"resolve_aliases": True}),
            ("Aliases and typos", {"resolve_aliases": True, "fuzzy_match": True}),
        ],
    )
    job = new_job(db, agent, Budget(candidates_per_round=3, max_iterations=6))
    await run(db, job)
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint.get("stop_reason"))
    versions = {v.hypothesis: v for v in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id))}
    # All three proposals of the round came from the same best parent.
    assert len(calls) == 3
    assert all(c["parent"].rules == AgentSpec.model_validate(initial.spec).rules for c in calls)
    assert [c["strategy"] for c in calls] == [calls[0]["strategy"], calls[1]["strategy"], calls[2]["strategy"]]
    assert len({c["strategy"] for c in calls}) == 3, "each proposal gets a different strategy"
    screens = list(db.scalars(select(EvaluationRun).where(EvaluationRun.status == "screen")))
    assert len(screens) == 3
    development = {c.id for c in cases_by_split(db, suite)["development"]}
    for screen in screens:
        results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == screen.id)))
        assert results and {r.case_id for r in results} <= development
        assert len(results) < len(development), "a screen is cheaper than the development split"
    # The candidate that fixed nothing was pruned and never got a full evaluation.
    evaluated = {it.version_id for it in db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id))}
    assert versions["Bypass stock"].id not in evaluated
    # The survivor that fixed the most was evaluated first and promoted; the other survivor was not needed.
    assert versions["Aliases and typos"].id in evaluated and versions["Resolve aliases"].id not in evaluated
    assert agent.best_version_id == versions["Aliases and typos"].id
    pruned = [a for a in job.checkpoint["attempts"] if a.get("pruned_in_screen")]
    assert [a["hypothesis"] for a in pruned] == ["Bypass stock"] and pruned[0]["fixed_cases"] == 0
    assert "round" not in job.checkpoint
    # Screen runs are never promotion evidence.
    completed = list(
        db.scalars(
            select(EvaluationRun).where(
                EvaluationRun.version_id == versions["Bypass stock"].id, EvaluationRun.status == "completed"
            )
        )
    )
    assert completed == []


@pytest.mark.asyncio
async def test_rejected_survivor_hands_over_to_the_next_without_new_proposals(db, seeded, monkeypatch):
    _, _, agent, initial, _, _ = seeded
    calls = scripted_proposals(
        monkeypatch,
        [
            # Fixes the most development failures but breaks a critical regression case.
            ("Everything and bypass stock", {"resolve_aliases": True, "fuzzy_match": True, "check_inventory": False}),
            ("Resolve aliases", {"resolve_aliases": True}),
        ],
    )
    job = new_job(db, agent, Budget(candidates_per_round=2, max_iterations=8))
    iterations = []
    for _ in range(1500):
        await advance(db, job)
        db.commit()
        iterations = list(
            db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number))
        )
        if len(iterations) >= 3 or job.state in TERMINAL:
            break
    hypotheses = [db.get(AgentVersion, it.version_id).hypothesis for it in iterations]
    assert hypotheses[1:] == ["Everything and bypass stock", "Resolve aliases"]
    assert [it.promoted for it in iterations] == [True, False, True]
    assert len(calls) == 2, "the second survivor was evaluated without asking for new proposals"
    assert agent.best_version_id == iterations[2].version_id
    assert db.get(AgentVersion, agent.best_version_id).spec["rules"]["check_inventory"] is True


@pytest.mark.asyncio
async def test_screened_round_survives_a_worker_restart_without_duplicate_results(db, seeded, monkeypatch):
    _, _, agent, _, _, _ = seeded
    scripted_proposals(
        monkeypatch,
        [
            ("Bypass stock", {"check_inventory": False}),
            ("Resolve aliases", {"resolve_aliases": True}),
            ("Aliases and typos", {"resolve_aliases": True, "fuzzy_match": True}),
        ],
    )
    job = new_job(db, agent, Budget(candidates_per_round=3, max_iterations=6))
    db.commit()
    first = sessionmaker(db.get_bind(), expire_on_commit=False)
    for _ in range(400):
        await worker_tick(first)
        db.expire_all()
        if db.get(BuildJob, job.id).state == "SCREENING":
            break
    assert db.get(BuildJob, job.id).state == "SCREENING"
    for _ in range(3):  # stop part-way through a screen
        await worker_tick(first)
    # A fresh sessionmaker represents a new worker process over the same persistent database.
    second = sessionmaker(db.get_bind(), expire_on_commit=False)
    for _ in range(1500):
        await worker_tick(second)
        db.expire_all()
        if db.get(BuildJob, job.id).state in TERMINAL:
            break
    assert db.get(BuildJob, job.id).state == "READY_FOR_REVIEW"
    duplicates = db.execute(
        select(EvaluationResult.evaluation_run_id, EvaluationResult.case_id, EvaluationResult.trial, func.count())
        .group_by(EvaluationResult.evaluation_run_id, EvaluationResult.case_id, EvaluationResult.trial)
        .having(func.count() > 1)
    ).all()
    assert duplicates == []
    assert db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status == "screen")) == 3
    assert db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status == "screening")) == 0


@pytest.mark.asyncio
async def test_single_candidate_round_keeps_the_original_flow(db, seeded):
    _, _, agent, _, _, _ = seeded
    job = new_job(db, agent, Budget())
    await run(db, job)
    assert job.state == "READY_FOR_REVIEW"
    assert db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status == "screen")) == 0
    assert [it.promoted for it in db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id))] == [
        True
    ] * 3


def test_examples_in_a_patch_are_typed():
    patch = SpecPatch(examples=[Example(input={"text": "a"}, output={"ok": True})])
    assert patch.examples[0].source_case is None
    assert Connection is not None  # models import stays exercised


def test_structured_replies_are_validated_identically_in_both_modes():
    from agents import ModelBehaviorError

    from factory.builder import parse_structured

    patch = parse_structured(
        SpecPatch, 'Sure. Here it is:\n```json\n{"hypothesis": "x", "rules": {"margin": 0.3}}\n```'
    )
    assert patch.rules == {"margin": 0.3}
    assert parse_structured(SpecPatch, {"hypothesis": "y"}).hypothesis == "y"
    assert parse_structured(SpecPatch, SpecPatch(hypothesis="z")).hypothesis == "z"
    for bad in ("no json here", '{"tools": ["grab"]}', '{"hypothesis": 5', "{}}"):
        with pytest.raises(ModelBehaviorError):
            parse_structured(SpecPatch, bad)


@pytest.mark.asyncio
async def test_prompt_mode_sends_no_schema_to_the_provider_and_still_enforces_the_patch(db, seeded, monkeypatch):
    _, _, agent, initial, _, _ = seeded
    seen = {}

    class TextOnly(Model):
        def __init__(self, reply):
            self.reply = reply

        async def get_response(
            self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        ):
            seen["schema"], seen["instructions"] = output_schema, system_instructions
            item = ResponseOutputMessage(
                type="message",
                role="assistant",
                id=uid(),
                status="completed",
                content=[ResponseOutputText(type="output_text", text=self.reply, annotations=[])],
            )
            return ModelResponse(output=[item], usage=Usage(requests=1, total_tokens=30), response_id=uid())

        async def stream_response(self, *args, **kwargs):
            raise NotImplementedError
            yield

    monkeypatch.setattr(settings(), "openai_structured_output", "prompt")
    job, _, _ = await optimizing_job(db, seeded, monkeypatch, [], Budget(investigator_turns=0, stagnation_limit=5))
    reply = 'Here is the patch: {"hypothesis": "Resolve aliases", "rules": {"resolve_aliases": true}} Hope it helps.'
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": TextOnly(reply)}))
    await advance(db, job)
    db.commit()
    assert job.state == "RETESTING", (job.state, job.error)
    assert seen["schema"] is None, "no JSON Schema is sent to the provider in prompt mode"
    assert "It must validate against this JSON Schema" in seen["instructions"]
    assert db.get(AgentVersion, job.checkpoint["version_id"]).spec["rules"]["resolve_aliases"] is True

    # A reply that tries to name a locked field is still rejected, not applied.
    job2_agent_versions = db.scalar(
        select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)
    )
    job.state = "OPTIMIZING"
    job.checkpoint = {**job.checkpoint, "version_id": initial.id}
    job.checkpoint.pop("round", None)
    db.commit()
    monkeypatch.setattr(
        "factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": TextOnly('{"tools": ["everything"]}')})
    )
    await advance(db, job)
    db.commit()
    assert job.error is None and job.checkpoint["attempts"][-1]["rejected_before_evaluation"]
    assert (
        db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id))
        == job2_agent_versions
    )
