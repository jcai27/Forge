import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote, quote_plus, unquote, urlsplit

import jwt
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from factory.config import settings
from factory.db import get_db, now
from factory.models import AuditEvent, Connection, DeploymentTrigger, Membership, SecretRedactionEntry, User

passwords = PasswordHasher()
bearer = HTTPBearer()


@dataclass
class Principal:
    user_id: str
    org_id: str
    role: str


def token_for(user_id, org_id):
    return jwt.encode(
        {"sub": user_id, "org": org_id, "exp": now() + timedelta(hours=8)}, settings().jwt_secret, algorithm="HS256"
    )


def principal(credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(get_db)):
    try:
        claims = jwt.decode(credentials.credentials, settings().jwt_secret, algorithms=["HS256"])
        member = db.scalar(
            select(Membership).where(Membership.user_id == claims["sub"], Membership.org_id == claims["org"])
        )
        if not member or not db.get(User, member.user_id):
            raise ValueError("Membership revoked")
        return Principal(member.user_id, member.org_id, member.role)
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired authentication") from None


def require_write(actor):
    if actor.role not in ("admin", "editor"):
        raise HTTPException(403, "Editor role required")


def require_admin(actor):
    if actor.role != "admin":
        raise HTTPException(403, "Administrator role required")


def owned(db, cls, resource_id, actor):
    item = db.get(cls, resource_id)
    if item is None or item.org_id != actor.org_id:
        raise HTTPException(404, "Resource not found")
    return item


def cipher():
    key = settings().encryption_key
    if not key:
        import base64

        key = base64.urlsafe_b64encode(hashlib.sha256(settings().jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else ""


def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value else ""


SECRET_KEYS = re.compile(
    r"(password|secret|authorization|api.?key|access.?token|refresh.?token|credential)", re.IGNORECASE
)


def secret_variants(secret):
    """Known plaintext and common transport encodings, never persisted or logged."""
    return (
        {
            secret,
            quote(secret, safe=""),
            quote_plus(secret),
            base64.b64encode(secret.encode()).decode(),
            json.dumps(secret, ensure_ascii=True)[1:-1],
        }
        if secret
        else set()
    )


def credential_values(secret):
    values = {secret} if secret else set()
    try:
        parsed = json.loads(secret)

        def collect(item):
            if isinstance(item, dict):
                for key, value in item.items():
                    if re.search(r"password|secret|token|key|credential|dsn", key, re.I) and isinstance(value, str):
                        values.add(value)
                    collect(value)
                if isinstance(item.get("username"), str) and isinstance(item.get("password"), str):
                    values.add(item["username"] + ":" + item["password"])
            elif isinstance(item, list):
                for value in item:
                    collect(value)

        collect(parsed)
    except (ValueError, TypeError):
        pass
    try:
        parsed_url = urlsplit(secret)
        if parsed_url.password:
            password = unquote(parsed_url.password)
            values.add(password)
            if parsed_url.username:
                values.add(unquote(parsed_url.username) + ":" + password)
    except ValueError:
        pass
    return {variant for value in values if value for variant in secret_variants(value)}


def known_secret_values(db, org_id):
    values = set()
    for cls in (Connection, DeploymentTrigger, SecretRedactionEntry):
        for encrypted in db.scalars(select(cls.encrypted_secret).where(cls.org_id == org_id)):
            if encrypted:
                values.update(credential_values(decrypt(encrypted)))
                values.add(encrypted)
    return values


def redact(value, secret_values=()):
    cfg = settings()
    values = set(secret_values)
    for secret in (cfg.openai_api_key, cfg.jwt_secret, cfg.encryption_key):
        values.update(secret_variants(secret))
    pattern = re.compile("|".join(re.escape(s) for s in sorted(values, key=len, reverse=True))) if values else None
    return _redact(value, pattern)


def _redact(value, pattern):
    if isinstance(value, dict):
        return {
            _redact(k, pattern): "[REDACTED]" if SECRET_KEYS.search(k) else _redact(v, pattern)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v, pattern) for v in value]
    if isinstance(value, str):
        if pattern:
            value = pattern.sub("[REDACTED]", value)
        value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
        return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def redact_tenant(db, org_id, value):
    return redact(value, known_secret_values(db, org_id))


def audit(db, actor, action, resource_id, detail=None):
    db.add(
        AuditEvent(
            org_id=actor.org_id,
            actor_id=actor.user_id,
            action=action,
            resource_id=resource_id,
            detail=redact_tenant(db, actor.org_id, detail or {}),
        )
    )
