"""Release evidence and feedback: shadow comparison, the release dossier, and the tenant playbook.

Everything here is read-only towards business systems. A shadow run executes the candidate in evaluation
mode, where writes are refused, and compares it with what the deployed version already answered.
"""

import json
import time

from sqlalchemy import select

from factory.db import now
from factory.models import (
    AgentRecord,
    AgentVersion,
    Approval,
    BuildIteration,
    Connection,
    Deployment,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    ExecutionEvent,
    ExecutionRun,
    Invocation,
    ToolDefinition,
)
from factory.schemas import AgentSpec
from factory.security import redact_tenant

# Hypotheses that describe bookkeeping rather than an idea worth reusing.
NOT_AN_IDEA = ("Initial candidate", "Background requirements", "User ", "Administrator-approved", "No ")


def playbook(db, org_id, template, exclude_agent_id=None, limit=5):
    """Hypotheses that were measured and promoted for this tenant's other agents of the same kind."""
    rows = db.execute(
        select(AgentVersion.hypothesis, BuildIteration.created_at)
        .join(BuildIteration, BuildIteration.version_id == AgentVersion.id)
        .join(AgentRecord, AgentRecord.id == AgentVersion.agent_id)
        .where(
            AgentVersion.org_id == org_id,
            BuildIteration.org_id == org_id,
            AgentRecord.org_id == org_id,
            AgentRecord.template == template,
            BuildIteration.promoted.is_(True),
            *([AgentRecord.id != exclude_agent_id] if exclude_agent_id else []),
        )
        .order_by(BuildIteration.created_at.desc())
        .limit(200)
    ).all()
    ideas = []
    for hypothesis, _ in rows:
        if hypothesis and not hypothesis.startswith(NOT_AN_IDEA) and hypothesis not in ideas:
            ideas.append(hypothesis)
        if len(ideas) >= limit:
            break
    return redact_tenant(db, org_id, ideas)


def changed_fields(before, after):
    keys = sorted(set(before or {}) | set(after or {}))
    return [key for key in keys if (before or {}).get(key) != (after or {}).get(key)]


async def shadow_run(db, actor, candidate, limit=10, max_cost=1.0, max_seconds=120, authorize_live_reads=False):
    """Replay recent real inputs through a candidate, read-only, and compare with the deployed answers."""
    from factory.runtime import emit, execute

    deployment = db.scalar(
        select(Deployment).where(
            Deployment.agent_id == candidate.agent_id,
            Deployment.org_id == candidate.org_id,
            Deployment.active.is_(True),
        )
    )
    if not deployment:
        raise ValueError("A shadow comparison needs an active deployment to compare with")
    if deployment.version_id == candidate.id:
        raise ValueError("This version is already the deployed one")
    spec = AgentSpec.model_validate(candidate.spec)
    external = [
        connection.id
        for connection in db.scalars(select(Connection).where(Connection.id.in_(spec.connection_ids)))
        if connection.kind != "fixture"
    ]
    if external and not authorize_live_reads:
        raise PermissionError("This version reads external systems; authorize read-only access for the shadow run")
    environment = (
        {"source": "live_read_only", "live_connection_ids": external, "authorized_by": actor.user_id}
        if external
        else {"source": "synthetic", "authorized_by": None}
    )
    invocations = list(
        db.scalars(
            select(Invocation)
            .where(Invocation.deployment_id == deployment.id, Invocation.org_id == candidate.org_id)
            .order_by(Invocation.created_at.desc())
            .limit(limit)
        )
    )
    if not invocations:
        raise ValueError("The deployment has no invocations to compare against yet")
    started, spent, different, identical, blocked_writes, compared = time.monotonic(), 0.0, [], 0, 0, 0
    for invocation in invocations:
        remaining = max_seconds - (time.monotonic() - started)
        if remaining <= 0 or spent >= max_cost:
            break
        baseline = db.get(ExecutionRun, invocation.run_id)
        run = await execute(
            db,
            candidate,
            baseline.input,
            evaluation=True,
            environment=environment,
            max_cost=max(0, max_cost - spent),
            max_seconds=remaining,
        )
        spent += run.metrics.get("cost", 0) + run.metrics.get("reserved_cost", 0)
        compared += 1
        if run.error == "PermissionError":
            blocked_writes += 1
        fields = changed_fields(baseline.output, run.output)
        if fields or (run.status == "failed") != (baseline.status == "failed"):
            different.append(
                {
                    "baseline_run_id": baseline.id,
                    "candidate_run_id": run.id,
                    "baseline_status": baseline.status,
                    "candidate_status": run.status,
                    "changed_fields": fields[:20],
                }
            )
        else:
            identical += 1
    report = {
        "deployment_id": deployment.id,
        "baseline_version_id": deployment.version_id,
        "candidate_version_id": candidate.id,
        "available": len(invocations),
        "compared": compared,
        "identical": identical,
        "different": different,
        "blocked_or_refused": blocked_writes,
        "live_reads_authorized": bool(external),
        "cost": spent,
        "at": now().isoformat(),
        "note": "Executed read-only in evaluation mode; no write or approval was created.",
    }
    emit(db, candidate.org_id, "shadow_report", report)
    return report


def latest_shadow(db, version):
    for event in db.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.org_id == version.org_id, ExecutionEvent.kind == "shadow_report")
        .order_by(ExecutionEvent.created_at.desc())
        .limit(100)
    ):
        if event.payload.get("candidate_version_id") == version.id:
            return event.payload
    return None


def reviewed_code_hashes(db, version):
    hashes = set()
    for earlier in db.scalars(
        select(AgentVersion).where(
            AgentVersion.agent_id == version.agent_id,
            AgentVersion.org_id == version.org_id,
            AgentVersion.approved_at.is_not(None),
        )
    ):
        hashes.update(tool.get("code_hash") for tool in earlier.spec.get("generated_tools") or [])
    return hashes


def dossier(db, version, gate):
    """One page a reviewer can approve from: what it is, what it can reach, how it measured, what is open."""
    spec = AgentSpec.model_validate(version.spec)
    suites = [s.id for s in db.scalars(select(EvaluationSuite).where(EvaluationSuite.agent_id == version.agent_id))]
    cases = {c.id: c for c in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id.in_(suites)))}
    runs = list(
        db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.version_id == version.id, EvaluationRun.status == "completed")
            .order_by(EvaluationRun.created_at.desc())
            .limit(10)
        )
    )
    evidence = [
        {
            "evaluation_id": run.id,
            "at": run.created_at.isoformat() if hasattr(run.created_at, "isoformat") else None,
            "score": run.scorecard.get("score"),
            "graded_score": run.scorecard.get("graded_score"),
            "total": run.scorecard.get("total"),
            "critical_failures": run.scorecard.get("critical_failures"),
            "confidence_interval_95": run.scorecard.get("confidence_interval_95"),
            "splits": run.scorecard.get("splits"),
            "provisional": True,
        }
        for run in runs
    ]
    newest = {}
    for result in db.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.evaluation_run_id.in_([run.id for run in runs]))
        .order_by(EvaluationResult.created_at.desc())
    ):
        newest.setdefault((result.case_id, result.trial), result)
    failures = [
        {"case": cases[case_id].name, "split": cases[case_id].split, "failed": result.failures}
        for (case_id, _), result in newest.items()
        if not result.passed and case_id in cases
    ]
    connections = list(db.scalars(select(Connection).where(Connection.id.in_(spec.connection_ids))))
    tools = {t.id: t for t in db.scalars(select(ToolDefinition).where(ToolDefinition.id.in_(spec.tools)))}
    reviewed = reviewed_code_hashes(db, version)
    generated = [
        {
            "name": tool.name,
            "code_hash": tool.code_hash,
            "capabilities": {
                alias: tools[tid].name if tid in tools else tid for alias, tid in tool.capabilities.items()
            },
            "reviewed": tool.code_hash in reviewed,
        }
        for tool in spec.generated_tools
    ]
    sources = set()
    for event in db.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.org_id == version.org_id, ExecutionEvent.kind == "improvement_hypothesis")
        .order_by(ExecutionEvent.created_at.desc())
        .limit(500)
    ):
        if event.payload.get("version_id") == version.id:
            sources.update(event.payload.get("research_sources") or [])
    shadow = latest_shadow(db, version)
    deployed = db.scalar(select(Deployment).where(Deployment.agent_id == version.agent_id, Deployment.active.is_(True)))
    open_items = []
    if not gate["passed"]:
        open_items.append("Quality gate: " + gate["reason"])
    if any(not tool["reviewed"] for tool in generated):
        open_items.append("Builder-written tool code has not been reviewed and acknowledged")
    if deployed and deployed.version_id != version.id and not shadow:
        open_items.append("No shadow comparison against the deployed version has been run")
    if shadow and shadow["different"]:
        open_items.append(f"Shadow comparison differs on {len(shadow['different'])} of {shadow['compared']} inputs")
    if sources:
        open_items.append("Public web pages informed this version; confirm what they claim independently")
    if not version.approved_at:
        open_items.append("Not yet approved by an administrator")
    return redact_tenant(
        db,
        version.org_id,
        {
            "version": {
                "id": version.id,
                "number": version.number,
                "hypothesis": version.hypothesis,
                "approved": bool(version.approved_at),
                "deployed": bool(deployed and deployed.version_id == version.id),
            },
            "quality_gate": gate,
            "evidence": evidence,
            "known_failures": failures[:50],
            "reach": {
                "connections": [
                    {
                        "name": c.name,
                        "kind": c.kind,
                        "hosts": c.config.get("allowed_hosts", []),
                        "write_allowed": bool(c.permissions.get("write")),
                        "status": c.status,
                    }
                    for c in connections
                ],
                "tools": sorted(
                    [{"name": t.name, "write": t.write} for t in tools.values()], key=lambda item: item["name"]
                ),
            },
            "generated_code": generated,
            "bundle": {
                "examples": len(spec.examples),
                "verifiers": [v.id for v in spec.verifiers],
                "tool_notes": len(spec.tool_notes),
            },
            "provenance": {"research_sources": sorted(sources)},
            "shadow": shadow,
            "limits": {
                "model": spec.model,
                "max_cost": spec.max_cost,
                "max_turns": spec.max_turns,
                "timeout_seconds": spec.timeout_seconds,
                "quality_policy": spec.quality_policy.model_dump(),
            },
            "open_items": open_items,
        },
    )


def feedback_candidates(db, agent, limit=50):
    """Deployed runs a person corrected or that went wrong: the best raw material for new test cases."""
    suites = [s.id for s in db.scalars(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))]
    known = {
        json.dumps(case.input, sort_keys=True, default=str)
        for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id.in_(suites)))
    }
    rows = db.execute(
        select(ExecutionRun, Invocation)
        .join(Invocation, Invocation.run_id == ExecutionRun.id)
        .join(Deployment, Deployment.id == Invocation.deployment_id)
        .where(Deployment.agent_id == agent.id, ExecutionRun.org_id == agent.org_id)
        .order_by(ExecutionRun.created_at.desc())
        .limit(500)
    ).all()
    items = []
    for run, _ in rows:
        rejected = db.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "rejected"))
        reason = (
            "A person rejected the proposed action"
            if rejected
            else "The run needed attention"
            if run.status == "needs_attention"
            else "The run failed"
            if run.status == "failed"
            else None
        )
        if not reason:
            continue
        items.append(
            {
                "run_id": run.id,
                "status": run.status,
                "reason": reason,
                "created_at": run.created_at.isoformat() if hasattr(run.created_at, "isoformat") else None,
                "already_a_case": json.dumps(run.input, sort_keys=True, default=str) in known,
            }
        )
        if len(items) >= limit:
            break
    return items
