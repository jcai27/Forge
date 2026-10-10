"""Prepare a reviewed-proposal browser fixture using a local SDK model, never OpenAI.

This helper is only for scripts/test-api.sh's disposable database. The real worker
creates the proposal checkpoint; no evaluation result or score is seeded.
"""

import asyncio
import sys
from pathlib import Path

from agents import Agent
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seed_browser_collections import seed_collections
from test_factory_roles import ProposalProvider

from factory import builder
from factory.api import create_agent, demo
from factory.config import settings
from factory.db import SessionLocal
from factory.models import AgentRecord, Connection, EvaluationCase, Membership, Project, UsageRecord
from factory.schemas import Budget, CreateAgent
from factory.security import Principal
from factory.workflow import advance, new_job


async def main():
    if not settings().database_url.startswith("sqlite:////tmp/factory-e2e-"):
        raise RuntimeError("Browser fixtures require the disposable E2E database")
    with SessionLocal() as db:
        await demo(db)
        member = db.scalar(select(Membership))
        project = db.scalar(select(Project).where(Project.org_id == member.org_id))
        connection = db.scalar(
            select(Connection).where(Connection.org_id == member.org_id, Connection.kind == "fixture")
        )
        created = await create_agent(
            CreateAgent(
                project_id=project.id,
                request="Process restaurant orders with reviewed catalog expectations",
                template="orders",
                connection_ids=[connection.id],
            ),
            Principal(member.user_id, member.org_id, "admin"),
            db,
        )
        agent = db.get(AgentRecord, created["id"])
        agent.name = "Local SDK proposal review fixture"
        for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])):
            db.delete(case)
        job = new_job(db, agent, Budget())
        job.state = "BUILDING"
        db.commit()
        calls = []
        settings().execution_mode = "live"
        settings().openai_api_key = "explicit-local-browser-designer-contract"
        builder.Agent = lambda **kwargs: Agent(**{**kwargs, "model": ProposalProvider(calls)})
        await advance(db, job)
        db.commit()
        assert job.state == "WAITING_FOR_APPROVAL" and len(calls) == 1
        record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
        assert record.role == "test_designer" and record.status == "recorded"
        assert list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"]))) == []
        settings().execution_mode = "demo"
        await seed_collections(db)


asyncio.run(main())
