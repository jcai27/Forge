from __future__ import annotations

from collections import Counter
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import which
from typing import Any, Protocol

from fastapi import HTTPException

from app.core.config import resolve_runtime_path, runtime_filesystem_fallback_allowed, settings
from app.services.object_store import object_store

logger = logging.getLogger(__name__)


@dataclass
class RuntimePaths:
    root: Path
    templates: Path

    @property
    def workspaces(self) -> Path:
        return self.root / "workspaces"

    @property
    def submissions(self) -> Path:
        return self.root / "submissions"


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult: ...


class SubprocessRunner:
    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            args=args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class DockerUnavailableError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class BaseRuntimeProvisioner:
    backend_name = "base"
    ignored_tree_entries = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        ".git",
    }

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def ensure_roots(self) -> None:
        for path in [
            self.paths.root,
            self.paths.templates,
            self.paths.workspaces,
            self.paths.submissions,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def resolve_template_path(self, starter_repo_ref: str) -> Path:
        if not starter_repo_ref.startswith("local://"):
            raise HTTPException(status_code=500, detail="Track starter repo is not available in the local runtime")
        template_name = starter_repo_ref.removeprefix("local://")
        template_path = self.paths.templates / template_name
        if not template_path.exists():
            raise HTTPException(status_code=500, detail=f"Missing local starter repo template: {template_name}")
        return template_path

    def workspace_path(self, workspace_id: str) -> Path:
        return self.paths.workspaces / workspace_id

    def workspace_repo_path(self, workspace_id: str) -> Path:
        return self.workspace_path(workspace_id) / "repo"

    def workspace_metadata_dir(self, workspace_id: str) -> Path:
        return self.workspace_path(workspace_id) / "metadata"

    def workspace_metadata_path(self, workspace_id: str) -> Path:
        return self.workspace_metadata_dir(workspace_id) / "workspace.json"

    def workspace_events_path(self, workspace_id: str) -> Path:
        return self.workspace_metadata_dir(workspace_id) / "events.jsonl"

    def workspace_logs_dir(self, workspace_id: str) -> Path:
        return self.workspace_path(workspace_id) / "logs"

    def workspace_checkpoints_dir(self, workspace_id: str) -> Path:
        return self.workspace_path(workspace_id) / "checkpoints"

    def resolve_workspace_relative_path(self, workspace_id: str, relative_path: str, *, require_exists: bool = True) -> Path:
        repo_root = self.workspace_repo_path(workspace_id).resolve()
        requested = Path(relative_path)
        if requested.is_absolute() or ".." in requested.parts:
            raise HTTPException(status_code=400, detail="Workspace path must stay inside the repo")
        resolved = (repo_root / requested).resolve()
        try:
            resolved.relative_to(repo_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Workspace path must stay inside the repo") from exc
        if require_exists and not resolved.exists():
            raise HTTPException(status_code=404, detail="Workspace path not found")
        return resolved

    def workspace_summary(self, workspace_id: str) -> dict[str, Any] | None:
        metadata_path = self.workspace_metadata_path(workspace_id)
        return self._read_workspace_summary_file(metadata_path)

    def write_workspace_summary(self, workspace_id: str, summary: dict[str, Any]) -> None:
        self.workspace_metadata_path(workspace_id).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def list_workspace_summaries(self, limit: int | None = None) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for metadata_path in self.paths.workspaces.glob("*/metadata/workspace.json"):
            summary = self._read_workspace_summary_file(metadata_path)
            if summary:
                summaries.append(summary)
        summaries.sort(
            key=lambda item: item.get("last_event_at") or item.get("submitted_at") or item.get("created_at") or "",
            reverse=True,
        )
        if limit is not None:
            return summaries[:limit]
        return summaries

    def _read_workspace_summary_file(self, metadata_path: Path) -> dict[str, Any] | None:
        if not metadata_path.exists():
            return None
        try:
            raw = metadata_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Unable to read workspace metadata file: %s", metadata_path, exc_info=True)
            return None
        if not raw.strip():
            logger.warning("Skipping empty workspace metadata file: %s", metadata_path)
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid workspace metadata file: %s", metadata_path, exc_info=True)
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping non-object workspace metadata file: %s", metadata_path)
            return None
        return payload

    def runtime_status(self) -> dict[str, Any]:
        workspaces = self.list_workspace_summaries()
        counts_by_status = dict(Counter(summary.get("status", "unknown") for summary in workspaces))
        counts_by_backend = dict(Counter(summary.get("backend", "unknown") for summary in workspaces))
        return {
            "configured_backend": settings.runtime_backend,
            "active_backend": self.backend_name,
            "paths": {
                "root": str(self.paths.root),
                "templates": str(self.paths.templates),
            },
            "limits": {
                "cpu": settings.runtime_session_cpu,
                "memory": settings.runtime_session_memory,
                "timeout_seconds": settings.runtime_session_timeout_seconds,
            },
            "workspace_counts": {
                "total": len(workspaces),
                "by_status": counts_by_status,
                "by_backend": counts_by_backend,
            },
        }

    def list_workspace_files(self, workspace_id: str) -> list[dict[str, Any]]:
        repo_root = self.workspace_repo_path(workspace_id)
        if not repo_root.exists():
            raise HTTPException(status_code=404, detail="Workspace not provisioned")
        items: list[dict[str, Any]] = []
        for path in sorted(repo_root.rglob("*")):
            relative = path.relative_to(repo_root)
            if any(part in self.ignored_tree_entries for part in relative.parts):
                continue
            items.append(
                {
                    "path": str(relative),
                    "name": path.name,
                    "type": "directory" if path.is_dir() else "file",
                    "size": path.stat().st_size if path.is_file() else None,
                }
            )
        return items

    def read_workspace_file(self, workspace_id: str, path: str) -> dict[str, Any]:
        target = self.resolve_workspace_relative_path(workspace_id, path)
        if target.is_dir():
            raise HTTPException(status_code=400, detail="Cannot read a directory as a file")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Only UTF-8 text files are supported in the browser workspace") from exc
        return {
            "path": path,
            "content": content,
            "size": target.stat().st_size,
            "updated_at": datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat(),
        }

    def write_workspace_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        target = self.resolve_workspace_relative_path(workspace_id, path, require_exists=False)
        if expected_updated_at and target.exists():
            current_updated_at = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat()
            if current_updated_at != expected_updated_at:
                raise HTTPException(status_code=409, detail="Workspace file changed since it was last loaded")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        summary = self.workspace_summary(workspace_id) or {}
        summary["last_file_write_at"] = utcnow().isoformat()
        summary["last_file_path"] = path
        self.write_workspace_summary(workspace_id, summary)
        return {
            "path": path,
            "size": target.stat().st_size,
            "updated_at": datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat(),
        }

    def delete_workspace_file(self, workspace_id: str, path: str) -> None:
        target = self.resolve_workspace_relative_path(workspace_id, path, require_exists=True)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def rename_workspace_file(self, workspace_id: str, old_path: str, new_path: str) -> dict[str, Any]:
        source = self.resolve_workspace_relative_path(workspace_id, old_path, require_exists=True)
        target = self.resolve_workspace_relative_path(workspace_id, new_path, require_exists=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        summary = self.workspace_summary(workspace_id) or {}
        summary["last_file_write_at"] = utcnow().isoformat()
        summary["last_file_path"] = new_path
        self.write_workspace_summary(workspace_id, summary)
        return {
            "path": new_path,
            "size": target.stat().st_size if target.is_file() else None,
            "updated_at": datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat(),
        }

    def search_workspace(self, workspace_id: str, query: str) -> list[dict[str, Any]]:
        repo_root = self.workspace_repo_path(workspace_id)
        if not repo_root.exists():
            raise HTTPException(status_code=404, detail="Workspace not provisioned")
        
        results = []
        try:
            compiled = re.compile(query, re.IGNORECASE)
            for path in sorted(repo_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(repo_root)
                if any(part in self.ignored_tree_entries for part in relative.parts):
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if compiled.search(line):
                            results.append({
                                "path": str(relative),
                                "line_number": i + 1,
                                "line_content": line.strip()
                            })
                except UnicodeDecodeError:
                    pass
        except re.error:
            raise HTTPException(status_code=400, detail="Invalid search regex")
        return results

    def execute_workspace_command(self, workspace_id: str, command: str) -> dict[str, Any] | None:
        return self.handle_terminal_command(workspace_id=workspace_id, command=command)

    def prepare_workspace(self, *, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str) -> tuple[Path, dict[str, Any]]:
        self.ensure_roots()
        template_path = self.resolve_template_path(starter_repo_ref)
        workspace_path = self.workspace_path(workspace_id)
        repo_path = self.workspace_repo_path(workspace_id)
        metadata_dir = self.workspace_metadata_dir(workspace_id)
        logs_dir = self.workspace_logs_dir(workspace_id)
        checkpoints_dir = self.workspace_checkpoints_dir(workspace_id)

        if workspace_path.exists():
            shutil.rmtree(workspace_path)

        shutil.copytree(template_path, repo_path)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_events_path(workspace_id).write_text("", encoding="utf-8")

        seeded_files = [str(path.relative_to(repo_path)) for path in repo_path.rglob("*") if path.is_file()]
        summary = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "track_id": track_id,
            "backend": self.backend_name,
            "status": "provisioned",
            "repo_root": str(repo_path),
            "seeded_file_count": len(seeded_files),
            "seeded_files": seeded_files,
            "container_image_ref": container_image_ref,
            "created_at": utcnow().isoformat(),
        }
        self.write_workspace_summary(workspace_id, summary)
        return repo_path, summary

    def append_event(self, *, workspace_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_roots()
        workspace_path = self.workspace_path(workspace_id)
        if not workspace_path.exists():
            raise HTTPException(status_code=404, detail="Workspace not provisioned")

        event_record = {
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
        }

        command_result = None
        if event_type == "terminal_command":
            command = payload.get("command", "")
            command_result = self.handle_terminal_command(workspace_id=workspace_id, command=command)
            with (self.workspace_logs_dir(workspace_id) / "commands.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{occurred_at.isoformat()} {command}\n")
                if command_result:
                    handle.write(f"exit={command_result['returncode']}\n")

        test_result = None
        if event_type == "test_run":
            test_result = self.handle_test_run(workspace_id=workspace_id, payload=payload)
            with (self.workspace_logs_dir(workspace_id) / "tests.log").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": occurred_at.isoformat(), **payload, "runtime_result": test_result}) + "\n")

        if command_result:
            event_record["payload"]["command_result"] = command_result
        if test_result:
            event_record["payload"]["runtime_result"] = test_result

        with self.workspace_events_path(workspace_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_record) + "\n")
        checkpoint_summary = None
        if event_type == "checkpoint":
            checkpoint_summary = self.create_checkpoint(workspace_id=workspace_id, label=payload.get("label", "checkpoint"))

        metadata = self.workspace_summary(workspace_id) or {}
        metadata["last_event_at"] = occurred_at.isoformat()
        if checkpoint_summary:
            metadata["last_checkpoint"] = checkpoint_summary
            metadata["checkpoint_count"] = metadata.get("checkpoint_count", 0) + 1
        self.write_workspace_summary(workspace_id, metadata)
        return {
            "event_log_path": str(self.workspace_events_path(workspace_id)),
            "checkpoint": checkpoint_summary,
            "command_result": command_result,
            "test_result": test_result,
        }

    def handle_terminal_command(self, *, workspace_id: str, command: str) -> dict[str, Any] | None:
        return None

    def handle_test_run(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        command = payload.get("command")
        if not command:
            return None
        return self.handle_terminal_command(workspace_id=workspace_id, command=command)

    def create_checkpoint(self, *, workspace_id: str, label: str) -> dict[str, Any]:
        timestamp = utcnow().strftime("%Y%m%d%H%M%S")
        checkpoint_id = f"{label.lower().replace(' ', '_')}_{timestamp}"
        target = self.workspace_checkpoints_dir(workspace_id) / checkpoint_id
        source_repo = self.workspace_repo_path(workspace_id)
        shutil.copytree(source_repo, target / "repo")
        manifest = {
            "checkpoint_id": checkpoint_id,
            "label": label,
            "created_at": utcnow().isoformat(),
            "repo_root": str(target / "repo"),
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def list_checkpoints(self, workspace_id: str) -> list[dict[str, Any]]:
        target = self.workspace_checkpoints_dir(workspace_id)
        if not target.exists():
            return []
        results = []
        for path in target.glob("*/manifest.json"):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def restore_checkpoint(self, workspace_id: str, checkpoint_id: str) -> None:
        target = self.workspace_checkpoints_dir(workspace_id) / checkpoint_id
        if not target.exists():
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        source_repo = target / "repo"
        if not source_repo.exists():
            raise HTTPException(status_code=404, detail="Checkpoint repo not found")
            
        repo_path = self.workspace_repo_path(workspace_id)
        if repo_path.exists():
            shutil.rmtree(repo_path)
        shutil.copytree(source_repo, repo_path)
        
        summary = self.workspace_summary(workspace_id) or {}
        summary["last_restored_checkpoint_id"] = checkpoint_id
        summary["last_restored_at"] = utcnow().isoformat()
        self.write_workspace_summary(workspace_id, summary)

    def finalize_workspace(self, *, workspace_id: str, submission_id: str) -> dict[str, Any]:
        return {}

    def cleanup_expired_workspaces(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "cleaned_workspaces": [], "cleaned_count": 0}

    def create_submission_artifact(self, *, submission_id: str, workspace_id: str, immutable_snapshot: dict[str, Any]) -> dict[str, Any]:
        self.ensure_roots()
        object_store.ensure_root()
        workspace_path = self.workspace_path(workspace_id)
        if not workspace_path.exists():
            raise HTTPException(status_code=404, detail="Workspace not provisioned")

        finalization = self.finalize_workspace(workspace_id=workspace_id, submission_id=submission_id)

        submission_dir = self.paths.submissions / submission_id
        if submission_dir.exists():
            shutil.rmtree(submission_dir)
        submission_dir.mkdir(parents=True, exist_ok=True)

        repo_source = self.workspace_repo_path(workspace_id)
        repo_target = submission_dir / "repo"
        shutil.copytree(repo_source, repo_target)

        events_target = submission_dir / "events.jsonl"
        shutil.copy2(self.workspace_events_path(workspace_id), events_target)

        checkpoints_source = self.workspace_checkpoints_dir(workspace_id)
        if checkpoints_source.exists():
            shutil.copytree(checkpoints_source, submission_dir / "checkpoints")

        logs_dir = self.workspace_logs_dir(workspace_id)
        workspace_build_log = logs_dir / "build.log"
        if not workspace_build_log.exists():
            workspace_build_log.write_text("Runtime log not captured.\n", encoding="utf-8")
        workspace_test_log = logs_dir / "tests.log"
        if not workspace_test_log.exists():
            workspace_test_log.write_text("Runtime log not captured.\n", encoding="utf-8")
        build_log_path = submission_dir / "build.log"
        test_log_path = submission_dir / "tests.log"
        shutil.copy2(workspace_build_log, build_log_path)
        shutil.copy2(workspace_test_log, test_log_path)

        workspace_summary = self.workspace_summary(workspace_id) or {}
        snapshot_manifest = {
            "workspace_id": workspace_id,
            "artifact_created_at": utcnow().isoformat(),
            "repo_root": str(repo_target),
            "file_count": sum(1 for path in repo_target.rglob("*") if path.is_file()),
            "workspace_summary": workspace_summary,
            "runtime_finalization": finalization,
            "provided_snapshot": immutable_snapshot,
        }
        manifest_path = submission_dir / "manifest.json"
        manifest_path.write_text(json.dumps(snapshot_manifest, indent=2), encoding="utf-8")

        artifact_uri, artifact_sha = object_store.copy_tree(repo_target, f"submissions/{submission_id}/repo")
        build_log_uri = object_store.copy_file(build_log_path, f"submissions/{submission_id}/build.log")
        test_log_uri = object_store.copy_file(test_log_path, f"submissions/{submission_id}/tests.log")
        manifest_uri = object_store.copy_file(manifest_path, f"submissions/{submission_id}/manifest.json")
        events_uri = object_store.copy_file(events_target, f"submissions/{submission_id}/events.jsonl")
        checkpoints_uri = None
        if (submission_dir / "checkpoints").exists():
            checkpoints_uri, _ = object_store.copy_tree(submission_dir / "checkpoints", f"submissions/{submission_id}/checkpoints")

        snapshot_manifest["evidence_uris"] = {
            "manifest": manifest_uri,
            "events": events_uri,
            "checkpoints": checkpoints_uri,
            "build_log": build_log_uri,
            "test_log": test_log_uri,
            "artifact": artifact_uri,
        }
        manifest_path.write_text(json.dumps(snapshot_manifest, indent=2), encoding="utf-8")
        manifest_uri = object_store.copy_file(manifest_path, f"submissions/{submission_id}/manifest.json")

        return {
            "artifact_uri": artifact_uri,
            "artifact_sha": artifact_sha,
            "build_log_uri": build_log_uri,
            "test_log_uri": test_log_uri,
            "artifact_manifest_uri": manifest_uri,
            "immutable_snapshot": snapshot_manifest,
        }

    def hash_directory(self, root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()


class FilesystemRuntimeProvisioner(BaseRuntimeProvisioner):
    backend_name = "filesystem"

    def __init__(self, paths: RuntimePaths, runner: CommandRunner | None = None) -> None:
        super().__init__(paths)
        self.runner = runner or SubprocessRunner()

    def provision_workspace(self, *, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str) -> dict[str, Any]:
        _, summary = self.prepare_workspace(
            session_id=session_id,
            workspace_id=workspace_id,
            track_id=track_id,
            starter_repo_ref=starter_repo_ref,
            container_image_ref=container_image_ref,
        )
        return summary

    def handle_terminal_command(self, *, workspace_id: str, command: str) -> dict[str, Any] | None:
        if not command:
            return None
        repo_path = self.workspace_repo_path(workspace_id)
        result = self.runner.run(["sh", "-lc", f"PYTHONPATH=. {command}"], cwd=repo_path)
        build_log_path = self.workspace_logs_dir(workspace_id) / "build.log"
        with build_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {command}\n")
            if result.stdout:
                handle.write(result.stdout)
            if result.stderr:
                handle.write(result.stderr)
            handle.write(f"\nexit={result.returncode}\n")
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }


class DockerRuntimeProvisioner(BaseRuntimeProvisioner):
    backend_name = "docker"

    def __init__(self, paths: RuntimePaths, docker_bin: str, runner: CommandRunner | None = None) -> None:
        super().__init__(paths)
        self.docker_bin = docker_bin
        self.runner = runner or SubprocessRunner()

    def _run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        result = self.runner.run(args, cwd=cwd)
        if result.returncode != 0:
            raise DockerUnavailableError(result.stderr or result.stdout or "docker command failed")
        return result

    def docker_available(self) -> bool:
        if not self.docker_bin or which(self.docker_bin) is None:
            return False
        try:
            self._run([self.docker_bin, "version", "--format", "{{.Server.Version}}"])
            return True
        except DockerUnavailableError:
            return False

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["docker"] = {
            "binary": self.docker_bin,
            "available": self.docker_available(),
        }
        return status

    def resolve_image_build_context(self, template_path: Path) -> Path | None:
        dockerfile = template_path / "Dockerfile.runtime"
        return template_path if dockerfile.exists() else None

    def ensure_image(self, *, image_ref: str, template_path: Path) -> dict[str, Any]:
        try:
            inspect = self.runner.run([self.docker_bin, "image", "inspect", image_ref])
            if inspect.returncode == 0:
                return {"image_ref": image_ref, "image_status": "present"}
        except Exception as exc:  # pragma: no cover - defensive
            raise DockerUnavailableError(str(exc)) from exc

        build_context = self.resolve_image_build_context(template_path)
        if build_context is None:
            raise DockerUnavailableError(f"Docker image {image_ref} is not available and no Dockerfile.runtime was found")

        build_result = self.runner.run(
            [
                self.docker_bin,
                "build",
                "-t",
                image_ref,
                "-f",
                str(build_context / "Dockerfile.runtime"),
                str(build_context),
            ]
        )
        if build_result.returncode != 0:
            raise DockerUnavailableError(build_result.stderr or "docker build failed")
        return {"image_ref": image_ref, "image_status": "built"}

    def provision_workspace(self, *, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str) -> dict[str, Any]:
        template_path = self.resolve_template_path(starter_repo_ref)
        _, summary = self.prepare_workspace(
            session_id=session_id,
            workspace_id=workspace_id,
            track_id=track_id,
            starter_repo_ref=starter_repo_ref,
            container_image_ref=container_image_ref,
        )
        image_info = self.ensure_image(image_ref=container_image_ref, template_path=template_path)
        repo_path = self.workspace_repo_path(workspace_id)
        container_name = f"verified-ws-{workspace_id}"
        run_result = self.runner.run(
            [
                self.docker_bin,
                "run",
                "-d",
                "--name",
                container_name,
                "--network",
                "none",
                "--cpus",
                settings.runtime_session_cpu,
                "--memory",
                settings.runtime_session_memory,
                "--pids-limit",
                "256",
                "--security-opt",
                "no-new-privileges",
                "-e",
                "PYTHONPATH=/workspace",
                "-w",
                "/workspace",
                "-v",
                f"{repo_path}:/workspace",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                container_image_ref,
                "sleep",
                "infinity",
            ]
        )
        if run_result.returncode != 0:
            raise DockerUnavailableError(run_result.stderr or "docker run failed")

        summary.update(
            {
                **image_info,
                "container_name": container_name,
                "container_id": (run_result.stdout or "").strip(),
                "status": "running",
                "network_policy": "none",
                "cpu_limit": settings.runtime_session_cpu,
                "memory_limit": settings.runtime_session_memory,
                "timeout_seconds": settings.runtime_session_timeout_seconds,
                "expires_at": (utcnow()).timestamp() + settings.runtime_session_timeout_seconds,
            }
        )
        self.write_workspace_summary(workspace_id, summary)
        return summary

    def handle_terminal_command(self, *, workspace_id: str, command: str) -> dict[str, Any] | None:
        if not command:
            return None
        summary = self.workspace_summary(workspace_id) or {}
        container_name = summary.get("container_name")
        if not container_name:
            return None
        result = self.runner.run(
            [self.docker_bin, "exec", container_name, "sh", "-lc", command]
        )
        build_log_path = self.workspace_logs_dir(workspace_id) / "build.log"
        with build_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {command}\n")
            if result.stdout:
                handle.write(result.stdout)
            if result.stderr:
                handle.write(result.stderr)
            handle.write(f"\nexit={result.returncode}\n")
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def handle_test_run(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        command = payload.get("command") or "pytest -q"
        command_result = self.handle_terminal_command(workspace_id=workspace_id, command=command)
        if not command_result:
            return None
        parsed = self.parse_pytest_output(command_result["stdout"], command_result["stderr"])
        return {
            **command_result,
            **parsed,
        }

    def parse_pytest_output(self, stdout: str, stderr: str) -> dict[str, Any]:
        combined = f"{stdout}\n{stderr}"
        passed = 0
        failed = 0
        match = re.search(r"(\d+) failed, (\d+) passed|(\d+) passed, (\d+) failed", combined)
        if match:
            if match.group(1) and match.group(2):
                failed = int(match.group(1))
                passed = int(match.group(2))
            else:
                passed = int(match.group(3))
                failed = int(match.group(4))
        else:
            passed_match = re.search(r"(\d+) passed", combined)
            failed_match = re.search(r"(\d+) failed", combined)
            if passed_match:
                passed = int(passed_match.group(1))
            if failed_match:
                failed = int(failed_match.group(1))
        total = passed + failed
        return {
            "passed_tests": passed,
            "total_tests": total,
            "build_success": failed == 0 and total > 0 and "not found" not in combined.lower(),
        }

    def finalize_workspace(self, *, workspace_id: str, submission_id: str) -> dict[str, Any]:
        summary = self.workspace_summary(workspace_id) or {}
        container_name = summary.get("container_name")
        results: dict[str, Any] = {
            "backend": self.backend_name,
            "submission_id": submission_id,
        }
        if not container_name:
            return results

        stop_result = self.runner.run([self.docker_bin, "stop", container_name])
        rm_result = self.runner.run([self.docker_bin, "rm", container_name])
        summary["status"] = "stopped" if stop_result.returncode == 0 else "stop_failed"
        summary["submitted_at"] = utcnow().isoformat()
        self.write_workspace_summary(workspace_id, summary)
        results.update(
            {
                "container_name": container_name,
                "stop_returncode": stop_result.returncode,
                "rm_returncode": rm_result.returncode,
            }
        )
        return results

    def cleanup_expired_workspaces(self) -> dict[str, Any]:
        cleaned: list[str] = []
        for metadata_path in self.paths.workspaces.glob("*/metadata/workspace.json"):
            summary = self._read_workspace_summary_file(metadata_path)
            if not summary:
                continue
            if summary.get("backend") != self.backend_name:
                continue
            expires_at = summary.get("expires_at")
            container_name = summary.get("container_name")
            if expires_at is None or not container_name:
                continue
            if utcnow().timestamp() < float(expires_at):
                continue
            self.runner.run([self.docker_bin, "stop", container_name])
            self.runner.run([self.docker_bin, "rm", container_name])
            summary["status"] = "expired"
            summary["expired_at"] = utcnow().isoformat()
            metadata_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            cleaned.append(summary["workspace_id"])
        return {"backend": self.backend_name, "cleaned_workspaces": cleaned, "cleaned_count": len(cleaned)}


class AutoRuntimeProvisioner(BaseRuntimeProvisioner):
    backend_name = "auto"

    def __init__(self, preferred: DockerRuntimeProvisioner, fallback: FilesystemRuntimeProvisioner) -> None:
        super().__init__(preferred.paths)
        self.preferred = preferred
        self.fallback = fallback

    def _active(self) -> BaseRuntimeProvisioner:
        if self.preferred.docker_available():
            return self.preferred
        if not runtime_filesystem_fallback_allowed():
            raise DockerUnavailableError("Container runtime is unavailable and filesystem fallback is disabled")
        return self.fallback

    def provision_workspace(self, *, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str) -> dict[str, Any]:
        return self._active().provision_workspace(
            session_id=session_id,
            workspace_id=workspace_id,
            track_id=track_id,
            starter_repo_ref=starter_repo_ref,
            container_image_ref=container_image_ref,
        )

    def append_event(self, *, workspace_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]) -> dict[str, Any]:
        return self._active().append_event(
            workspace_id=workspace_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
        )

    def handle_terminal_command(self, *, workspace_id: str, command: str) -> dict[str, Any] | None:
        return self._active().handle_terminal_command(workspace_id=workspace_id, command=command)

    def handle_test_run(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._active().handle_test_run(workspace_id=workspace_id, payload=payload)

    def create_checkpoint(self, *, workspace_id: str, label: str) -> dict[str, Any]:
        return self._active().create_checkpoint(workspace_id=workspace_id, label=label)

    def create_submission_artifact(self, *, submission_id: str, workspace_id: str, immutable_snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._active().create_submission_artifact(
            submission_id=submission_id,
            workspace_id=workspace_id,
            immutable_snapshot=immutable_snapshot,
        )

    def cleanup_expired_workspaces(self) -> dict[str, Any]:
        return self._active().cleanup_expired_workspaces()

    def workspace_summary(self, workspace_id: str) -> dict[str, Any] | None:
        summary = self.preferred.workspace_summary(workspace_id)
        if summary:
            return summary
        return self.fallback.workspace_summary(workspace_id)

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        docker_available = self.preferred.docker_available()
        status.update(
            {
                "active_backend": self._active().backend_name,
                "preferred_backend": self.preferred.backend_name,
                "fallback_backend": self.fallback.backend_name,
                "docker": {
                    "binary": self.preferred.docker_bin,
                    "available": docker_available,
                },
            }
        )
        return status


def build_runtime_provisioner() -> BaseRuntimeProvisioner:
    docker_bin = settings.runtime_docker_bin
    if docker_bin == "docker" and which(docker_bin) is None:
        desktop_docker = "/Applications/Docker.app/Contents/Resources/bin/docker"
        if Path(desktop_docker).exists():
            docker_bin = desktop_docker

    paths = RuntimePaths(
        root=resolve_runtime_path(settings.runtime_root),
        templates=resolve_runtime_path(settings.runtime_template_root),
    )
    filesystem = FilesystemRuntimeProvisioner(paths)
    docker = DockerRuntimeProvisioner(paths, docker_bin=docker_bin)

    if settings.runtime_backend == "filesystem":
        return filesystem
    if settings.runtime_backend == "docker":
        return docker
    return AutoRuntimeProvisioner(preferred=docker, fallback=filesystem)


runtime_provisioner = build_runtime_provisioner()
