from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import which
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core.config import resolve_runtime_path, runtime_filesystem_fallback_allowed, settings
from app.runtime.provisioner import CommandResult, CommandRunner, RuntimePaths, SubprocessRunner


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PreviewHandle:
    scope: str
    subject_id: str
    runtime_id: str
    repo_root: Path
    metadata_path: Path
    log_path: Path


class PreviewUnavailableError(RuntimeError):
    pass


class BasePreviewManager:
    backend_name = "base"

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def ensure_roots(self) -> None:
        for path in [self.paths.root, self.paths.workspaces, self.paths.submissions]:
            path.mkdir(parents=True, exist_ok=True)

    def live_handle(self, *, session_id: str, workspace_id: str) -> PreviewHandle:
        workspace_root = self.paths.workspaces / workspace_id
        metadata_dir = workspace_root / "metadata"
        logs_dir = workspace_root / "logs"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        return PreviewHandle(
            scope="live",
            subject_id=session_id,
            runtime_id=workspace_id,
            repo_root=workspace_root / "repo",
            metadata_path=metadata_dir / "preview.json",
            log_path=logs_dir / "preview.log",
        )

    def frozen_handle(self, *, submission_id: str) -> PreviewHandle:
        submission_root = self.paths.submissions / submission_id
        logs_dir = submission_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return PreviewHandle(
            scope="frozen",
            subject_id=submission_id,
            runtime_id=submission_id,
            repo_root=submission_root / "repo",
            metadata_path=submission_root / "preview.json",
            log_path=logs_dir / "preview.log",
        )

    def read_summary(self, handle: PreviewHandle) -> dict[str, Any]:
        if not handle.metadata_path.exists():
            return {
                "scope": handle.scope,
                "subject_id": handle.subject_id,
                "runtime_id": handle.runtime_id,
                "status": "not_started",
                "backend": self.backend_name,
                "log_path": str(handle.log_path),
            }
        return json.loads(handle.metadata_path.read_text(encoding="utf-8"))

    def write_summary(self, handle: PreviewHandle, summary: dict[str, Any]) -> dict[str, Any]:
        handle.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        summary.setdefault("scope", handle.scope)
        summary.setdefault("subject_id", handle.subject_id)
        summary.setdefault("runtime_id", handle.runtime_id)
        summary.setdefault("backend", self.backend_name)
        summary.setdefault("log_path", str(handle.log_path))
        handle.metadata_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def build_default_summary(self, handle: PreviewHandle, preview_config: dict[str, Any], port: int) -> dict[str, Any]:
        readiness_path = preview_config.get("readiness_path", "/")
        if not readiness_path.startswith("/"):
            readiness_path = f"/{readiness_path}"
        default_path = preview_config.get("default_path", "/")
        if not default_path.startswith("/"):
            default_path = f"/{default_path}"
        local_url = f"http://{settings.preview_host}:{port}"
        return {
            "scope": handle.scope,
            "subject_id": handle.subject_id,
            "runtime_id": handle.runtime_id,
            "status": "starting",
            "backend": self.backend_name,
            "repo_root": str(handle.repo_root),
            "host": settings.preview_host,
            "port": port,
            "local_url": local_url,
            "readiness_path": readiness_path,
            "default_path": default_path,
            "started_at": utcnow().isoformat(),
            "last_accessed_at": utcnow().isoformat(),
            "last_ready_at": None,
            "stopped_at": None,
            "error": None,
            "log_path": str(handle.log_path),
        }

    def allocate_port(self) -> int:
        for port in range(settings.preview_port_start, settings.preview_port_end + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((settings.preview_host, port))
                except OSError:
                    continue
                return port
        raise PreviewUnavailableError("No preview ports available")

    def is_enabled(self, preview_config: dict[str, Any]) -> bool:
        return settings.preview_enabled and bool(preview_config.get("enabled"))

    def is_running(self, summary: dict[str, Any]) -> bool:
        return summary.get("status") in {"starting", "ready"}

    def wait_until_ready(self, handle: PreviewHandle, preview_config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
        timeout = int(preview_config.get("startup_timeout_seconds") or settings.preview_startup_timeout_seconds)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process_terminated(summary):
                return self.mark_failed(handle, summary, "Preview process exited before readiness probe passed")
            if self._probe_readiness(summary):
                summary["status"] = "ready"
                summary["last_ready_at"] = utcnow().isoformat()
                summary["error"] = None
                return self.write_summary(handle, summary)
            time.sleep(0.25)
        return self.mark_failed(handle, summary, "Preview failed readiness probe before timeout")

    def touch(self, handle: PreviewHandle) -> dict[str, Any]:
        summary = self.read_summary(handle)
        summary["last_accessed_at"] = utcnow().isoformat()
        return self.write_summary(handle, summary)

    def mark_failed(self, handle: PreviewHandle, summary: dict[str, Any], error: str) -> dict[str, Any]:
        try:
            summary = self._stop_preview_process(handle, summary)
        except Exception:
            pass
        summary["status"] = "failed"
        summary["error"] = error
        summary["stopped_at"] = utcnow().isoformat()
        self.write_summary(handle, summary)
        return summary

    def start(self, handle: PreviewHandle, preview_config: dict[str, Any], *, image_ref: str | None = None) -> dict[str, Any]:
        self.ensure_roots()
        if not self.is_enabled(preview_config):
            raise PreviewUnavailableError("Preview is not configured for this track")
        if not handle.repo_root.exists():
            raise PreviewUnavailableError("Preview repo is not available")

        existing = self.read_summary(handle)
        if self.is_running(existing):
            self.stop(handle)

        port = self.allocate_port()
        summary = self.build_default_summary(handle, preview_config, port)
        self.write_summary(handle, summary)
        started = self._start_preview_process(handle, preview_config, summary, image_ref=image_ref)
        self.write_summary(handle, started)
        return self.wait_until_ready(handle, preview_config, started)

    def stop(self, handle: PreviewHandle) -> dict[str, Any]:
        summary = self.read_summary(handle)
        if summary.get("status") in {"not_started", "stopped"}:
            return summary
        stopped = self._stop_preview_process(handle, summary)
        stopped["status"] = "stopped"
        stopped["stopped_at"] = utcnow().isoformat()
        return self.write_summary(handle, stopped)

    def get(self, handle: PreviewHandle) -> dict[str, Any]:
        summary = self.read_summary(handle)
        if summary.get("status") == "starting" and not self._has_process_handle(summary):
            return summary
        if summary.get("status") == "starting" and self._process_terminated(summary):
            return self.mark_failed(handle, summary, "Preview process exited before readiness probe passed")
        if summary.get("status") == "ready" and self._process_terminated(summary):
            stopped = self._stop_preview_process(handle, summary)
            stopped["status"] = "stopped"
            stopped["error"] = stopped.get("error") or "Preview process is no longer running"
            stopped["stopped_at"] = utcnow().isoformat()
            return self.write_summary(handle, stopped)
        return summary

    def cleanup_expired_previews(self) -> dict[str, Any]:
        now = utcnow()
        cleaned: list[str] = []
        for metadata_path in list(self.paths.workspaces.glob("*/metadata/preview.json")) + list(self.paths.submissions.glob("*/preview.json")):
            summary = json.loads(metadata_path.read_text(encoding="utf-8"))
            if summary.get("status") not in {"starting", "ready"}:
                continue
            last_accessed = summary.get("last_accessed_at") or summary.get("started_at")
            if not last_accessed:
                continue
            try:
                last_accessed_at = datetime.fromisoformat(last_accessed)
            except ValueError:
                continue
            idle_for = (now - last_accessed_at).total_seconds()
            if idle_for < settings.preview_idle_timeout_seconds:
                continue
            if summary.get("scope") == "live":
                handle = self.live_handle(session_id=summary["subject_id"], workspace_id=summary["runtime_id"])
            else:
                handle = self.frozen_handle(submission_id=summary["runtime_id"])
            self.stop(handle)
            cleaned.append(summary["subject_id"])
        return {
            "backend": self.backend_name,
            "cleaned_previews": cleaned,
            "cleaned_count": len(cleaned),
        }

    def list_preview_summaries(self, limit: int | None = None) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for metadata_path in list(self.paths.workspaces.glob("*/metadata/preview.json")) + list(self.paths.submissions.glob("*/preview.json")):
            summaries.append(json.loads(metadata_path.read_text(encoding="utf-8")))
        summaries.sort(key=lambda item: item.get("last_accessed_at") or item.get("started_at") or "", reverse=True)
        if limit is not None:
            return summaries[:limit]
        return summaries

    def runtime_status(self) -> dict[str, Any]:
        summaries = self.list_preview_summaries()
        by_status: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        for summary in summaries:
            by_status[summary.get("status", "unknown")] = by_status.get(summary.get("status", "unknown"), 0) + 1
            by_scope[summary.get("scope", "unknown")] = by_scope.get(summary.get("scope", "unknown"), 0) + 1
        return {
            "configured": settings.preview_enabled,
            "active_backend": self.backend_name,
            "host": settings.preview_host,
            "port_range": [settings.preview_port_start, settings.preview_port_end],
            "idle_timeout_seconds": settings.preview_idle_timeout_seconds,
            "preview_counts": {
                "total": len(summaries),
                "by_status": by_status,
                "by_scope": by_scope,
            },
        }

    def proxy_request(
        self,
        handle: PreviewHandle,
        summary: dict[str, Any],
        *,
        method: str,
        request_path: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        if summary.get("status") != "ready":
            raise PreviewUnavailableError("Preview is not ready")
        port = summary.get("port")
        if port is None:
            raise PreviewUnavailableError("Preview port is unavailable")
        self.touch(handle)
        path = request_path if request_path.startswith("/") else f"/{request_path}"
        if query_string:
            path = f"{path}?{query_string}"
        response = self._proxy_http_request(port=port, method=method, path=path, headers=headers, body=body)
        return response

    def _probe_readiness(self, summary: dict[str, Any]) -> bool:
        local_url = summary.get("local_url")
        readiness_path = summary.get("readiness_path") or "/"
        if not local_url:
            return False
        try:
            with urlopen(f"{local_url}{readiness_path}", timeout=1.0) as response:
                return 200 <= response.status < 400
        except (OSError, URLError):
            return False

    def _proxy_http_request(self, *, port: int, method: str, path: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        connection = http.client.HTTPConnection(settings.preview_host, port, timeout=10)
        forwarded_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        if body:
            forwarded_headers["Content-Length"] = str(len(body))
        connection.request(method.upper(), path, body=body or None, headers=forwarded_headers)
        response = connection.getresponse()
        response_headers = {key: value for key, value in response.getheaders()}
        payload = response.read()
        connection.close()
        return {
            "status_code": response.status,
            "headers": response_headers,
            "content": payload,
        }

    def _process_terminated(self, summary: dict[str, Any]) -> bool:
        return False

    def _has_process_handle(self, summary: dict[str, Any]) -> bool:
        return False

    def _start_preview_process(
        self,
        handle: PreviewHandle,
        preview_config: dict[str, Any],
        summary: dict[str, Any],
        *,
        image_ref: str | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _stop_preview_process(self, handle: PreviewHandle, summary: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class FilesystemPreviewManager(BasePreviewManager):
    backend_name = "filesystem"

    def __init__(self, paths: RuntimePaths) -> None:
        super().__init__(paths)

    def _start_preview_process(
        self,
        handle: PreviewHandle,
        preview_config: dict[str, Any],
        summary: dict[str, Any],
        *,
        image_ref: str | None,
    ) -> dict[str, Any]:
        command = str(preview_config["start_command_template"]).replace("{PORT}", str(summary["port"]))
        handle.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = handle.log_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        interpreter_dir = str(Path(sys.executable).resolve().parent)
        env["PATH"] = f"{interpreter_dir}:{env.get('PATH', '')}"
        process = subprocess.Popen(
            ["sh", "-lc", f"PYTHONPATH=. {command}"],
            cwd=handle.repo_root,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=env,
        )
        log_handle.close()
        summary["pid"] = process.pid
        return summary

    def _stop_preview_process(self, handle: PreviewHandle, summary: dict[str, Any]) -> dict[str, Any]:
        pid = summary.get("pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return summary

    def _process_terminated(self, summary: dict[str, Any]) -> bool:
        pid = summary.get("pid")
        if not pid:
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        return False

    def _has_process_handle(self, summary: dict[str, Any]) -> bool:
        return bool(summary.get("pid"))


class DockerPreviewManager(BasePreviewManager):
    backend_name = "docker"

    def __init__(self, paths: RuntimePaths, docker_bin: str, runner: CommandRunner | None = None) -> None:
        super().__init__(paths)
        self.docker_bin = docker_bin
        self.runner = runner or SubprocessRunner()

    def docker_available(self) -> bool:
        if not self.docker_bin or which(self.docker_bin) is None:
            return False
        result = self.runner.run([self.docker_bin, "version", "--format", "{{.Server.Version}}"])
        return result.returncode == 0

    def _start_preview_process(
        self,
        handle: PreviewHandle,
        preview_config: dict[str, Any],
        summary: dict[str, Any],
        *,
        image_ref: str | None,
    ) -> dict[str, Any]:
        if not image_ref:
            raise PreviewUnavailableError("Preview image reference is unavailable")
        container_name = f"verified-preview-{handle.scope}-{handle.runtime_id}"
        command = str(preview_config["start_command_template"]).replace("{PORT}", str(summary["port"]))
        result = self.runner.run(
            [
                self.docker_bin,
                "run",
                "-d",
                "--name",
                container_name,
                "--cpus",
                settings.runtime_session_cpu,
                "--memory",
                settings.runtime_session_memory,
                "--pids-limit",
                "256",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "ALL",
                "--read-only",
                "-p",
                f"{settings.preview_host}:{summary['port']}:{summary['port']}",
                "-e",
                "PYTHONPATH=/workspace",
                "-w",
                "/workspace",
                "-v",
                f"{handle.repo_root}:/workspace",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                image_ref,
                "sh",
                "-lc",
                command,
            ]
        )
        if result.returncode != 0:
            raise PreviewUnavailableError(result.stderr or "docker preview failed to start")
        summary["container_name"] = container_name
        summary["container_id"] = (result.stdout or "").strip()
        summary["image_ref"] = image_ref
        return summary

    def _stop_preview_process(self, handle: PreviewHandle, summary: dict[str, Any]) -> dict[str, Any]:
        container_name = summary.get("container_name")
        if container_name:
            logs = self.runner.run([self.docker_bin, "logs", container_name])
            handle.log_path.parent.mkdir(parents=True, exist_ok=True)
            handle.log_path.write_text(f"{logs.stdout}{logs.stderr}", encoding="utf-8")
            self.runner.run([self.docker_bin, "stop", container_name])
            self.runner.run([self.docker_bin, "rm", container_name])
        return summary

    def _process_terminated(self, summary: dict[str, Any]) -> bool:
        container_name = summary.get("container_name")
        if not container_name:
            return True
        result = self.runner.run([self.docker_bin, "inspect", "-f", "{{.State.Running}}", container_name])
        return result.returncode != 0 or (result.stdout or "").strip().lower() != "true"

    def _has_process_handle(self, summary: dict[str, Any]) -> bool:
        return bool(summary.get("container_name"))

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["docker"] = {
            "binary": self.docker_bin,
            "available": self.docker_available(),
        }
        return status


class AutoPreviewManager(BasePreviewManager):
    backend_name = "auto"

    def __init__(self, preferred: DockerPreviewManager, fallback: FilesystemPreviewManager) -> None:
        super().__init__(preferred.paths)
        self.preferred = preferred
        self.fallback = fallback

    def _active(self) -> BasePreviewManager:
        if self.preferred.docker_available():
            return self.preferred
        if not runtime_filesystem_fallback_allowed():
            raise PreviewUnavailableError("Container preview runtime is unavailable and filesystem fallback is disabled")
        return self.fallback

    def _manager_for_handle(self, handle: PreviewHandle) -> BasePreviewManager:
        preferred_summary = self.preferred.read_summary(handle)
        if preferred_summary.get("status") != "not_started":
            return self.preferred
        fallback_summary = self.fallback.read_summary(handle)
        if fallback_summary.get("status") != "not_started":
            return self.fallback
        return self._active()

    def start(self, handle: PreviewHandle, preview_config: dict[str, Any], *, image_ref: str | None = None) -> dict[str, Any]:
        return self._active().start(handle, preview_config, image_ref=image_ref)

    def stop(self, handle: PreviewHandle) -> dict[str, Any]:
        return self._manager_for_handle(handle).stop(handle)

    def get(self, handle: PreviewHandle) -> dict[str, Any]:
        primary = self.preferred.get(handle)
        if primary.get("status") != "not_started":
            return primary
        return self.fallback.get(handle)

    def touch(self, handle: PreviewHandle) -> dict[str, Any]:
        primary = self.preferred.get(handle)
        if primary.get("status") != "not_started":
            return self.preferred.touch(handle)
        return self.fallback.touch(handle)

    def cleanup_expired_previews(self) -> dict[str, Any]:
        workspace = self.fallback.cleanup_expired_previews()
        docker = self.preferred.cleanup_expired_previews()
        return {
            "backend": self.backend_name,
            "cleaned_previews": workspace.get("cleaned_previews", []) + docker.get("cleaned_previews", []),
            "cleaned_count": workspace.get("cleaned_count", 0) + docker.get("cleaned_count", 0),
        }

    def list_preview_summaries(self, limit: int | None = None) -> list[dict[str, Any]]:
        return super().list_preview_summaries(limit=limit)

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status.update(
            {
                "active_backend": self._active().backend_name,
                "preferred_backend": self.preferred.backend_name,
                "fallback_backend": self.fallback.backend_name,
                "docker": {
                    "binary": self.preferred.docker_bin,
                    "available": self.preferred.docker_available(),
                },
            }
        )
        return status

    def proxy_request(
        self,
        handle: PreviewHandle,
        summary: dict[str, Any],
        *,
        method: str,
        request_path: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        if summary.get("backend") == "docker":
            return self.preferred.proxy_request(
                handle,
                summary,
                method=method,
                request_path=request_path,
                query_string=query_string,
                headers=headers,
                body=body,
            )
        return self.fallback.proxy_request(
            handle,
            summary,
            method=method,
            request_path=request_path,
            query_string=query_string,
            headers=headers,
            body=body,
        )


def build_preview_manager() -> BasePreviewManager:
    docker_bin = settings.runtime_docker_bin
    if docker_bin == "docker" and which(docker_bin) is None:
        desktop_docker = "/Applications/Docker.app/Contents/Resources/bin/docker"
        if Path(desktop_docker).exists():
            docker_bin = desktop_docker

    paths = RuntimePaths(
        root=resolve_runtime_path(settings.runtime_root),
        templates=resolve_runtime_path(settings.runtime_template_root),
    )
    filesystem = FilesystemPreviewManager(paths)
    docker = DockerPreviewManager(paths, docker_bin=docker_bin)
    return AutoPreviewManager(preferred=docker, fallback=filesystem)


preview_manager = build_preview_manager()
