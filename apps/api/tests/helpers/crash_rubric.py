"""Owned local SDK provider fixture: kill after the rubric reservation commits."""

import asyncio
import os
import sys
from pathlib import Path

from agents import Agent, Model
from sqlalchemy.orm import sessionmaker

from factory import qualitative
from factory.db import make_engine
from factory.models import AgentVersion, BuildJob, EvaluationCase, ExecutionRun

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
run_id, case_id, job_id, marker = sys.argv[1:]


class BlockedProvider(Model):
    async def get_response(self, *args, **kwargs):
        Path(marker).write_text("local_grader_dispatched")
        await asyncio.sleep(60)
        raise RuntimeError("Fixture process must be killed before returning")

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


qualitative.Agent = lambda **kwargs: Agent(**{**kwargs, "model": BlockedProvider()})


async def main():
    with sessions() as db:
        run = db.get(ExecutionRun, run_id)
        await qualitative.grade_rubric(
            db, db.get(AgentVersion, run.version_id), run, db.get(EvaluationCase, case_id), job=db.get(BuildJob, job_id)
        )


asyncio.run(main())
