"""Owned local SDK fixture: kill after an evaluation-agent reservation commits."""

import asyncio
import os
import sys
from pathlib import Path

from agents import Agent, Model
from sqlalchemy.orm import sessionmaker

from factory import runtime
from factory.db import make_engine
from factory.models import AgentVersion, BuildJob, EvaluationCase

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
case_id, job_id, marker = sys.argv[1:]


class BlockedProvider(Model):
    async def get_response(self, *args, **kwargs):
        Path(marker).write_text("local_evaluation_dispatched")
        await asyncio.sleep(60)
        raise RuntimeError("Fixture process must be killed before returning")

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


runtime.Agent = lambda **kwargs: Agent(**{**kwargs, "model": BlockedProvider()})


async def main():
    with sessions() as db:
        case, job = db.get(EvaluationCase, case_id), db.get(BuildJob, job_id)
        version = db.get(AgentVersion, job.checkpoint["version_id"])
        await runtime.execute(db, version, case.input, evaluation=True, job=job)


asyncio.run(main())
