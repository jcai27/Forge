from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib import error, request

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import EventType, TrackVersion
from app.runtime.provisioner import runtime_provisioner
from app.schemas import SessionEventCreate, WorkspaceAssistantRequest
from app.services.platform import (
    append_session_event,
    ensure_session_editable,
    get_runtime_job,
    get_session_or_404,
    serialize_session,
    write_workspace_file,
)

logger = logging.getLogger(__name__)

PREFERRED_CONTEXT_PATHS = [
    "app/routes.py",
    "app/main.py",
    "tests/test_inventory.py",
    "README.md",
    "pyproject.toml",
]
MAX_CONTEXT_FILES = 8
MAX_CONTEXT_CHARS = 60_000
MAX_CHANGED_FILES = 6


def _assistant_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["path", "content", "summary"],
                },
            },
            "suggested_command": {"type": "string"},
            "follow_up": {"type": "string"},
        },
        "required": ["summary", "changes", "suggested_command", "follow_up"],
    }


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _dedupe_paths(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for path in paths:
        normalized = path.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _candidate_context_paths(payload: WorkspaceAssistantRequest, available_paths: list[str]) -> list[str]:
    available = set(available_paths)
    requested = _dedupe_paths([payload.selected_path or "", *payload.open_paths, *PREFERRED_CONTEXT_PATHS])
    return [path for path in requested if path in available][:MAX_CONTEXT_FILES]


def _read_context_files(workspace_id: str, paths: list[str]) -> list[dict[str, str]]:
    included: list[dict[str, str]] = []
    total_chars = 0
    for path in paths:
        file_payload = runtime_provisioner.read_workspace_file(workspace_id, path)
        content = file_payload.get("content", "")
        remaining = MAX_CONTEXT_CHARS - total_chars
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[:remaining]
        included.append({"path": path, "content": content})
        total_chars += len(content)
    return included


def _workspace_tree_text(items: list[dict[str, Any]]) -> str:
    entries = [item["path"] for item in items if item.get("type") == "file"]
    return "\n".join(entries[:200])


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    if isinstance(response_payload.get("error"), dict):
        detail = str(response_payload["error"].get("message") or "OpenAI did not complete the response.")
        raise HTTPException(status_code=502, detail=f"OpenAI response error: {detail}")

    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    output_items = response_payload.get("output") or []
    if not isinstance(output_items, list):
        output_items = []

    for item in output_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content_items = item.get("content") or []
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                refusal = content.get("refusal") or "The model refused to complete the request."
                raise HTTPException(status_code=422, detail=refusal)
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])

    if parts:
        return "".join(parts)
    raise HTTPException(status_code=502, detail="OpenAI response did not include assistant text.")


def _reasoning_options(model: str) -> dict[str, str] | None:
    if "codex" in model:
        return {"effort": "low"}
    if model.startswith("gpt-5.1") or model.startswith("gpt-5.2"):
        return {"effort": "none"}
    if model.startswith("gpt-5"):
        return {"effort": "low"}
    return None


def _call_openai_workspace_editor(*, prompt: str, selected_path: str | None, track: TrackVersion, tree_text: str, context_files: list[dict[str, str]]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured. Add it to .env and restart the API.")

    instructions = (
        "You are a precise coding assistant inside a controlled browser IDE. "
        "Return only JSON that matches the supplied schema. "
        "Apply the user's request by editing code directly when possible. "
        "Keep changes narrow, production-minded, and consistent with the existing code. "
        "Do not invent files unless they are clearly needed for the request. "
        "Prefer updating the selected file and related tests. "
        "Return complete file contents for each changed file. "
        "Do not wrap file contents in markdown fences."
    )
    user_input = {
        "selected_path": selected_path,
        "track_title": track.title,
        "track_prompt": track.prompt_markdown,
        "workspace_files": tree_text,
        "context_files": context_files,
        "request": prompt,
    }

    request_body: dict[str, Any] = {
        "model": settings.openai_model,
        "instructions": instructions,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(user_input, ensure_ascii=True),
                    }
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "workspace_edit_plan",
                "schema": _assistant_schema(),
                "strict": True,
            }
        },
        "max_output_tokens": 8000,
    }
    reasoning = _reasoning_options(settings.openai_model)
    if reasoning:
        request_body["reasoning"] = reasoning

    api_request = request.Request(
        f"{settings.openai_base_url.rstrip('/')}/responses",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(api_request, timeout=settings.openai_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        detail = response_body
        try:
            parsed = json.loads(response_body)
            detail = parsed.get("error", {}).get("message") or response_body
        except json.JSONDecodeError:
            pass
        raise HTTPException(status_code=502, detail=f"OpenAI API request failed: {detail}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI API connection failed: {exc.reason}") from exc

    output_text = _extract_output_text(response_payload)
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI response was not valid JSON.") from exc

    if not isinstance(parsed_output, dict):
        raise HTTPException(status_code=502, detail="OpenAI response JSON had an unexpected shape.")
    return parsed_output


def apply_workspace_assistant(
    db: Session,
    *,
    session_id: str,
    payload: WorkspaceAssistantRequest,
) -> dict[str, Any]:
    try:
        session = get_session_or_404(db, session_id)
        ensure_session_editable(session)

        track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
        if not track:
            raise HTTPException(status_code=404, detail="Track version not found")

        items = runtime_provisioner.list_workspace_files(session.workspace_id)
        available_paths = [item["path"] for item in items if item.get("type") == "file"]
        context_paths = _candidate_context_paths(payload, available_paths)
        context_files = _read_context_files(session.workspace_id, context_paths)

        append_session_event(
            db,
            session_id,
            SessionEventCreate(
                event_type=EventType.ai_request,
                payload={
                    "prompt": payload.prompt,
                    "selected_path": payload.selected_path,
                    "context_paths": context_paths,
                    "requested_at": _iso_now(),
                },
            ),
        )

        plan = _call_openai_workspace_editor(
            prompt=payload.prompt,
            selected_path=payload.selected_path,
            track=track,
            tree_text=_workspace_tree_text(items),
            context_files=context_files,
        )

        changed_files: list[dict[str, Any]] = []
        changed_paths: list[str] = []
        raw_changes = plan.get("changes") or []
        if not isinstance(raw_changes, list):
            raw_changes = []

        for change in raw_changes[:MAX_CHANGED_FILES]:
            if not isinstance(change, dict):
                continue
            path = str(change.get("path", "")).strip()
            content = change.get("content")
            if not path or not isinstance(content, str):
                continue
            write_result = write_workspace_file(
                db,
                session.id,
                path=path,
                content=content,
                expected_updated_at=None,
            )
            file_payload = runtime_provisioner.read_workspace_file(session.workspace_id, path)
            changed_paths.append(path)
            changed_files.append(
                {
                    **file_payload,
                    "summary": str(change.get("summary", "")).strip(),
                    "size": write_result["file"]["size"],
                    "updated_at": write_result["file"]["updated_at"],
                }
            )

        append_session_event(
            db,
            session_id,
            SessionEventCreate(
                event_type=EventType.ai_response,
                payload={
                    "summary": str(plan.get("summary", "")).strip(),
                    "changed_paths": changed_paths,
                    "suggested_command": str(plan.get("suggested_command", "")).strip(),
                    "follow_up": str(plan.get("follow_up", "")).strip(),
                    "responded_at": _iso_now(),
                },
            ),
        )

        refreshed_session = get_session_or_404(db, session_id)
        return {
            "session": serialize_session(refreshed_session, get_runtime_job(db, refreshed_session.id)),
            "assistant": {
                "summary": str(plan.get("summary", "")).strip(),
                "suggested_command": str(plan.get("suggested_command", "")).strip(),
                "follow_up": str(plan.get("follow_up", "")).strip(),
                "changed_files": changed_files,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        logger.exception("Workspace assistant failed", extra={"session_id": session_id})
        raise HTTPException(status_code=502, detail=f"Assistant request failed unexpectedly: {exc}") from exc
