from datetime import UTC, datetime
from types import MethodType
from typing import Any

from app.core.config import settings
from app.main import app
from app.runtime.preview import PreviewHandle, preview_manager


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_path(path: str | None, fallback: str) -> str:
    candidate = path or fallback
    if not candidate.startswith("/"):
        return f"/{candidate}"
    return candidate


def _preview_html(handle: PreviewHandle) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Candidate Preview</title>
    <style>
      body {{
        margin: 0;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: linear-gradient(160deg, #f8f5ee 0%, #efe1cc 100%);
        color: #1a1a1a;
      }}
      main {{
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 32px;
      }}
      section {{
        width: min(720px, 100%);
        border: 1px solid rgba(0, 0, 0, 0.08);
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.9);
        box-shadow: 0 24px 60px rgba(62, 43, 17, 0.12);
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 2rem;
      }}
      p {{
        margin: 0 0 12px;
        line-height: 1.5;
      }}
      code {{
        display: inline-block;
        margin-top: 8px;
        padding: 8px 10px;
        border-radius: 10px;
        background: #f5efe6;
      }}
    </style>
  </head>
  <body>
    <main>
      <section>
        <p>Managed preview</p>
        <h1 data-testid="e2e-preview-heading">Warehouse Ops API Preview</h1>
        <p data-testid="e2e-preview-runtime">Runtime id: {handle.runtime_id}</p>
        <code data-testid="e2e-preview-subject">Session: {handle.subject_id}</code>
      </section>
    </main>
  </body>
</html>
"""


def _start(self: Any, handle: PreviewHandle, preview_config: dict[str, Any], *, image_ref: str | None = None) -> dict[str, Any]:
    readiness_path = _normalize_path(preview_config.get("readiness_path"), "/health")
    default_path = _normalize_path(preview_config.get("default_path"), "/docs")
    summary = {
        "scope": handle.scope,
        "subject_id": handle.subject_id,
        "runtime_id": handle.runtime_id,
        "status": "ready",
        "backend": "e2e",
        "repo_root": str(handle.repo_root),
        "host": settings.preview_host,
        "port": settings.preview_port_start,
        "local_url": f"http://{settings.preview_host}:{settings.preview_port_start}",
        "readiness_path": readiness_path,
        "default_path": default_path,
        "started_at": _utc_iso(),
        "last_accessed_at": _utc_iso(),
        "last_ready_at": _utc_iso(),
        "stopped_at": None,
        "error": None,
        "image_ref": image_ref,
        "log_path": str(handle.log_path),
    }
    return self.write_summary(handle, summary)


def _stop(self: Any, handle: PreviewHandle) -> dict[str, Any]:
    summary = self.read_summary(handle)
    if summary.get("status") in {"not_started", "stopped"}:
        return summary
    summary["status"] = "stopped"
    summary["stopped_at"] = _utc_iso()
    summary["last_accessed_at"] = _utc_iso()
    return self.write_summary(handle, summary)


def _get(self: Any, handle: PreviewHandle) -> dict[str, Any]:
    return self.read_summary(handle)


def _touch(self: Any, handle: PreviewHandle) -> dict[str, Any]:
    summary = self.read_summary(handle)
    summary["last_accessed_at"] = _utc_iso()
    return self.write_summary(handle, summary)


def _proxy_request(
    self: Any,
    handle: PreviewHandle,
    summary: dict[str, Any],
    *,
    method: str,
    request_path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes,
) -> dict[str, Any]:
    _ = (method, query_string, headers, body)
    if summary.get("status") != "ready":
        return {
            "status_code": 409,
            "headers": {"content-type": "application/json"},
            "content": b'{"detail":"Preview is not ready"}',
        }
    self.touch(handle)
    path = _normalize_path(request_path, "/")
    if path == summary.get("readiness_path"):
        return {
            "status_code": 200,
            "headers": {"content-type": "application/json"},
            "content": b'{"status":"ok"}',
        }
    return {
        "status_code": 200,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "content": _preview_html(handle).encode("utf-8"),
    }


preview_manager.start = MethodType(_start, preview_manager)
preview_manager.stop = MethodType(_stop, preview_manager)
preview_manager.get = MethodType(_get, preview_manager)
preview_manager.touch = MethodType(_touch, preview_manager)
preview_manager.proxy_request = MethodType(_proxy_request, preview_manager)

