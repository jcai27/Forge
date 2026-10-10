"""Search-loop correctness: parent selection, optimizer memory and noise-aware promotion."""

import pytest
from sqlalchemy import select

from factory.evaluation import can_promote
from factory.models import AgentVersion, BuildIteration
from factory.schemas import Budget
from factory.workflow import TERMINAL, advance, new_job


async def run_until(db, job, predicate, limit=400):
    for _ in range(limit):
        await advance(db, job)
        db.commit()
        if predicate() or job.state in TERMINAL:
            return
    raise AssertionError(f"loop did not reach condition: {job.state} {job.checkpoint}")


@pytest.mark.asyncio
async def test_rejected_candidate_is_never_the_next_parent(db, seeded, monkeypatch):
    _, _, agent, _, _, _ = seeded
    seen = []

    async def scripted(spec, development_failures, **kwargs):
        seen.append({"spec": spec.model_copy(deep=True), "failures": development_failures, **kwargs})
        candidate = spec.model_copy(deep=True)
        if len(seen) == 1:
            candidate.rules["check_inventory"] = False  # critical stock regression: must be rejected
            return candidate, "Bypass stock check"
        candidate.rules["resolve_aliases"] = True
        return candidate, "Resolve aliases"

    monkeypatch.setattr("factory.workflow.optimize", scripted)
    job = new_job(db, agent, Budget(max_iterations=6))
    await run_until(db, job, lambda: len(seen) >= 2)
    assert len(seen) >= 2
    iterations = list(
        db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number))
    )
    assert iterations[0].promoted and not iterations[1].promoted
    best_spec = db.get(AgentVersion, iterations[0].version_id).spec
    # The second optimizer call must start from the best version, not the rejected candidate.
    assert seen[1]["spec"].rules["check_inventory"] is True
    assert seen[1]["spec"].rules == best_spec["rules"]
    assert seen[1]["spec"].instructions == best_spec["instructions"]
    # And it is shown the failures of that best version.
    assert job.checkpoint["best_version_id"] == iterations[0].version_id


@pytest.mark.asyncio
async def test_optimizer_receives_history_and_only_development_evidence(db, seeded, monkeypatch):
    from factory.models import EvaluationCase

    _, _, agent, _, suite, _ = seeded
    seen = []

    async def scripted(spec, development_failures, **kwargs):
        seen.append({"failures": development_failures, **kwargs})
        candidate = spec.model_copy(deep=True)
        if len(seen) == 1:
            candidate.rules["check_inventory"] = False
            return candidate, "Bypass stock check"
        candidate.rules["resolve_aliases"] = True
        return candidate, "Resolve aliases"

    monkeypatch.setattr("factory.workflow.optimize", scripted)
    job = new_job(db, agent, Budget(max_iterations=6))
    await run_until(db, job, lambda: len(seen) >= 2)
    assert len(seen) >= 2
    history = seen[1]["history"]
    assert [entry["promoted"] for entry in history] == [True, False]
    assert history[1]["hypothesis"] == "Bypass stock check"
    assert history[1]["critical_failures"] > 0
    # Evidence and passing examples may name development cases only.
    cases = {c.name: c.split for c in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == suite.id))}
    for call in seen:
        for failure in call["failures"]:
            assert cases[failure["case"]] == "development"
            assert "tool_sequence" in failure
        for example in call["passing"]:
            assert cases[example["case"]] == "development"
    assert seen[1]["passing"], "passing development behaviour should be shown for contrast"
    # Nothing outside the development split is serialised into the notebook either.
    for entry in history:
        assert all(cases[name] == "development" for name in entry["development_failures"])


@pytest.mark.asyncio
async def test_evidence_includes_tool_sequence(db, seeded):
    from factory.evaluation import development_evidence, evaluate_suite

    _, _, _, initial, suite, _ = seeded
    run = await evaluate_suite(db, initial, suite, ("development", "regression"))
    evidence = development_evidence(db, run)
    assert evidence
    assert all(item["tool_sequence"] for item in evidence)


def card(rates, score=None):
    total = sum(t for _, t in rates.values())
    passed = sum(p for p, _ in rates.values())
    return {
        "score": passed / total if score is None else score,
        "total": total,
        "passed": passed,
        "critical_failures": 0,
        "metrics": {"safety": 1, "approval_compliance": 1},
        "mean_latency_ms": 1,
        "cost": 0,
        "splits": {},
        "regression_outcomes": {},
        "case_rates": rates,
    }


def test_noise_guard_rejects_an_improvement_inside_trial_variability():
    baseline = card({"a": [1, 3], "b": [2, 3]})
    candidate = card({"a": [2, 3], "b": [2, 3]})
    assert candidate["score"] > baseline["score"]
    assert not can_promote(candidate, baseline)


def test_noise_guard_accepts_clear_or_unmeasurable_variance():
    # Consistent trials show no noise, so a higher score is accepted.
    assert can_promote(card({"a": [3, 3], "b": [3, 3]}), card({"a": [0, 3], "b": [3, 3]}))
    # Single trials carry no variance estimate; behaviour matches the original strict comparison.
    assert can_promote(card({"a": [1, 1], "b": [1, 1]}), card({"a": [0, 1], "b": [1, 1]}))
    assert not can_promote(card({"a": [1, 1], "b": [1, 1]}), card({"a": [1, 1], "b": [1, 1]}))
    # A large paired improvement outweighs the trial noise.
    assert can_promote(card({"a": [3, 3], "b": [3, 3], "c": [3, 3]}), card({"a": [1, 3], "b": [0, 3], "c": [1, 3]}))


def test_arithmetic_check_only_applies_to_line_item_outputs():
    from types import SimpleNamespace

    from factory.evaluation import grade

    case = SimpleNamespace(assertions=[], input={})
    metrics = {"tool_calls": 1, "safety_violations": 0, "state_changes": 0}
    custom = SimpleNamespace(output={"answer": "ok"}, status="completed", metrics=metrics, error=None)
    checks, failures = grade(custom, case)
    assert "business_rule_compliance" not in {c["category"] for c in checks}
    assert failures == []
    wrong = SimpleNamespace(
        output={"lines": [{"quantity": 2, "unit_price_cents": 100, "line_total_cents": 999}], "total_cents": 999},
        status="completed",
        metrics=metrics,
        error=None,
    )
    checks, failures = grade(wrong, case)
    assert "business_rule_compliance" in failures


def test_graded_score_gives_partial_credit_but_zero_on_safety_violation():
    from factory.evaluation import graded_score

    ok = {"passed": True}
    checks = [
        {"category": "structured_accuracy", **ok},
        {"category": "structured_accuracy", "passed": False},
        {"category": "business_rule_compliance", **ok},
        {"category": "task_completion", **ok},
        {"category": "safety", **ok},
    ]
    assert graded_score(checks) == pytest.approx(2 / 3)
    assert graded_score([*checks[:-1], {"category": "safety", "passed": False}]) == 0
    # Only generic checks: all-pass is full credit, any fail is zero.
    assert graded_score([{"category": "task_completion", **ok}]) == 1
    assert graded_score([{"category": "task_completion", "passed": False}]) == 0


@pytest.mark.asyncio
async def test_scorecard_reports_graded_score_between_zero_and_pass_rate_bounds(db, seeded):
    from factory.evaluation import evaluate_suite

    _, _, _, initial, suite, _ = seeded
    run = await evaluate_suite(db, initial, suite, ("development", "regression"))
    card_ = run.scorecard
    assert 0 <= card_["score"] <= card_["graded_score"] <= 1
    assert all("graded_score" in split for split in card_["splits"].values())
