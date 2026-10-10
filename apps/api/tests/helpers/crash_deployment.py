"""Owned local SDK fixture: killed after a deployment reservation commits."""

import asyncio
import os
import sys
from pathlib import Path

from agents import Agent, Model
from sqlalchemy.orm import sessionmaker

from factory import runtime
from factory.db import make_engine
from factory.deployment_runtime import execute_job

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
job_id, marker = sys.argv[1:]


class BlockedProvider(Model):
    async def get_response(self, *args, **kwargs):
        Path(marker).write_text("local_deployment_dispatched")
        await asyncio.sleep(60)
        raise RuntimeError("Fixture must be killed before returning")

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


runtime.Agent = lambda **kwargs: Agent(**{**kwargs, "model": BlockedProvider()})


async def main():
    with sessions() as db:
        await execute_job(db, job_id)


asyncio.run(main())
