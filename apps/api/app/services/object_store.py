from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from app.core.config import resolve_runtime_path, settings


class ObjectStore(Protocol):
    def ensure_root(self) -> None: ...

    def uri_for(self, key: str) -> str: ...

    def write_text(self, key: str, content: str) -> str: ...

    def write_json(self, key: str, payload: dict[str, Any]) -> str: ...

    def copy_file(self, source: Path, key: str) -> str: ...

    def copy_tree(self, source: Path, key: str) -> tuple[str, str]: ...


def hash_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, key: str) -> Path:
        normalized = key.strip("/").replace("..", "")
        return self.root / normalized

    def uri_for(self, key: str) -> str:
        return f"object://{key.strip('/')}"

    def write_text(self, key: str, content: str) -> str:
        target = self._target(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self.uri_for(key)

    def write_json(self, key: str, payload: dict[str, Any]) -> str:
        return self.write_text(key, json.dumps(payload, indent=2))

    def copy_file(self, source: Path, key: str) -> str:
        target = self._target(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return self.uri_for(key)

    def copy_tree(self, source: Path, key: str) -> tuple[str, str]:
        target = self._target(key)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        return self.uri_for(key), hash_directory(target)


class S3ObjectStore:
    def __init__(self, *, bucket: str, prefix: str = "", region_name: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region_name = region_name or None

    def _client(self):
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise RuntimeError("boto3 is required for the S3 object store backend") from exc
        return boto3.client("s3", region_name=self.region_name)

    def _full_key(self, key: str) -> str:
        normalized = key.strip("/")
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def ensure_root(self) -> None:
        if not self.bucket:
            raise RuntimeError("OBJECT_STORE_BUCKET must be configured for S3 object storage")

    def uri_for(self, key: str) -> str:
        return f"object://{key.strip('/')}"

    def write_text(self, key: str, content: str) -> str:
        self._client().put_object(Bucket=self.bucket, Key=self._full_key(key), Body=content.encode("utf-8"))
        return self.uri_for(key)

    def write_json(self, key: str, payload: dict[str, Any]) -> str:
        return self.write_text(key, json.dumps(payload, indent=2))

    def copy_file(self, source: Path, key: str) -> str:
        self._client().upload_file(str(source), self.bucket, self._full_key(key))
        return self.uri_for(key)

    def copy_tree(self, source: Path, key: str) -> tuple[str, str]:
        digest = hash_directory(source)
        client = self._client()
        prefix = self._full_key(key)
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            client.upload_file(str(path), self.bucket, f"{prefix}/{relative}")
        return self.uri_for(key), digest


def _build_object_store() -> ObjectStore:
    if settings.object_store_backend == "s3":
        return S3ObjectStore(
            bucket=settings.object_store_bucket,
            prefix=settings.object_store_prefix,
            region_name=settings.aws_region,
        )
    return LocalObjectStore(resolve_runtime_path(settings.object_store_root))


object_store = _build_object_store()
