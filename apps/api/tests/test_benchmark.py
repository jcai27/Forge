"""The search benchmark must stay runnable and must not overstate what it measures."""

import pytest

from benchmarks.search import LIVE_ARMS, POOL, SIMULATED_ARMS, live, run_build, simulated, simulated_proposer, table


@pytest.mark.asyncio
async def test_simulated_benchmark_runs_real_builds_and_reports_every_arm():
    report = await simulated(2)
    assert [row["arm"] for row in report] == list(SIMULATED_ARMS)
    for row in report:
        assert row["builds"] == 2 and 0 <= row["success_rate"] <= 1
        assert row["mean_trials"] > 0 and row["mean_full_evaluations"] >= 1
        # Demo execution has no model, so no cost may be invented.
        assert row["mean_cost"] == 0
    rendered = table(report)
    assert "Reached target" in rendered and all(name in rendered for name in SIMULATED_ARMS)


@pytest.mark.asyncio
async def test_memory_arm_never_repeats_an_idea_and_screening_uses_screen_runs():
    log = []
    single = await run_build({"candidates_per_round": 1}, simulated_proposer(7, True, log))
    assert single["succeeded"] and single["screen_runs"] == 0
    assert len(log) == len(set(log)) <= len(POOL), log
    assert single["held_out_score"] == 1
    screened = await run_build({"candidates_per_round": 3}, simulated_proposer(7, True, []))
    assert screened["succeeded"] and screened["screen_runs"] >= 2
    assert screened["full_evaluations"] <= single["full_evaluations"]


@pytest.mark.asyncio
async def test_live_benchmark_refuses_to_run_without_a_real_provider():
    with pytest.raises(SystemExit) as stopped:
        await live(1, 1.0)
    assert "needs a real provider" in str(stopped.value)
    assert set(LIVE_ARMS) == {"one-shot optimizer", "harness (investigate, 3 screened)"}
