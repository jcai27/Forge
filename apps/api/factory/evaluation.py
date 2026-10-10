import json
import math
import time
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from statistics import pstdev

from jsonschema import validate
from jsonschema.exceptions import ValidationError
from sqlalchemy import select

from factory.connectors import check_connection
from factory.fixtures import business_snapshot
from factory.models import DataSource, EvaluationCase, EvaluationResult, EvaluationRun, ExecutionRun, Membership
from factory.runtime import execute
from factory.schemas import QualityPolicy
from factory.security import redact, redact_tenant


def get_path(value, path):
    if path in ("$", ""):
        return value
    for segment in path.split("."):
        if isinstance(value, list):
            value = value[int(segment)]
        elif isinstance(value, dict):
            value = value[segment]
        else:
            raise KeyError(path)
    return value


def grade(run, case, observation=None):
    output = run.output
    subject = {
        **output,
        "lines_count": len(output.get("lines", [])),
        "flags_count": len(output.get("flags", [])),
        "state_changes": run.metrics.get("state_changes", 0),
        "status": run.status,
        "tool_sequence": run.metrics.get("tool_sequence", []),
    }
    checks = []
    if run.status == "failed":
        checks.append({"category": "execution_error", "passed": False, "evidence": run.error})
    for assertion in case.assertions:
        try:
            scope = assertion.get("scope", "output")
            source = (
                (observation or {}).get("state", {})
                if scope == "state"
                else run.metrics
                if scope == "metrics"
                else run.output
                if assertion.get("path", "$") == "$"
                else subject
            )
            actual = get_path(source, assertion.get("path", "$"))
            op = assertion.get("op", "equals")
            if op == "equals":
                passed = actual == assertion["value"]
            elif op == "contains":
                passed = assertion["value"] in actual
            elif op == "gte":
                passed = actual >= assertion["value"]
            elif op == "lte":
                passed = actual <= assertion["value"]
            elif op == "contains_record":
                passed = isinstance(actual, list) and any(
                    isinstance(row, dict) and all(row.get(key) == value for key, value in assertion["value"].items())
                    for row in actual
                )
            elif op == "json_schema":
                try:
                    validate(actual, assertion["schema"])
                    passed = True
                except ValidationError:
                    passed = False
            else:
                raise ValueError("Unsupported assertion operator")
            checks.append(
                {
                    "category": assertion.get("category", "structured_accuracy"),
                    "path": assertion.get("path", "$"),
                    "scope": scope,
                    "passed": passed,
                    "expected": redact(assertion.get("value", assertion.get("schema"))),
                    "actual": (
                        {"valid_schema": passed}
                        if op == "json_schema"
                        else {"matching_record": passed}
                        if scope == "state" and isinstance(actual, (list, dict))
                        else redact(actual)
                    ),
                }
            )
        except (KeyError, IndexError, TypeError, ValueError):
            checks.append(
                {
                    "category": assertion.get("category", "structured_accuracy"),
                    "path": assertion.get("path", "$"),
                    "passed": False,
                    "expected": assertion.get("value"),
                    "actual": None,
                    "evidence": "Missing or invalid field",
                }
            )
    lines = output.get("lines", [])
    try:
        arithmetic = all(
            line.get("line_total_cents")
            == int(
                (Decimal(str(line.get("quantity", 0))) * line.get("unit_price_cents", 0)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            for line in lines
        ) and output.get("total_cents", 0) == sum(line.get("line_total_cents", 0) for line in lines)
    except (InvalidOperation, TypeError, ValueError, AttributeError, OverflowError):
        arithmetic = False
    checks.append(
        {
            "category": "business_rule_compliance",
            "passed": arithmetic,
            "evidence": "Independent line and total arithmetic verification",
        }
    )
    checks.append(
        {
            "category": "task_completion",
            "passed": run.status not in ("failed", "running", "queued"),
            "evidence": "Execution reached a terminal result or approval checkpoint",
        }
    )
    checks.append(
        {
            "category": "approval_compliance",
            "passed": not run.metrics.get("approval_ids"),
            "evidence": "Evaluation created no production approval or external dispatch",
        }
    )
    checks.append(
        {
            "category": "tool_correctness",
            "passed": run.metrics.get("tool_calls", 0) > 0,
            "evidence": "Registered tool invocation observed",
        }
    )
    checks.append(
        {
            "category": "safety",
            "passed": run.metrics.get("safety_violations", 0) == 0
            and (case.input.get("approve_in_test") or run.metrics.get("state_changes", 0) == 0),
            "evidence": "No permission violations or unauthorized state mutations; approved test writes affect only the isolated fork",
        }
    )
    failures = [check["category"] for check in checks if not check["passed"]]
    return checks, failures


def evaluation_environment(db, case, version):
    """Resolve only server-authorized environments; each case receives a fresh fork."""
    environment = {**case.environment, "source": case.source, "authorized_by": case.authorized_by}
    state = business_snapshot(db, version.org_id)
    for collection, records in environment.get("state_overrides", {}).items():
        if collection not in state:
            raise ValueError("Unknown test-state collection")
        state[collection] = redact_tenant(db, version.org_id, records)
    if environment.get("data_mappings"):
        member = db.scalar(
            select(Membership).where(Membership.org_id == version.org_id, Membership.user_id == case.authorized_by)
        )
        if not member or member.role != "admin":
            raise PermissionError("Imported evaluation authorization revoked")
        for mapping in environment["data_mappings"]:
            source = db.get(DataSource, mapping["source_id"])
            if (
                not source
                or source.org_id != version.org_id
                or not source.model_visible
                or source.connection_id not in version.spec["connection_ids"]
            ):
                raise PermissionError("Imported evaluation data is unavailable or not explicitly model-authorized")
            check_connection(db, version.org_id, source.connection_id)
            collection = mapping["collection"]
            if collection not in state:
                raise ValueError("Unknown imported-state collection")
            # Select only explicitly mapped fields; unrelated private columns never enter the fork.
            mapped = []
            for record in redact_tenant(db, version.org_id, source.records):
                row = {destination: record[column] for destination, column in mapping["fields"].items()}
                exemplar = state[collection][0] if state[collection] else {}
                for field, value in row.items():
                    expected = exemplar.get(field)
                    if isinstance(value, str):
                        if isinstance(expected, int) and not isinstance(expected, bool):
                            row[field] = int(value)
                        elif isinstance(expected, float):
                            row[field] = float(value)
                        elif isinstance(expected, (list, dict)):
                            row[field] = json.loads(value)
                mapped.append(row)
            state[collection] = mapped
    if case.source == "live_read_only":
        member = db.scalar(
            select(Membership).where(Membership.org_id == version.org_id, Membership.user_id == case.authorized_by)
        )
        if not member or member.role != "admin":
            raise PermissionError("Live evaluation authorization revoked")
        approved = environment.get("live_connection_ids", [])
        if not approved or not set(approved).issubset(version.spec["connection_ids"]):
            raise PermissionError("Live evaluation connection was not authorized for this version")
        for connection_id in approved:
            check_connection(db, version.org_id, connection_id)
        if case.input.get("approve_in_test"):
            raise PermissionError("Live read-only evaluations cannot request writes")
    elif environment.get("live_connection_ids"):
        raise PermissionError("Synthetic and replay evaluations cannot authorize live reads")
    return state, environment


async def evaluate_case(db, evaluation, version, case, trial=0, max_cost=None, max_seconds=None):
    existing = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.evaluation_run_id == evaluation.id,
            EvaluationResult.case_id == case.id,
            EvaluationResult.trial == trial,
        )
    )
    if existing:
        return existing
    if case.org_id != version.org_id or evaluation.org_id != version.org_id or case.suite_id != evaluation.suite_id:
        raise PermissionError("Evaluation tenant or suite mismatch")
    state, environment = evaluation_environment(db, case, version)
    observation = {}
    run = await execute(
        db,
        version,
        case.input,
        evaluation=True,
        state=state,
        environment=environment,
        observation=observation,
        max_cost=max_cost,
        max_seconds=max_seconds,
    )
    checks, failures = grade(run, case, observation)
    if case.rubric:
        from factory.qualitative import grade_rubric

        remaining_seconds = (
            max(0, max_seconds - run.metrics.get("duration_ms", 0) / 1000) if max_seconds is not None else None
        )
        checks.extend(await grade_rubric(db, version, run, case, max_cost, remaining_seconds))
    if case.source == "human":
        checks.append(
            {
                "category": "human_review",
                "passed": False,
                "pending": True,
                "evidence": "Independent human review required",
            }
        )
    failures = [check["category"] for check in checks if not check["passed"]]
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
    trials = {}
    pending_reviews = 0
    regression_outcomes = {}
    for result in results:
        case = db.get(EvaluationCase, result.case_id)
        split_counts[case.split] += 1
        split_passed[case.split] += int(result.passed)
        if case.split == "regression":
            regression_outcomes[f"{case.id}:{result.trial}"] = bool(result.passed)
        trials.setdefault(case.id, []).append(int(result.passed))
        critical_failures += int(case.critical and not result.passed)
        for check in result.checks:
            pending_reviews += int(check.get("pending", False))
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
        "distinct_cases": len(trials),
        "critical_failures": critical_failures,
        "metrics": {key: categories[key] / value for key, value in counts.items()},
        "splits": {
            key: {"passed": split_passed[key], "total": value, "score": split_passed[key] / value}
            for key, value in split_counts.items()
        },
        "mean_latency_ms": sum(durations) / total if total else 0,
        "cost": sum(costs),
        "tokens": sum(tokens),
        "pending_reviews": pending_reviews,
        "regression_outcomes": regression_outcomes,
        "variability": {
            "repeated_cases": sum(len(values) > 1 for values in trials.values()),
            "unstable_cases": sum(len(set(values)) > 1 for values in trials.values()),
            "cases": {
                case_id: {
                    "trials": len(values),
                    "pass_rate": sum(values) / len(values),
                    "standard_deviation": pstdev(values),
                    "min": min(values),
                    "max": max(values),
                }
                for case_id, values in trials.items()
                if len(values) > 1
            },
        },
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
                "input": redact(case.input),
                "output": run.output,
                "failed_checks": [c for c in result.checks if not c["passed"]],
            }
        )
    return redact_tenant(db, evaluation.org_id, evidence)


def can_promote(candidate, baseline=None, policy=None):
    policy = QualityPolicy.model_validate(policy or {})
    if (
        not candidate["total"]
        or candidate["critical_failures"]
        or candidate.get("pending_reviews")
        or candidate["metrics"].get("safety", 0) < 1
        or candidate["metrics"].get("approval_compliance", 1) < 1
    ):
        return False
    if (
        candidate["mean_latency_ms"] > policy.maximum_mean_latency_ms
        or candidate["cost"] > policy.maximum_evaluation_cost
    ):
        return False
    if baseline is None:
        return True
    if candidate["splits"].get("regression", {}).get("score", 0) < baseline["splits"].get("regression", {}).get(
        "score", 0
    ):
        return False
    if candidate["score"] < baseline["score"]:
        return False
    if any(
        passed and not candidate.get("regression_outcomes", {}).get(key, False)
        for key, passed in baseline.get("regression_outcomes", {}).items()
    ):
        return False
    if policy.objective == "cost":
        return (
            candidate["score"] >= policy.minimum_score
            and baseline["cost"] - candidate["cost"] > policy.minimum_improvement
        )
    if policy.objective == "latency":
        return (
            candidate["score"] >= policy.minimum_score
            and baseline["mean_latency_ms"] - candidate["mean_latency_ms"] > policy.minimum_improvement
        )
    return candidate["score"] - baseline["score"] > policy.minimum_improvement


async def evaluate_suite(
    db, version, suite, splits=("development", "regression", "validation"), max_cost=5, max_seconds=1800
):
    evaluation = EvaluationRun(org_id=version.org_id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    spent, started = 0.0, time.monotonic()
    for case in db.scalars(
        select(EvaluationCase)
        .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(splits))
        .order_by(EvaluationCase.id)
    ):
        for trial in range(case.trials):
            if time.monotonic() - started >= max_seconds or spent > max_cost:
                evaluation.status = "budget_exhausted"
                evaluation.scorecard = scorecard(db, evaluation)
                return evaluation
            result = await evaluate_case(
                db,
                evaluation,
                version,
                case,
                trial,
                max_cost=max(0, max_cost - spent),
                max_seconds=max(0, max_seconds - (time.monotonic() - started)),
            )
            spent += db.get(ExecutionRun, result.execution_id).metrics.get("cost", 0)
    evaluation.scorecard = scorecard(db, evaluation)
    evaluation.status = "completed"
    return evaluation
