"""Deployment ledger checkpoints that preserve staged approvals and queue ownership."""

from datetime import timedelta

from sqlalchemy import select

from factory.config import settings
from factory.db import now
from factory.models import AgentVersion, Deployment, Invocation, Membership, RuntimeJob, UsageRecord
from factory.runtime import BudgetExceeded, BudgetHooks


class RuntimeInterrupted(Exception):
    """A returning invocation lost ownership or its dispatch authorization."""


def usage_totals(db, run_id):
    records = list(
        db.scalars(select(UsageRecord).where(UsageRecord.run_id == run_id, UsageRecord.role == "deployment_agent"))
    )
    return {
        "tokens": sum(record.tokens for record in records),
        "cost": sum(record.cost for record in records),
        "reserved_cost": sum(record.reserved_cost for record in records),
        "deployment_accounted": bool(records),
        "cost_is_estimate": True,
    }


def recover_pending(db, run):
    for record in db.scalars(
        select(UsageRecord).where(
            UsageRecord.run_id == run.id, UsageRecord.role == "deployment_agent", UsageRecord.status == "pending"
        )
    ):
        record.status = "uncertain"
    totals = usage_totals(db, run.id)
    if totals["deployment_accounted"]:
        run.metrics = {**run.metrics, **totals}


class DeploymentBudgetHooks(BudgetHooks):
    def __init__(self, ceiling, db, run, job, max_seconds):
        super().__init__(ceiling, "live")
        self.ceiling, self.db, self.run, self.job = ceiling, db, run, job
        self.owner, self.version_id = job.lease_owner, run.version_id
        invocation = db.get(Invocation, job.invocation_id)
        self.invocation_id = invocation.id
        self.deployment = db.get(Deployment, invocation.deployment_id)
        self.deadline = now() + timedelta(seconds=max_seconds + 15)
        self.pending = None
        self.accounted_tokens = self.accounted_cost = 0
        self.sync_usage()

    def lock(self):
        self.db.scalar(
            select(RuntimeJob)
            .where(RuntimeJob.id == self.job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        self.db.scalar(
            select(Deployment)
            .where(Deployment.id == self.deployment.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def guard(self):
        version = self.db.get(AgentVersion, self.version_id, populate_existing=True)
        invocation = self.db.get(Invocation, self.invocation_id, populate_existing=True)
        member = self.db.scalar(
            select(Membership)
            .where(Membership.org_id == self.run.org_id, Membership.user_id == self.job.actor_id)
            .execution_options(populate_existing=True)
        )
        if (
            self.job.lease_owner != self.owner
            or self.job.state != "RUNNING"
            or self.job.org_id != self.run.org_id
            or self.deployment.org_id != self.run.org_id
            or not self.deployment.active
            or self.deployment.version_id != self.version_id
            or not invocation
            or invocation.org_id != self.run.org_id
            or invocation.run_id != self.run.id
            or invocation.deployment_id != self.deployment.id
            or self.job.invocation_id != self.invocation_id
            or not version
            or version.org_id != self.run.org_id
            or version.agent_id != self.deployment.agent_id
            or not version.approved_at
            or not member
            or member.role not in ("admin", "editor")
        ):
            raise RuntimeInterrupted()

    def sync_usage(self):
        totals = usage_totals(self.db, self.run.id)
        self.run.metrics = {**self.run.metrics, **totals}
        self.accounted_tokens, self.accounted_cost = totals["tokens"], totals["cost"]
        return totals

    async def check_control(self):
        self.lock()
        self.guard()
        self.db.commit()  # Only run/events/ledger; tool approvals remain staged in memory.

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.lock()
        self.guard()
        totals = self.sync_usage()
        limit = min(self.ceiling, self.job.reservation, self.deployment.policy.get("max_cost", 1))
        self.max_cost = self.cost + max(0, limit - totals["cost"] - totals["reserved_cost"])
        if self.deployment.spent + self.deployment.reserved > self.deployment.policy.get("lifetime_max_cost", 10):
            raise BudgetExceeded("Deployment lifetime budget exhausted")
        await super().on_llm_start(context, agent, system_prompt, input_items)
        self.pending = UsageRecord(
            org_id=self.run.org_id,
            run_id=self.run.id,
            role="deployment_agent",
            status="pending",
            reserved_cost=self.next_reservation,
        )
        self.db.add(self.pending)
        self.run.status = "running"
        self.sync_usage()
        self.job.lease_until = self.deadline
        self.db.commit()

    async def on_llm_end(self, context, agent, response):
        self.lock()
        reserve = self.pending.reserved_cost
        actual = response.usage.total_tokens * settings().estimated_token_cost
        self.pending.tokens, self.pending.cost = response.usage.total_tokens, actual
        self.pending.status, self.pending.reserved_cost = "recorded", 0
        # A late response may resolve an unknown charge after another worker finalized.
        if self.job.reservation == 0:
            self.deployment.reserved = max(0, self.deployment.reserved - reserve)
            self.deployment.spent += actual
        self.db.refresh(self.run)
        self.sync_usage()
        self.db.commit()
        self.pending = None
        await super().on_llm_end(context, agent, response)
        await self.check_control()

    async def on_tool_start(self, context, agent, tool):
        await self.check_control()

    async def on_tool_end(self, context, agent, tool, result):
        await self.check_control()

    def finish(self):
        pending_id = self.pending.id if self.pending is not None else None
        try:
            with self.db.no_autoflush:
                self.lock()
                self.guard()
                totals = usage_totals(self.db, self.run.id)
                if totals["cost"] + totals["reserved_cost"] > self.deployment.policy.get(
                    "max_cost", 1
                ) or self.deployment.spent + self.deployment.reserved > self.deployment.policy.get(
                    "lifetime_max_cost", 10
                ):
                    raise RuntimeInterrupted()
        except RuntimeInterrupted:
            self.db.rollback()  # Discard a stale final result and any attached approvals.
            if pending_id:
                record = self.db.get(UsageRecord, pending_id)
                record.status = "uncertain"
                self.sync_usage()
                self.db.commit()
            raise
        if self.pending is not None:
            self.pending.status = "uncertain"
            self.sync_usage()
        # Keep queue/deployment locked. Caller commits result, approvals and settlement.
