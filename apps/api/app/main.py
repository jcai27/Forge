from contextlib import asynccontextmanager
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import router
from app.core.config import runtime_worker_embeds_in_api, settings
from app.db.session import SessionLocal
from app.db.session import init_db
from app.services.object_store import object_store
from app.services.runtime_maintenance import runtime_maintenance
from app.services.runtime_worker import runtime_job_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.runtime_worker_enabled and runtime_worker_embeds_in_api():
        await runtime_job_worker.start()
    await runtime_maintenance.start()
    yield
    await runtime_maintenance.stop()
    if settings.runtime_worker_enabled and runtime_worker_embeds_in_api():
        await runtime_job_worker.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3200",
        "http://127.0.0.1:3200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.middleware("http")
async def request_context_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex[:12]}"
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["x-request-id"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
            }
        )
    )
    return response


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/liveness")
def liveness():
    return {"status": "alive"}


@app.get("/readiness")
def readiness():
    checks: dict[str, str] = {}

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(status_code=503, content={"status": "failed", "checks": {"database": f"error: {exc}"}})
    finally:
        db.close()

    try:
        object_store.ensure_root()
        checks["object_store"] = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(status_code=503, content={"status": "failed", "checks": {**checks, "object_store": f"error: {exc}"}})

    if settings.runtime_worker_enabled and runtime_worker_embeds_in_api() and not runtime_job_worker.status().get("loop_running"):
        return JSONResponse(status_code=503, content={"status": "failed", "checks": {**checks, "runtime_worker": "not_running"}})

    return {"status": "ready", "checks": checks}
