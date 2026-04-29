from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AssessmentAttempt,
    Credential,
    EmailVerificationToken,
    LoginSession,
    MfaEnrollment,
    PasswordResetToken,
    User,
    UserType,
)
from app.services.runtime_control import log_audit_event


def utcnow() -> datetime:
    return datetime.now(UTC)


def _comparable_now(value: datetime) -> datetime:
    now = utcnow()
    return now.replace(tzinfo=None) if value.tzinfo is None else now


def _hash_with_secret(value: str, *, secret: str) -> str:
    return hashlib.sha256(f"{value}:{secret}".encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return _hash_with_secret(token, secret=settings.auth_signed_token_key)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        f"{password}{settings.auth_password_pepper}".encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )
    return f"scrypt${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = encoded_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    padding = "=" * (-len(salt_b64) % 4)
    salt = base64.urlsafe_b64decode(f"{salt_b64}{padding}")
    expected = base64.urlsafe_b64decode(f"{digest_b64}{'=' * (-len(digest_b64) % 4)}")
    actual = hashlib.scrypt(
        f"{password}{settings.auth_password_pepper}".encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )
    return hmac.compare_digest(actual, expected)


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def generate_recovery_codes() -> list[str]:
    return [secrets.token_hex(4) for _ in range(8)]


def hash_recovery_code(code: str) -> str:
    return _hash_with_secret(code, secret=settings.auth_signed_token_key)


def _decode_base32_secret(secret: str) -> bytes:
    padded = secret + "=" * (-len(secret) % 8)
    return base64.b32decode(padded, casefold=True)


def _totp_code(secret: str, counter: int) -> str:
    key = _decode_base32_secret(secret)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    chunk = digest[offset : offset + 4]
    code_int = struct.unpack(">I", chunk)[0] & 0x7FFFFFFF
    return str(code_int % 1_000_000).zfill(6)


def verify_totp_code(secret: str, code: str, *, now: int | None = None, drift_steps: int = 1) -> bool:
    timestamp = int(now or time.time())
    timestep = timestamp // 30
    for offset in range(-drift_steps, drift_steps + 1):
        if hmac.compare_digest(_totp_code(secret, timestep + offset), code.strip()):
            return True
    return False


def totp_provisioning_uri(*, email: str, secret: str) -> str:
    issuer = quote("Forge")
    label = quote(f"Forge:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30"


def set_session_cookies(response: Response, *, session_token: str, csrf_token: str) -> None:
    max_age = settings.auth_session_ttl_seconds
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key=settings.auth_csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=max_age,
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth_session_cookie_name, path="/")
    response.delete_cookie(settings.auth_csrf_cookie_name, path="/")


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def get_credential_for_user(db: Session, user_id: str) -> Credential | None:
    return db.query(Credential).filter(Credential.user_id == user_id).first()


def ensure_password_credential(db: Session, *, user_id: str, password: str, must_change_password: bool = False) -> Credential:
    credential = get_credential_for_user(db, user_id)
    if not credential:
        credential = Credential(id=f"cred_{uuid4().hex[:12]}", user_id=user_id)
        db.add(credential)
    credential.password_hash = hash_password(password)
    credential.password_version = (credential.password_version or 0) + 1
    credential.must_change_password = must_change_password
    credential.password_set_at = utcnow()
    db.add(credential)
    return credential


def authenticate_password_login(db: Session, *, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    credential = get_credential_for_user(db, user.id)
    if not credential or not verify_password(password, credential.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return user


def create_login_session(
    db: Session,
    *,
    user: User,
    request: Request | None,
    mfa_verified: bool = False,
) -> tuple[LoginSession, str]:
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    login_session = LoginSession(
        id=f"ls_{uuid4().hex[:12]}",
        user_id=user.id,
        session_token_hash=hash_token(raw_token),
        csrf_token=csrf_token,
        expires_at=utcnow() + timedelta(seconds=settings.auth_session_ttl_seconds),
        last_seen_at=utcnow(),
        mfa_verified_at=utcnow() if mfa_verified else None,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(login_session)
    return login_session, raw_token


def get_login_session_from_cookie(db: Session, session_token: str | None) -> LoginSession | None:
    if not session_token:
        return None
    session_hash = hash_token(session_token)
    login_session = (
        db.query(LoginSession)
        .filter(LoginSession.session_token_hash == session_hash, LoginSession.revoked_at.is_(None))
        .first()
    )
    if not login_session:
        return None
    if login_session.expires_at < _comparable_now(login_session.expires_at):
        login_session.revoked_at = utcnow()
        db.add(login_session)
        db.commit()
        return None
    return login_session


def touch_login_session(db: Session, login_session: LoginSession) -> LoginSession:
    login_session.last_seen_at = utcnow()
    db.add(login_session)
    db.commit()
    db.refresh(login_session)
    return login_session


def revoke_login_session(db: Session, login_session: LoginSession) -> LoginSession:
    login_session.revoked_at = utcnow()
    db.add(login_session)
    db.commit()
    db.refresh(login_session)
    return login_session


def require_csrf(request: Request, login_session: LoginSession) -> None:
    provided = request.headers.get("x-csrf-token", "")
    if not provided or not hmac.compare_digest(provided, login_session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")


def user_requires_mfa(user: User) -> bool:
    return settings.auth_internal_mfa_required and user.user_type in {UserType.admin.value, UserType.employer.value}


def get_active_mfa_enrollment(db: Session, user_id: str) -> MfaEnrollment | None:
    return (
        db.query(MfaEnrollment)
        .filter(MfaEnrollment.user_id == user_id, MfaEnrollment.disabled_at.is_(None))
        .first()
    )


def enroll_mfa(db: Session, *, user: User) -> MfaEnrollment:
    enrollment = get_active_mfa_enrollment(db, user.id)
    if not enrollment:
        enrollment = MfaEnrollment(id=f"mfa_{uuid4().hex[:12]}", user_id=user.id)
        db.add(enrollment)
    recovery_codes = generate_recovery_codes()
    enrollment.totp_secret = generate_totp_secret()
    enrollment.recovery_codes_json = [hash_recovery_code(code) for code in recovery_codes]
    enrollment.verified_at = None
    enrollment.disabled_at = None
    db.add(enrollment)
    db.flush()
    enrollment._plain_recovery_codes = recovery_codes  # type: ignore[attr-defined]
    return enrollment


def verify_mfa_enrollment(db: Session, *, enrollment: MfaEnrollment, code: str) -> bool:
    if verify_totp_code(enrollment.totp_secret, code):
        enrollment.verified_at = utcnow()
        db.add(enrollment)
        return True
    hashed = hash_recovery_code(code.strip())
    if hashed in (enrollment.recovery_codes_json or []):
        enrollment.recovery_codes_json = [item for item in (enrollment.recovery_codes_json or []) if item != hashed]
        enrollment.verified_at = utcnow()
        db.add(enrollment)
        return True
    return False


def issue_password_reset_token(db: Session, *, user: User) -> str:
    raw_token = secrets.token_urlsafe(32)
    token = PasswordResetToken(
        id=f"prt_{uuid4().hex[:12]}",
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(seconds=settings.auth_password_reset_ttl_seconds),
    )
    db.add(token)
    return raw_token


def consume_password_reset_token(db: Session, *, raw_token: str, new_password: str) -> User:
    token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_token(raw_token), PasswordResetToken.consumed_at.is_(None))
        .first()
    )
    if not token or token.expires_at < _comparable_now(token.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token is invalid or expired")
    user = db.query(User).filter(User.id == token.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_password_credential(db, user_id=user.id, password=new_password)
    token.consumed_at = utcnow()
    db.add(token)
    return user


def issue_email_token(
    db: Session,
    *,
    email: str,
    purpose: str,
    user_id: str | None = None,
    attempt_id: str | None = None,
    ttl_seconds: int | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token = EmailVerificationToken(
        id=f"evtok_{uuid4().hex[:12]}",
        user_id=user_id,
        attempt_id=attempt_id,
        email=email.lower().strip(),
        purpose=purpose,
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(seconds=ttl_seconds or settings.auth_magic_link_ttl_seconds),
    )
    db.add(token)
    return raw_token


def consume_email_token(db: Session, *, raw_token: str, purpose: str) -> EmailVerificationToken:
    token = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.token_hash == hash_token(raw_token),
            EmailVerificationToken.purpose == purpose,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .first()
    )
    if not token or token.expires_at < _comparable_now(token.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token is invalid or expired")
    token.consumed_at = utcnow()
    db.add(token)
    return token


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "user_type": user.user_type,
        "organization_id": user.organization_id,
        "auth_provider": user.auth_provider,
    }


def serialize_login_session(login_session: LoginSession, user: User, *, db: Session | None = None) -> dict[str, Any]:
    enrollment = get_active_mfa_enrollment(db, user.id) if db is not None else None
    return {
        "id": login_session.id,
        "expires_at": login_session.expires_at.isoformat(),
        "mfa_verified": bool(login_session.mfa_verified_at),
        "mfa_required": user_requires_mfa(user),
        "mfa_enrolled": bool(enrollment and enrollment.verified_at),
        "csrf_token": login_session.csrf_token,
    }


def create_candidate_magic_link(db: Session, *, invite_token: str, email: str) -> tuple[AssessmentAttempt, str]:
    attempt = db.query(AssessmentAttempt).filter(AssessmentAttempt.invite_token == invite_token).first()
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    user = db.query(User).filter(User.id == attempt.user_id).first()
    if not user or user.email.lower() != email.lower().strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    token = issue_email_token(
        db,
        email=user.email,
        purpose="candidate_magic_link",
        user_id=user.id,
        attempt_id=attempt.id,
    )
    log_audit_event(
        db,
        event_type="candidate_magic_link_requested",
        target_type="assessment_attempt",
        target_id=attempt.id,
        actor_id=user.id,
        actor_label="candidate_magic_link",
        payload={"email": user.email},
    )
    return attempt, token
