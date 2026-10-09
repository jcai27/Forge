"""Test harness: interrupt an owned worker during an uncommitted evaluation checkpoint."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from factory import workflow
from factory.db import make_engine
from factory.models import BuildJob

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
job_id, mode, marker = sys.argv[1:]


async def main():
    if mode == "interrupt":
        original = workflow.advance

        async def hold(db, job):
            await original(db, job)
            Path(marker).write_text("uncommitted_checkpoint")
            await asyncio.sleep(60)

        workflow.advance = hold
        await workflow.worker_tick(sessions)
    else:
        for _ in range(500):
            await workflow.worker_tick(sessions)
            with sessions() as db:
                job = db.get(BuildJob, job_id)
                if job.state in workflow.TERMINAL:
                    print(job.state, flush=True)
                    return
            await asyncio.sleep(0.02)
        raise RuntimeError("Worker did not reach terminal state")


asyncio.run(main())
