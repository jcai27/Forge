"""Kill/recover an SDK factory request using an explicit local provider contract."""

import asyncio
import json
import os
import sys
from pathlib import Path

from agents import Agent, Model, ModelResponse, Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy.orm import sessionmaker

from factory import builder, workflow
from factory.db import make_engine, uid
from factory.models import BuildJob

engine = make_engine(os.environ["DATABASE_URL"])
if os.getenv("TEST_SCHEMA"):
    engine = engine.execution_options(schema_translate_map={None: os.environ["TEST_SCHEMA"]})
sessions = sessionmaker(engine, expire_on_commit=False)
job_id, mode, marker = sys.argv[1:]
calls = 0


class Provider(Model):
    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        global calls
        calls += 1
        if mode == "interrupt":
            Path(marker).write_text("provider_dispatched")
            await asyncio.sleep(60)
        payload = json.loads(
            next(item["content"] for item in input if isinstance(item, dict) and item.get("role") == "user")
        )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[
                        ResponseOutputText(type="output_text", text=json.dumps(payload["baseline"]), annotations=[])
                    ],
                )
            ],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


builder.Agent = lambda **kwargs: Agent(**{**kwargs, "model": Provider()})


async def main():
    for _ in range(300):
        await workflow.worker_tick(sessions)
        with sessions() as db:
            job = db.get(BuildJob, job_id)
            if job.state != "DESIGNING":
                print(job.state, calls, flush=True)
                return
        await asyncio.sleep(0.02)
    raise RuntimeError("Lease recovery did not advance the factory role")


asyncio.run(main())
