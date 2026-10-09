"""Exercise runtime lease recovery in real subprocesses without external side effects."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from factory import deployment_runtime
from factory.db import make_engine
from factory.models import RuntimeJob

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
job_id, mode, marker = sys.argv[1:]


async def main():
    if mode == "interrupt":
        original = deployment_runtime.execute

        async def hold(*args, **kwargs):
            run = await original(*args, **kwargs)
            Path(marker).write_text("uncommitted_approval")
            await asyncio.sleep(60)
            return run

        deployment_runtime.execute = hold
        await deployment_runtime.invocation_tick(sessions)
    else:
        for _ in range(500):
            await deployment_runtime.invocation_tick(sessions)
            with sessions() as db:
                job = db.get(RuntimeJob, job_id)
                if job.state in ("COMPLETED", "FAILED"):
                    print(job.state, flush=True)
                    return
            await asyncio.sleep(0.02)
        raise RuntimeError("Runtime queue did not reach terminal state")


asyncio.run(main())
