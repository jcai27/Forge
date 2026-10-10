"""Durable reservations for read-only factory roles, committed before SDK dispatch."""

from datetime import timedelta

from sqlalchemy import select

from factory.config import settings
from factory.db import now
from factory.models import BuildJob, UsageRecord
from factory.runtime import BudgetExceeded, BudgetHooks


class BuildInterrupted(Exception):
    """The caller lost its lease or the user changed the build state."""


class FactoryBudgetHooks(BudgetHooks):
    def __init__(self, max_cost, db, job, role, max_seconds=120):
        super().__init__(max_cost, "live", max_output_tokens=4000)
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
            raise BuildInterrupted()

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        await super().on_llm_start(context, agent, system_prompt, input_items)
        self.lock()
        self.check_active()
        reserve = self.next_reservation
        if self.job.spent + reserve > self.job.budget["max_cost"]:
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
        actual = response.usage.total_tokens * settings().estimated_token_cost
        self.job.spent = (self.job.spent - self.pending.reserved_cost) + actual
        self.pending.cost = actual
        self.pending.tokens = response.usage.total_tokens
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
    # These reservations already contribute to job.spent. Never refund unknown calls.
