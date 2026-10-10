"""What keeps a real build trustworthy: provider failures are not scored, trials run side by side with
sound accounting, the final held-out score survives a tight budget, and waiting is not charged."""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import openai
import pytest
from agents import Agent, Model
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_intake import TOPICS, Builder, TicketAgent, as_csv, direct_agent, reply, tickets, user_text

from factory.api import app, limits
from factory.builder import apply_patch, persist_version
from factory.config import mode_for, settings
from factory.db import get_db, now
from factory.deployment_runtime import invocation_tick
from factory.evaluation import changed_selection_cases, confusions, selection_flips, verifiers_rejecting
from factory.models import (
    AgentRecord,
    AgentVersion,
    BuildJob,
    Dataset,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    ExecutionEvent,
    ExecutionRun,
    Membership,
    Organization,
    UsageRecord,
    User,
)
from factory.pricing import provider_unavailable, usage_cost
from factory.runtime import relevant_examples
from factory.schemas import AgentSpec, Budget, Example, SpecPatch, Verifier
from factory.security import passwords, token_for
from factory.workflow import TERMINAL, advance, control, new_job, pass_needs, transition

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    org, user, *_ = seeded
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def unreachable():
    return openai.APIConnectionError(request=REQUEST)


def live(monkeypatch, builder, agent_model):
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.workflow.RETRY_DELAYS", (0, 0, 0))
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = agent_model
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)


def with_data(client, seeded, development=12, selection=12, validation=8, rows=30, content=None):
    created = direct_agent(client, seeded)
    made = client.post(
        f"/agents/{created['id']}/datasets",
        json={
            "name": "Support tickets",
            "content": content or as_csv(tickets(rows)),
            "development": development,
            "selection": selection,
            "validation": validation,
        },
    )
    assert made.status_code == 201, made.text
    return created


async def run_to_end(db, job, limit=600):
    for _ in range(limit):
        if job.state in TERMINAL or job.state == "PAUSED":
            break
        await advance(db, job)
        db.commit()
    return job


class Flaky(TicketAgent):
    """A deployed agent whose provider drops the first calls and then answers correctly."""

    def __init__(self, failures):
        super().__init__()
        self.failures, self.calls = failures, 0

    async def get_response(self, system_instructions, input, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise unreachable()
        payload = json.loads(user_text(input))
        return reply({"category": payload.get("input", payload)["text"].split()[0]})


def test_only_provider_side_failures_count_as_the_provider_being_unavailable():
    assert provider_unavailable(unreachable())
    assert provider_unavailable(openai.APITimeoutError(request=REQUEST))
    response = httpx.Response(429, request=REQUEST)
    assert provider_unavailable(openai.RateLimitError("slow down", response=response, body=None))
    wrapped = RuntimeError("agent run failed")
    wrapped.__cause__ = unreachable()
    assert provider_unavailable(wrapped)
    # The agent's own failures are the agent's.
    assert not provider_unavailable(ValueError("bad output"))
    assert not provider_unavailable(TimeoutError())
    bad = httpx.Response(400, request=REQUEST)
    assert not provider_unavailable(openai.BadRequestError("bad request", response=bad, body=None))


@pytest.mark.asyncio
async def test_calls_the_provider_dropped_are_run_again_and_never_scored_as_wrong(client, seeded, db, monkeypatch):
    created = with_data(client, seeded)
    agent_model = Flaky(failures=11)
    live(monkeypatch, Builder(), agent_model)
    monkeypatch.setattr(settings(), "evaluation_concurrency", 4)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint.get("waiting_reason"))
    # Every answer the agent actually gave was right, so the dropped calls left no mark on any score.
    rounds = job.checkpoint["best_scorecard"]
    assert rounds["score"] == 1 and job.checkpoint["validation_scorecard"]["score"] == 1
    results = list(db.scalars(select(EvaluationResult)))
    assert all(result.passed for result in results)
    keys = [(result.evaluation_run_id, result.case_id, result.trial) for result in results]
    assert len(keys) == len(set(keys)), "a trial was recorded twice"
    # The dropped calls are on record as runs that did not count, and as events on the build.
    dropped = [run for run in db.scalars(select(ExecutionRun)) if run.metrics.get("provider_unavailable")]
    assert len(dropped) == 11 and all(run.status == "failed" for run in dropped)
    assert {result.execution_id for result in results}.isdisjoint({run.id for run in dropped})
    assert db.scalar(
        select(func.count()).select_from(ExecutionEvent).where(ExecutionEvent.kind == "provider_unavailable")
    )
    assert "provider_failures" not in job.checkpoint and "not_before" not in job.checkpoint


@pytest.mark.asyncio
async def test_a_provider_that_stays_down_pauses_the_build_which_resumes_where_it_stopped(
    client, seeded, db, monkeypatch
):
    created = with_data(client, seeded)
    agent_model = Flaky(failures=10**6)
    live(monkeypatch, Builder(), agent_model)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "PAUSED" and job.error is None
    assert job.checkpoint["resume_state"] == "TESTING" and "could not be reached" in job.checkpoint["waiting_reason"]
    assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 0
    # The connection comes back; a person resumes; the build finishes as if nothing had happened.
    agent_model.failures = 0
    control(db, job, "resume")
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW" and job.checkpoint["validation_scorecard"]["score"] == 1
    # The reason for the pause went with it.
    assert "waiting_reason" not in job.checkpoint and "resume_state" not in job.checkpoint


@pytest.mark.asyncio
async def test_a_builder_step_the_provider_dropped_is_retried_not_fatal(client, seeded, db, monkeypatch):
    created = with_data(client, seeded)

    class DroppedOnce(Builder):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            payload = json.loads(user_text(input))
            if "baseline" not in payload and not any(r["role"] == "dropped" for r in self.requests):
                self.requests.append({"role": "dropped", "payload": {}, "tools": []})
                raise unreachable()
            return await super().get_response(system_instructions, input, *args, **kwargs)

    builder = DroppedOnce()
    live(monkeypatch, builder, TicketAgent())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW" and job.error is None
    assert [request["role"] for request in builder.requests] == ["architect", "dropped", "optimizer"]


class Slow(TicketAgent):
    """Answers correctly after a pause, recording how many requests were in flight together."""

    def __init__(self):
        super().__init__()
        self.active = self.peak = 0

    async def get_response(self, system_instructions, input, *args, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            payload = json.loads(user_text(input))
            return reply({"category": payload.get("input", payload)["text"].split()[0]})
        finally:
            self.active -= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [1, 6])
async def test_trials_run_side_by_side_with_every_result_once_and_spend_that_adds_up(
    client, seeded, db, monkeypatch, width
):
    created = with_data(client, seeded)
    agent_model = Slow()
    live(monkeypatch, Builder(), agent_model)
    monkeypatch.setattr(settings(), "evaluation_concurrency", width)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error)
    assert agent_model.peak == width
    results = list(db.scalars(select(EvaluationResult)))
    keys = [(result.evaluation_run_id, result.case_id, result.trial) for result in results]
    assert len(keys) == len(set(keys)) == 12 + 12 + 8
    # The build's spend is exactly its recorded usage: nothing lost or counted twice between sessions.
    recorded = db.scalar(select(func.sum(UsageRecord.cost)).where(UsageRecord.job_id == job.id))
    assert job.spent == pytest.approx(recorded) and job.spent > 0
    assert not db.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.status != "recorded"))
    events = list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.kind == "evaluation_case")))
    assert len(events) == len(results)


@pytest.mark.asyncio
async def test_cancelling_during_a_parallel_pass_stops_it(client, seeded, db, monkeypatch):
    created = with_data(client, seeded)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    class Cancelled(Slow):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            if not self.seen:
                self.seen.append("cancelled")
                with sessions() as other:
                    control(other, other.get(BuildJob, job.id), "cancel")
                    other.commit()
            return await super().get_response(system_instructions, input, *args, **kwargs)

    live(monkeypatch, Builder(), Cancelled())
    monkeypatch.setattr(settings(), "evaluation_concurrency", 4)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "CANCELLED"
    assert db.scalar(select(func.count()).select_from(EvaluationResult)) < 24


@pytest.mark.asyncio
async def test_a_build_short_of_money_still_ends_with_a_held_out_score(client, seeded, db, monkeypatch):
    created = with_data(client, seeded)

    class Stuck(Builder):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            payload = json.loads(user_text(input))
            if "baseline" in payload:
                return await super().get_response(system_instructions, input, *args, **kwargs)
            self.requests.append({"role": "optimizer", "payload": payload, "tools": []})
            return reply({"hypothesis": f"Idea {len(self.requests)}", "instructions": f"Attempt {len(self.requests)}."})

    live(monkeypatch, Stuck(), TicketAgent())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, stagnation_limit=20, max_iterations=50, investigator_turns=0))
    db.commit()
    for _ in range(400):
        await advance(db, job)
        db.commit()
        if job.iteration == 2 and job.state == "OPTIMIZING":
            break
    # From here there is room for the held-out pass, and not for another round before it.
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    final_cost, _ = pass_needs(db, suite, job.checkpoint, ("validation",))
    round_cost, _ = pass_needs(db, suite, job.checkpoint, ("development", "selection", "regression"))
    assert 0 < final_cost < round_cost
    job.budget = {**job.budget, "max_cost": job.spent + final_cost + round_cost / 2}
    db.commit()
    spent_before, rounds_before = job.spent, job.iteration
    await run_to_end(db, job)
    assert job.state == "BUDGET_EXHAUSTED" and job.checkpoint["stop_reason"] == "cost_or_elapsed_budget"
    assert job.iteration == rounds_before, "no further round was started"
    card = job.checkpoint["validation_scorecard"]
    assert card["total"] == 8 and set(card["splits"]) == {"validation"}
    assert job.spent - spent_before == pytest.approx(card["cost"])
    assert job.spent <= job.budget["max_cost"]


@pytest.mark.asyncio
async def test_time_spent_paused_or_waiting_is_not_charged_to_the_build(db, seeded):
    _, _, agent, *_ = seeded
    job = new_job(db, agent, Budget(max_seconds=600))
    job.state = "TESTING"
    db.flush()
    control(db, job, "pause")
    assert job.state == "PAUSED" and "idle_since" in job.checkpoint
    # An hour passes while the build is paused.
    job.checkpoint = {**job.checkpoint, "idle_since": (now() - timedelta(hours=1)).isoformat()}
    job.created_at = now() - timedelta(hours=1, seconds=30)
    control(db, job, "resume")
    assert job.state == "TESTING" and "idle_since" not in job.checkpoint
    assert 3590 < job.checkpoint["idle_seconds"] < 3700
    job.state = "DRAFT"
    await advance(db, job)
    assert job.state == "DISCOVERING", "thirty active seconds of a ten-minute limit"
    # The same age with no pause is over the limit.
    job.checkpoint = {**job.checkpoint, "idle_seconds": 0}
    await advance(db, job)
    assert job.state == "BUDGET_EXHAUSTED"
    # Waiting for a person counts as idle too, and accumulates.
    other = SimpleNamespace(
        state="TESTING", checkpoint={"idle_seconds": 5}, org_id=job.org_id, iteration=0, spent=0, id=job.id
    )
    transition(db, other, "WAITING_FOR_APPROVAL")
    other.checkpoint["idle_since"] = (now() - timedelta(seconds=10)).isoformat()
    transition(db, other, "TESTING")
    assert 14 < other.checkpoint["idle_seconds"] < 20


@pytest.mark.asyncio
async def test_a_pass_that_fails_every_trial_the_same_way_is_cut_short(client, seeded, db, monkeypatch):
    created = with_data(client, seeded, development=40, selection=20, validation=8, rows=30)

    class Broken(TicketAgent):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            self.seen.append(1)
            return reply({"category": "not a queue"})

    agent_model = Broken()
    live(monkeypatch, Builder(), agent_model)
    monkeypatch.setattr(settings(), "evaluation_concurrency", 1)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    for _ in range(200):
        if job.state == "ANALYZING":
            break
        await advance(db, job)
        db.commit()
    assert job.state == "ANALYZING"
    assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 20, "sixty cases, stopped at twenty"
    assert db.scalar(
        select(func.count()).select_from(ExecutionEvent).where(ExecutionEvent.kind == "evaluation_stopped_early")
    )


def test_checks_that_reject_known_answers_are_found_without_running_anything():
    answers = [{"category": "card"}, {"category": "loan"}]
    verifiers = [
        Verifier(id="known", kind="one_of", path="category", values=["card", "loan"]),
        Verifier(id="narrow", kind="one_of", path="category", values=["card"]),
        Verifier(id="number", kind="range", path="category", minimum=0),
        Verifier(id="present", kind="required", path="category"),
        # About fields no answer mentions: nothing here can judge them.
        Verifier(id="other_field", kind="required", path="confidence"),
        Verifier(id="schema_ok", kind="schema", path="$", schema={"properties": {"category": {"type": "string"}}}),
        Verifier(
            id="schema_bad",
            kind="schema",
            path="$",
            schema={"properties": {"category": {"enum": ["billing"]}}, "required": ["confidence"]},
        ),
    ]
    assert verifiers_rejecting(verifiers, answers) == ["narrow", "number", "schema_bad"]
    assert verifiers_rejecting(verifiers, []) == []


def test_cached_input_is_priced_at_the_cached_rate(monkeypatch):
    monkeypatch.setattr(settings(), "model_prices", {"big-model": [5.0, 30.0, 0.5], "no-cache-price": [5.0, 30.0]})
    usage = SimpleNamespace(
        input_tokens=2000,
        output_tokens=100,
        total_tokens=2100,
        input_tokens_details=SimpleNamespace(cached_tokens=1500),
    )
    assert usage_cost(usage, "big-model") == pytest.approx(500 * 5e-6 + 1500 * 0.5e-6 + 100 * 30e-6)
    assert usage_cost(usage, "no-cache-price") == pytest.approx(2000 * 5e-6 + 100 * 30e-6)
    # A provider reporting more cached than sent cannot make input negative.
    usage.input_tokens_details.cached_tokens = 9999
    assert usage_cost(usage, "big-model") == pytest.approx(2000 * 0.5e-6 + 100 * 30e-6)


def test_the_builder_cannot_move_an_agent_to_a_model_the_operator_has_not_listed(db, seeded, monkeypatch):
    _, _, agent, initial, *_ = seeded
    spec = AgentSpec.model_validate(initial.spec)
    moved = apply_patch(spec, SpecPatch(hypothesis="Use a bigger model", model="very-expensive-model"))
    assert moved.model == spec.model
    monkeypatch.setattr(settings(), "agent_models", ["approved-model"])
    assert apply_patch(spec, SpecPatch(hypothesis="h", model="approved-model")).model == "approved-model"
    assert apply_patch(spec, SpecPatch(hypothesis="h", model="very-expensive-model")).model == spec.model


def test_failures_are_summarised_as_what_was_expected_against_what_was_answered():
    def failure(expected, actual):
        return {"failed_checks": [{"path": "category", "expected": expected, "actual": actual, "passed": False}]}

    evidence = [failure("card", "loan")] * 3 + [failure("loan", "card")] * 2 + [failure("account", "card")]
    assert confusions(evidence) == [
        {"field": "category", "expected": "card", "answered": "loan", "times": 3},
        {"field": "category", "expected": "loan", "answered": "card", "times": 2},
    ]
    assert confusions([{"failed_checks": [{"category": "verification", "passed": False}]}]) == []


def test_a_gain_on_unseen_cases_counts_in_full_only_if_it_holds_when_run_again():
    def card(rates):
        return {"case_rates": rates, "selection_cases": list(rates)}

    baseline = card({"a": [0, 1], "b": [0, 1], "c": [1, 1], "d": [1, 1]})
    first = card({"a": [1, 1], "b": [1, 1], "c": [1, 1], "d": [0, 1]})
    assert changed_selection_cases(first, baseline) == [("a", 1), ("b", 1), ("d", 1)]
    assert selection_flips(first, baseline) == (2, 1)
    # Run again: one gain repeats, one does not, and the loss was a fluke half the time.
    confirmed = card({"a": [2, 2], "b": [1, 2], "c": [1, 1], "d": [1, 2]})
    assert selection_flips(confirmed, baseline) == (1.5, 0.5)


@pytest.mark.asyncio
async def test_a_version_is_kept_only_after_its_changed_unseen_cases_are_run_a_second_time(
    client, seeded, db, monkeypatch
):
    created = with_data(client, seeded)
    live(monkeypatch, Builder(), TicketAgent())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW"
    confirming = db.scalar(select(ExecutionEvent).where(ExecutionEvent.kind == "promotion_confirming"))
    # The first version answers "card" for everything: nine of twelve unseen cases change when it is fixed.
    assert confirming.payload == {"cases": 9}
    second = [result for result in db.scalars(select(EvaluationResult)) if result.trial == 1]
    cases = {case.id: case for case in db.scalars(select(EvaluationCase))}
    assert len(second) == 9 and {cases[result.case_id].split for result in second} == {"selection"}
    assert job.iteration == 2, "confirming is part of a round, not a round of its own"


def test_similar_examples_are_chosen_per_request_and_a_case_never_sees_its_own_answer():
    examples = [
        Example(input={"text": f"my {topic} problem {topic}{n}"}, output={"category": topic})
        for topic in ("card", "loan", "transfer")
        for n in range(10)
    ]
    spec = SimpleNamespace(examples=examples, examples_shown=4)
    shown = relevant_examples(spec, {"text": "my loan problem loan3"})
    assert len(shown) == 4 and shown[-1].input == {"text": "my loan problem loan3"}, "the nearest is shown last"
    assert {item.output["category"] for item in shown} == {"loan"}
    # In evaluation the request's own row is withheld, or the case would be answered by its answer key.
    held = relevant_examples(spec, {"text": "my loan problem loan3"}, exclude_same=True)
    assert len(held) == 4 and {"text": "my loan problem loan3"} not in [item.input for item in held]
    assert {item.output["category"] for item in held} == {"loan"}
    # A handful of examples are all shown, in the order written.
    few = SimpleNamespace(examples=examples[:3], examples_shown=8)
    assert relevant_examples(few, {"text": "anything"}) == examples[:3]
    assert relevant_examples(SimpleNamespace(examples=examples, examples_shown=0), {"text": "loan"}) == []


def test_the_example_pool_is_the_development_cases_and_nothing_the_builder_may_not_read(client, seeded, db):
    created = with_data(client, seeded)
    agent = db.get(AgentRecord, created["id"])
    latest = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
    )
    spec = AgentSpec.model_validate(latest.spec)
    patched = apply_patch(spec, SpecPatch(hypothesis="Use the examples", example_pool=True, examples_shown=5))
    version = persist_version(db, agent, patched, "Use the examples")
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])))
    development = {case.id for case in cases if case.split == "development"}
    pooled = version.spec["examples"]
    assert len(pooled) == 12 and {item["source_case"] for item in pooled} == development
    unseen = {json.dumps(case.input, sort_keys=True) for case in cases if case.split != "development"}
    assert not unseen & {json.dumps(item["input"], sort_keys=True) for item in pooled}
    assert all(item["output"] == {"category": item["input"]["text"].split()[0]} for item in pooled)
    # Turning the pool off takes the pooled rows out again; the builder's own examples stay.
    own = Example(input={"text": "an invented illustration"}, output={"category": "card"})
    both = persist_version(
        db, agent, apply_patch(AgentSpec.model_validate(version.spec), SpecPatch(hypothesis="h", examples=[own])), "h"
    )
    assert len(both.spec["examples"]) == 13
    off = apply_patch(AgentSpec.model_validate(both.spec), SpecPatch(hypothesis="h", example_pool=False))
    assert [item.input for item in off.examples] == [own.input]


class ExampleFollower(Model):
    """A deployed agent that copies the answer of the last example it is shown, and otherwise guesses."""

    async def get_response(self, system_instructions, input, *args, **kwargs):
        outputs = [line for line in system_instructions.splitlines() if line.strip().startswith("Output:")]
        answer = json.loads(outputs[-1].split("Output:", 1)[1])["category"] if outputs else "card"
        return reply({"category": answer})

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
async def test_a_builder_that_turns_on_the_example_pool_improves_cases_it_never_read(client, seeded, db, monkeypatch):
    # Each message shares its topic word with others of its queue and nothing else with anyone.
    rows = [{"text": f"my {topic} problem {topic}{n}", "category": topic} for n in range(30) for topic in TOPICS]
    created = with_data(client, seeded, development=40, selection=12, validation=8, content=as_csv(rows))

    class Pooler(Builder):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            payload = json.loads(user_text(input))
            if "baseline" in payload:
                return await super().get_response(system_instructions, input, *args, **kwargs)
            self.requests.append({"role": "optimizer", "payload": payload, "tools": []})
            return reply({"hypothesis": "Show similar worked examples", "example_pool": True, "examples_shown": 3})

    builder = Pooler()
    live(monkeypatch, builder, ExampleFollower())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW", (job.state, job.checkpoint.get("stop_reason"))
    best = db.get(AgentVersion, agent.best_version_id)
    assert best.spec["example_pool"] and len(best.spec["examples"]) == 40
    assert job.checkpoint["validation_scorecard"]["score"] == 1
    # The builder is told the pattern of its failures, and is not sent the pool it already has as cases.
    optimizer = builder.requests[-1]["payload"]
    assert optimizer["confusions"] and {"field", "expected", "answered", "times"} == set(optimizer["confusions"][0])
    assert optimizer["allowed_models"] == [best.spec["model"]]


@pytest.mark.asyncio
async def test_a_build_whose_best_version_scores_under_the_target_ends_below_target_not_failed(db, seeded):
    _, _, agent, version, suite, _ = seeded
    job = new_job(db, agent, Budget(target_score=0.95))
    from factory.models import EvaluationRun

    evaluation = EvaluationRun(org_id=job.org_id, version_id=version.id, suite_id=suite.id, status="completed")
    evaluation.scorecard = {
        "score": 0.8,
        "distinct_cases": 10,
        "critical_failures": 0,
        "mean_latency_ms": 1,
        "cost": 0,
        "metrics": {"safety": 1, "approval_compliance": 1},
    }
    db.add(evaluation)
    db.flush()
    job.state = "ANALYZING"
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id, "validation": True}
    await advance(db, job)
    assert job.state == "BELOW_TARGET" and job.error is None
    assert job.checkpoint["stop_reason"] == "held_out_score_below_target"
    assert "BELOW_TARGET" in TERMINAL


def test_removing_a_dataset_takes_its_cases_and_their_results_and_needs_an_administrator(
    client, seeded, db, monkeypatch
):
    org, *_ = seeded
    created = with_data(client, seeded)
    dataset = db.scalar(select(Dataset).where(Dataset.agent_id == created["id"]))
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id)))
    assert len(cases) == 32
    version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == created["id"]))
    evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=created["suite_id"])
    run = ExecutionRun(org_id=org.id, version_id=version.id, mode="live", input={})
    db.add_all([evaluation, run])
    db.flush()
    db.add(
        EvaluationResult(
            org_id=org.id,
            evaluation_run_id=evaluation.id,
            case_id=cases[0].id,
            execution_id=run.id,
            trial=0,
            passed=True,
            checks=[],
            failures=[],
        )
    )
    editor = User(email="editor@example.invalid", password_hash=passwords.hash("test-password"))
    other = Organization(name="Other tenant")
    outsider = User(email="outsider@example.invalid", password_hash=passwords.hash("test-password"))
    db.add_all([editor, other, outsider])
    db.flush()
    db.add_all(
        [
            Membership(org_id=org.id, user_id=editor.id, role="editor"),
            Membership(org_id=other.id, user_id=outsider.id, role="admin"),
        ]
    )
    db.commit()
    path = f"/datasets/{dataset.id}"
    assert client.delete(path, headers={"Authorization": "Bearer " + token_for(editor.id, org.id)}).status_code == 403
    assert (
        client.delete(path, headers={"Authorization": "Bearer " + token_for(outsider.id, other.id)}).status_code == 404
    )
    monkeypatch.setattr(settings(), "execution_mode", "live")
    build = client.post(f"/agents/{created['id']}/builds", json={}).json()
    assert client.delete(path).status_code == 409
    client.post(f"/builds/{build['id']}/cancel", json={})
    removed = client.delete(path)
    assert removed.status_code == 200 and removed.json() == {"cases": 32, "results": 1}
    assert (
        db.scalar(
            select(func.count()).select_from(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])
        )
        == 0
    )
    assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 0
    detail = client.get(f"/agents/{created['id']}").json()
    assert detail["truth_source"] is None and client.get(f"/agents/{created['id']}/datasets").json()["total"] == 0
    assert client.post(f"/agents/{created['id']}/builds", json={}).status_code == 422


def test_the_acceptable_score_is_set_by_the_owner_at_creation(client, seeded):
    created = direct_agent(client, seeded, minimum_score=0.8)
    assert created["version"]["spec"]["quality_policy"]["minimum_score"] == 0.8
    assert direct_agent(client, seeded)["version"]["spec"]["quality_policy"]["minimum_score"] == 0.95
    body = {"project_id": created["project_id"], "request": "x" * 20, "minimum_score": 1.5}
    assert client.post("/agents", json=body).status_code == 422


def test_hybrid_mode_runs_templates_on_fixtures_and_custom_agents_on_the_model(client, seeded, monkeypatch):
    assert (mode_for("orders"), mode_for("custom")) == ("demo", "demo")
    monkeypatch.setattr(settings(), "execution_mode", "live")
    assert (mode_for("orders"), mode_for("custom")) == ("live", "live")
    monkeypatch.setattr(settings(), "execution_mode", "hybrid")
    assert (mode_for("orders"), mode_for("quotes"), mode_for("hiring"), mode_for("custom")) == ("demo",) * 3 + ("live",)
    # A custom agent without tools can be built here; in plain demo mode it is refused.
    created = with_data(client, seeded)
    assert client.post(f"/agents/{created['id']}/builds", json={}).status_code == 201
    from factory.config import Settings

    with pytest.raises(ValueError):
        Settings(execution_mode="sometimes").validate_provider()


@pytest.mark.asyncio
async def test_a_tool_less_agent_is_deployed_invoked_and_answers(client, seeded, db, monkeypatch):
    created = with_data(client, seeded)
    live(monkeypatch, Builder(), TicketAgent())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW"
    assert client.post(f"/versions/{agent.best_version_id}/approve").status_code == 200
    deployed = client.post(f"/agents/{agent.id}/deployments", json={"version_id": agent.best_version_id})
    assert deployed.status_code == 201, deployed.text
    queued = client.post(
        f"/deployments/{deployed.json()['id']}/invoke",
        json={"input": {"text": "transfer has not arrived"}, "idempotency_key": "tool-less-1"},
    )
    assert queued.status_code in (200, 201, 202), queued.text
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    for _ in range(5):
        if not await invocation_tick(sessions):
            break
    db.expire_all()
    run = db.get(ExecutionRun, queued.json()["id"])
    # An answer, with nothing to approve: this agent has no way to write anywhere.
    assert run.status == "completed" and run.output == {"category": "transfer"} and run.mode == "live"
    assert run.metrics["tools_offered"] == 0 and not run.metrics["approval_ids"]
    # A request outside the agent's input shape is refused before any model call.
    bad = client.post(
        f"/deployments/{deployed.json()['id']}/invoke",
        json={"input": {"message": "x"}, "idempotency_key": "tool-less-2"},
    )
    assert bad.status_code == 422


def test_a_request_may_take_minutes_by_default():
    assert AgentSpec(name="n", purpose="p", template="custom", instructions="i").timeout_seconds == 180
    assert Budget().max_cost == 25 and Budget().max_seconds == 14400


@pytest.mark.asyncio
async def test_rubric_graded_cases_run_side_by_side_without_holding_each_other_up(client, seeded, db, monkeypatch):
    created = with_data(client, seeded, development=8, selection=0, validation=8)
    criterion = "Names a queue"
    for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])):
        case.rubric = {"criteria": [criterion], "threshold": 0.8}
    db.commit()

    class Grader(Model):
        active = peak = 0

        async def get_response(self, system_instructions, input, *args, **kwargs):
            Grader.active += 1
            Grader.peak = max(Grader.peak, Grader.active)
            try:
                await asyncio.sleep(0.01)
                return reply({"criteria": [{"criterion": criterion, "score": 1, "evidence": "It names one."}]})
            finally:
                Grader.active -= 1

        async def stream_response(self, *args, **kwargs):
            raise NotImplementedError
            yield

    live(monkeypatch, Builder(), Slow())
    monkeypatch.setattr("factory.qualitative.Agent", lambda **kwargs: Agent(**{**kwargs, "model": Grader()}))
    monkeypatch.setattr(settings(), "evaluation_concurrency", 4)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint.get("waiting_reason"))
    assert Grader.peak == 4
    results = list(db.scalars(select(EvaluationResult)))
    assert len(results) == 16 and all(result.passed for result in results)
    assert all("qualitative" in {check["category"] for check in result.checks} for result in results)
    recorded = db.scalar(select(func.sum(UsageRecord.cost)).where(UsageRecord.job_id == job.id))
    assert job.spent == pytest.approx(recorded)


@pytest.mark.asyncio
async def test_the_build_reports_spend_by_role_and_how_often_the_held_back_rows_were_scored(
    client, seeded, db, monkeypatch
):
    created = with_data(client, seeded)
    assert client.get(f"/agents/{created['id']}").json()["held_out_uses"] == 0
    live(monkeypatch, Builder(), TicketAgent())
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    await run_to_end(db, job)
    detail = client.get(f"/builds/{job.id}").json()
    roles = detail["usage_by_role"]
    assert set(roles) == {"requirements_architect", "optimizer", "evaluation_agent"}
    assert roles["requirements_architect"]["calls"] == 1 and roles["optimizer"]["calls"] == 1
    # Twelve read and twelve unseen rows twice, nine changed rows again, and eight held back.
    assert roles["evaluation_agent"]["calls"] == 24 + 24 + 9 + 8
    assert all(
        row["input_tokens"] == 5 * row["calls"] and row["output_tokens"] == 5 * row["calls"] for row in roles.values()
    )
    assert sum(row["cost"] for row in roles.values()) == pytest.approx(detail["spent"])
    assert client.get(f"/agents/{created['id']}").json()["held_out_uses"] == 1
