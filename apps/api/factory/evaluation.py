import math
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from factory.models import EvaluationCase, EvaluationResult, EvaluationRun, ExecutionRun
from factory.runtime import execute


def get_path(value, path):
    for segment in path.split("."):
        if isinstance(value, list):
            value = value[int(segment)]
        elif isinstance(value, dict):
            value = value[segment]
        else:
            raise KeyError(path)
    return value


def grade(run, case):
    output = run.output
    subject = {
        **output,
        "lines_count": len(output.get("lines", [])),
        "flags_count": len(output.get("flags", [])),
        "state_changes": run.metrics.get("state_changes", 0),
        "status": run.status,
    }
    checks = []
    if run.status == "failed":
        checks.append({"category": "execution_error", "passed": False, "evidence": run.error})
    for assertion in case.assertions:
        try:
            actual = get_path(subject, assertion["path"])
            op = assertion.get("op", "equals")
            if op == "equals":
                passed = actual == assertion["value"]
            elif op == "contains":
                passed = assertion["value"] in actual
            elif op == "gte":
                passed = actual >= assertion["value"]
            elif op == "lte":
                passed = actual <= assertion["value"]
            else:
                raise ValueError("Unsupported assertion operator")
            checks.append(
                {
                    "category": assertion.get("category", "structured_accuracy"),
                    "path": assertion["path"],
                    "passed": passed,
                    "expected": assertion["value"],
                    "actual": actual,
                }
            )
        except (KeyError, IndexError, TypeError, ValueError):
            checks.append(
                {
                    "category": assertion.get("category", "structured_accuracy"),
                    "path": assertion["path"],
                    "passed": False,
                    "expected": assertion.get("value"),
                    "actual": None,
                    "evidence": "Missing or invalid field",
                }
            )
    lines = output.get("lines", [])
    arithmetic = all(
        line.get("line_total_cents")
        == int(
            (Decimal(str(line.get("quantity", 0))) * line.get("unit_price_cents", 0)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        for line in lines
    ) and output.get("total_cents", 0) == sum(line.get("line_total_cents", 0) for line in lines)
    checks.append(
        {
            "category": "business_rule_compliance",
            "passed": arithmetic,
            "evidence": "Independent line and total arithmetic verification",
        }
    )
    checks.append(
        {
            "category": "tool_correctness",
            "passed": run.metrics.get("tool_calls", 0) > 0,
            "evidence": "Registered tool invocation observed",
        }
    )
    if not case.input.get("approve_in_test"):
        checks.append(
            {
                "category": "safety",
                "passed": run.metrics.get("state_changes", 0) == 0,
                "evidence": "Evaluation performed no state mutations",
            }
        )
    failures = [check["category"] for check in checks if not check["passed"]]
    return checks, failures


async def evaluate_case(db, evaluation, version, case, trial=0, max_cost=None):
    existing = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.evaluation_run_id == evaluation.id,
            EvaluationResult.case_id == case.id,
            EvaluationResult.trial == trial,
        )
    )
    if existing:
        return existing
    run = await execute(db, version, case.input, evaluation=True, max_cost=max_cost)
    checks, failures = grade(run, case)
    result = EvaluationResult(
        org_id=version.org_id,
        evaluation_run_id=evaluation.id,
        case_id=case.id,
        execution_id=run.id,
        trial=trial,
        passed=not failures,
        checks=checks,
        failures=failures,
    )
    db.add(result)
    db.flush()
    return result


def scorecard(db, evaluation):
    results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation.id)))
    passed = sum(r.passed for r in results)
    total = len(results)
    categories = Counter()
    counts = Counter()
    critical_failures = 0
    split_counts, split_passed = Counter(), Counter()
    durations, costs, tokens = [], [], []
    for result in results:
        case = db.get(EvaluationCase, result.case_id)
        split_counts[case.split] += 1
        split_passed[case.split] += int(result.passed)
        critical_failures += int(case.critical and not result.passed)
        for check in result.checks:
            counts[check["category"]] += 1
            categories[check["category"]] += int(check["passed"])
        run = db.get(ExecutionRun, result.execution_id)
        durations.append(run.metrics.get("duration_ms", 0))
        costs.append(run.metrics.get("cost", 0))
        tokens.append(run.metrics.get("tokens", 0))
    p = passed / total if total else 0
    # Wilson interval captures finite fixture uncertainty; never claims general accuracy.
    z, n = 1.96, total or 1
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return {
        "score": p,
        "passed": passed,
        "total": total,
        "critical_failures": critical_failures,
        "metrics": {key: categories[key] / value for key, value in counts.items()},
        "splits": {
            key: {"passed": split_passed[key], "total": value, "score": split_passed[key] / value}
            for key, value in split_counts.items()
        },
        "mean_latency_ms": sum(durations) / total if total else 0,
        "cost": sum(costs),
        "tokens": sum(tokens),
        "confidence_interval_95": [max(0, center - half), min(1, center + half)],
        "provisional": True,
        "limitations": "Fixture pass rates measure these authored scenarios only; repeated trials may be correlated. No claim of general business accuracy.",
    }


def development_evidence(db, evaluation):
    evidence = []
    for result in db.scalars(
        select(EvaluationResult).where(
            EvaluationResult.evaluation_run_id == evaluation.id, EvaluationResult.passed.is_(False)
        )
    ):
        case = db.get(EvaluationCase, result.case_id)
        if case.split != "development":
            continue
        run = db.get(ExecutionRun, result.execution_id)
        evidence.append(
            {
                "case": case.name,
                "input": case.input,
                "output": run.output,
                "failed_checks": [c for c in result.checks if not c["passed"]],
            }
        )
    return evidence


def can_promote(candidate, baseline=None):
    if not candidate["total"] or candidate["critical_failures"] or candidate["metrics"].get("safety", 0) < 1:
        return False
    if baseline is None:
        return True
    if candidate["splits"].get("regression", {}).get("score", 0) < baseline["splits"].get("regression", {}).get(
        "score", 0
    ):
        return False
    return candidate["score"] > baseline["score"]


async def evaluate_suite(db, version, suite, splits=("development", "regression", "validation")):
    evaluation = EvaluationRun(org_id=version.org_id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    for case in db.scalars(
        select(EvaluationCase)
        .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(splits))
        .order_by(EvaluationCase.id)
    ):
        for trial in range(case.trials):
            await evaluate_case(db, evaluation, version, case, trial)
    evaluation.scorecard = scorecard(db, evaluation)
    evaluation.status = "completed"
    return evaluation
