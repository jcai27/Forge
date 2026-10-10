"""Durable reservations for read-only factory roles, committed before SDK dispatch."""

from datetime import timedelta

from sqlalchemy import select

from factory.db import now
from factory.models import BuildJob, ExecutionRun, UsageRecord
from factory.pricing import cached_tokens, model_name, usage_cost
from factory.runtime import BudgetExceeded, BudgetHooks


class BuildInterrupted(Exception):
    """The caller lost its lease or the user changed the build state."""


class FactoryBudgetHooks(BudgetHooks):
    def __init__(self, max_cost, db, job, role, max_seconds=120, max_output_tokens=4000):
        super().__init__(max_cost, "live", max_output_tokens=max_output_tokens)
        self.db, self.job, self.role = db, job, role
        self.owner, self.stage = job.lease_owner, job.state
        self.pending = None
        self.reserved_cost = 0.0
        self.deadline = now() + timedelta(seconds=max_seconds + 15)

    def lock(self):
        self.db.scalar(
            select(BuildJob)
            .where(BuildJob.id == self.job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def check_active(self):
        if self.job.lease_owner != self.owner or self.job.state != self.stage:
            # Let go of the build row before unwinding: the SDK awaits while it cleans up, and anything
            # else waiting on that row in this process would wait forever.
            self.db.commit()
            raise BuildInterrupted()

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        await super().on_llm_start(context, agent, system_prompt, input_items)
        self.lock()
        self.check_active()
        reserve = self.next_reservation
        if self.job.spent + reserve > self.job.budget["max_cost"]:
            self.db.commit()
            raise BudgetExceeded("Insufficient build budget for next model call")
        self.pending = UsageRecord(
            org_id=self.job.org_id,
            job_id=self.job.id,
            role=self.role,
            status="pending",
            reserved_cost=reserve,
        )
        self.db.add(self.pending)
        self.job.spent += reserve
        if self.owner:
            # The lease must outlive the bounded request, including very short settings.
            self.job.lease_until = self.deadline
        self.db.commit()

    async def on_llm_end(self, context, agent, response):
        # Persist observed usage even when the response exceeds the reservation.
        self.lock()
        actual = usage_cost(response.usage, model_name(agent))
        self.job.spent = (self.job.spent - self.pending.reserved_cost) + actual
        self.pending.cost = actual
        self.pending.tokens = response.usage.total_tokens
        self.pending.input_tokens, self.pending.output_tokens = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        self.pending.cached_tokens = cached_tokens(response.usage)
        self.pending.reserved_cost = 0
        self.pending.status = "recorded"
        self.db.commit()
        self.pending = None
        await super().on_llm_end(context, agent, response)

    def finish(self, usage):
        self.lock()
        if self.pending is not None:
            self.pending.status = "uncertain"
            self.reserved_cost = self.pending.reserved_cost
            self.db.commit()
            self.lock()
        if usage is not None:
            usage.update(accounted=True, reserved_cost=self.reserved_cost)
        # Keep the row locked while the caller persists the resulting checkpoint.
        self.check_active()


def recover_reservations(db, job):
    for record in db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id, UsageRecord.status == "pending")):
        record.status = "uncertain"
        if record.role == "evaluation_agent" and record.run_id:
            run = db.scalar(
                select(ExecutionRun)
                .where(ExecutionRun.id == record.run_id, ExecutionRun.org_id == job.org_id)
                .with_for_update()
            )
            if run and run.status == "running":
                run.status, run.error = "failed", "InterruptedProviderCall"
                run.metrics = {**run.metrics, "execution_interrupted": True}
    # These reservations already contribute to job.spent. Never refund unknown calls.


class ReadOnlyRunBudgetHooks(BudgetHooks):
    """Durable isolated/read-only charges; never use for production tool transactions."""

    def __init__(self, ceiling, db, run, job=None, max_seconds=120, role="rubric_evaluator", metric_prefix="grading"):
        super().__init__(ceiling, "live")
        self.ceiling, self.db, self.run, self.job = ceiling, db, run, job
        self.owner, self.stage = (job.lease_owner, job.state) if job else (None, None)
        self.deadline = now() + timedelta(seconds=max_seconds + 15)
        self.pending = None
        self.role, self.metric_prefix = role, metric_prefix
        if job and job.org_id != run.org_id:
            raise PermissionError("Rubric accounting tenant mismatch")

    def lock(self):
        if self.job:
            self.db.scalar(
                select(BuildJob)
                .where(BuildJob.id == self.job.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        self.db.scalar(
            select(ExecutionRun)
            .where(ExecutionRun.id == self.run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def check_active(self):
        if self.job and (self.job.lease_owner != self.owner or self.job.state != self.stage):
            # Let go of the rows before unwinding: trials run side by side, the SDK awaits while it
            # cleans up, and another trial waiting on these rows in this process would wait forever.
            self.db.commit()
            raise BuildInterrupted()

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.lock()
        self.check_active()
        metrics = self.run.metrics
        available = self.ceiling - metrics.get("cost", 0) - metrics.get("reserved_cost", 0)
        self.max_cost = self.cost + max(0, available)
        try:
            await super().on_llm_start(context, agent, system_prompt, input_items)
        except BudgetExceeded:
            self.db.commit()
            raise
        reserve = self.next_reservation
        accounted = metrics.get("build_accounted_cost", 0)
        unaccounted = max(0, metrics.get("cost", 0) - accounted) if self.job else 0
        if self.job and self.job.spent + unaccounted + reserve > self.job.budget["max_cost"]:
            self.db.commit()
            raise BudgetExceeded("Insufficient build budget for rubric call")
        self.pending = UsageRecord(
            org_id=self.run.org_id,
            run_id=self.run.id,
            job_id=self.job.id if self.job else None,
            role=self.role,
            status="pending",
            reserved_cost=reserve,
        )
        self.db.add(self.pending)
        self.run.metrics = {
            **metrics,
            "reserved_cost": metrics.get("reserved_cost", 0) + reserve,
            # The most one call of this run set aside: what a budget must have free for a call to start.
            "peak_reservation": max(metrics.get("peak_reservation", 0), reserve),
        }
        if self.job:
            self.job.spent += unaccounted + reserve
            self.run.metrics = {**self.run.metrics, "build_accounted_cost": accounted + unaccounted}
            if self.owner:
                self.job.lease_until = self.deadline
        self.db.commit()

    async def on_llm_end(self, context, agent, response):
        self.lock()
        actual = usage_cost(response.usage, model_name(agent))
        reserve = self.pending.reserved_cost
        self.pending.tokens, self.pending.cost = response.usage.total_tokens, actual
        self.pending.input_tokens, self.pending.output_tokens = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        self.pending.cached_tokens = cached_tokens(response.usage)
        self.pending.status, self.pending.reserved_cost = "recorded", 0
        metrics = self.run.metrics
        self.run.metrics = {
            **metrics,
            "reserved_cost": max(0, metrics.get("reserved_cost", 0) - reserve),
            "tokens": metrics.get("tokens", 0) + response.usage.total_tokens,
            "cost": metrics.get("cost", 0) + actual,
            self.metric_prefix + "_tokens": metrics.get(self.metric_prefix + "_tokens", 0)
            + response.usage.total_tokens,
            self.metric_prefix + "_cost": metrics.get(self.metric_prefix + "_cost", 0) + actual,
            "cost_is_estimate": True,
            self.metric_prefix + "_cost_is_estimate": True,
        }
        if self.job:
            self.job.spent = (self.job.spent - reserve) + actual
            self.run.metrics = {
                **self.run.metrics,
                "build_accounted_cost": metrics.get("build_accounted_cost", 0) + actual,
            }
        self.db.commit()
        self.pending = None
        await super().on_llm_end(context, agent, response)

    def finish(self, duration_ms):
        self.lock()
        if self.pending is not None:
            self.pending.status = "uncertain"
        metrics = self.run.metrics
        self.run.metrics = {
            **metrics,
            self.metric_prefix + "_tokens": metrics.get(self.metric_prefix + "_tokens", 0),
            self.metric_prefix + "_cost": metrics.get(self.metric_prefix + "_cost", 0),
            self.metric_prefix + "_duration_ms": metrics.get(self.metric_prefix + "_duration_ms", 0) + duration_ms,
            "duration_ms": metrics.get("duration_ms", 0) + duration_ms,
        }
        self.db.commit()
        self.lock()
        self.check_active()


class RubricBudgetHooks(ReadOnlyRunBudgetHooks):
    """Independent rubric grading with no business tools."""


class EvaluationBudgetHooks(ReadOnlyRunBudgetHooks):
    """Only isolated/replayed/authorized read-only agent execution may use these commits."""

    def __init__(self, ceiling, db, run, job=None, max_seconds=120):
        super().__init__(ceiling, db, run, job, max_seconds, role="evaluation_agent", metric_prefix="execution")

    async def check_control(self):
        self.lock()
        self.check_active()
        self.db.commit()

    async def on_llm_end(self, context, agent, response):
        await super().on_llm_end(context, agent, response)
        await self.check_control()

    async def on_tool_start(self, context, agent, tool):
        await self.check_control()

    async def on_tool_end(self, context, agent, tool, result):
        await self.check_control()
