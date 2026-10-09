import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from factory.builder import persist_version
from factory.evaluation import can_promote, development_evidence, evaluate_suite
from factory.models import AgentVersion, BuildIteration, BuildJob
from factory.schemas import AgentSpec, Budget
from factory.workflow import TERMINAL, advance, new_job, worker_tick


@pytest.mark.asyncio
async def test_complete_improvement_loop(db, seeded):
    _, _, agent, version, suite, _ = seeded
    job = new_job(db, agent, Budget())
    for _ in range(300):
        await advance(db, job)
        db.commit()
        if job.state in TERMINAL:
            break
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint)
    iterations = list(
        db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number))
    )
    assert len(iterations) == 3
    assert iterations[0].scorecard["score"] < iterations[-1].scorecard["score"]
    assert iterations[-1].scorecard["score"] == 1
    assert all(it.promoted for it in iterations)
    assert agent.best_version_id == iterations[-1].version_id
    assert len(list(db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id)))) == 3
    assert job.checkpoint["validation_scorecard"]["total"] == 8
    assert job.checkpoint["diagnosis"]["hidden_validation_shared_with_optimizer"] is False


@pytest.mark.asyncio
async def test_regression_prevents_promotion(db, seeded):
    _, _, agent, initial, suite, _ = seeded
    spec = AgentSpec.model_validate(initial.spec)
    spec.rules.update(resolve_aliases=True, fuzzy_match=True)
    best = persist_version(db, agent, spec)
    baseline = await evaluate_suite(db, best, suite, ("development", "regression"))
    spec.rules["check_inventory"] = False
    broken = persist_version(db, agent, spec, "Overly aggressive stock bypass")
    candidate = await evaluate_suite(db, broken, suite, ("development", "regression"))
    assert candidate.scorecard["critical_failures"] > 0
    assert not can_promote(candidate.scorecard, baseline.scorecard)
    evidence = development_evidence(db, candidate)
    assert not any("stock" in e["case"].lower() for e in evidence)


@pytest.mark.asyncio
async def test_higher_score_candidate_with_development_fixes_and_critical_regression_is_rejected(db, seeded):
    _, _, agent, initial, suite, _ = seeded
    baseline = await evaluate_suite(db, initial, suite, ("development", "regression"))
    spec = AgentSpec.model_validate(initial.spec)
    spec.rules.update(resolve_aliases=True, fuzzy_match=True, check_inventory=False)
    changed = persist_version(db, agent, spec, "Fix aliases and typos but bypass stock checks")
    candidate = await evaluate_suite(db, changed, suite, ("development", "regression"))
    assert candidate.scorecard["splits"]["development"]["score"] > baseline.scorecard["splits"]["development"]["score"]
    assert candidate.scorecard["score"] > baseline.scorecard["score"]
    assert candidate.scorecard["critical_failures"] > 0
    assert candidate.scorecard["splits"]["regression"]["score"] < baseline.scorecard["splits"]["regression"]["score"]
    assert not can_promote(candidate.scorecard, baseline.scorecard)


@pytest.mark.asyncio
async def test_restart_recovers_and_does_not_duplicate_results(db, seeded):
    _, _, agent, _, _, _ = seeded
    job = new_job(db, agent, Budget())
    db.commit()
    factory = sessionmaker(db.get_bind(), expire_on_commit=False)
    for _ in range(8):
        await worker_tick(factory)
    db.expire_all()
    before = db.get(BuildJob, job.id).checkpoint.copy()
    # A fresh sessionmaker represents a new worker process over the same persistent database.
    recovered = sessionmaker(db.get_bind(), expire_on_commit=False)
    for _ in range(300):
        await worker_tick(recovered)
        db.expire_all()
        if db.get(BuildJob, job.id).state in TERMINAL:
            break
    assert db.get(BuildJob, job.id).state == "READY_FOR_REVIEW"
    assert before["evaluation_id"]
    numbers = [row.number for row in db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id))]
    assert numbers == [1, 2, 3]
