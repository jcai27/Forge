import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
from factory.deployment_runtime import invocation_tick, schedule_tick
from factory.workflow import worker_tick


async def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            scheduled = schedule_tick()
            invoked = await invocation_tick()
            built = await worker_tick()
            if not (scheduled or invoked or built):
                await asyncio.sleep(0.5)
        except Exception:
            logging.error("Worker connection failure; retrying", exc_info=False)
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
