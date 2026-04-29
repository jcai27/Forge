import asyncio
from contextlib import suppress

from app.db.session import init_db
from app.services.runtime_worker import runtime_job_worker


async def _main() -> None:
    init_db()
    await runtime_job_worker.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runtime_job_worker.stop()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(_main())
