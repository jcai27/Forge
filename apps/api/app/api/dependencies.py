from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import LoginSession, User, UserType
from app.db.session import get_db
from app.services.auth import (
    get_login_session_from_cookie,
    require_csrf,
    serialize_user,
    touch_login_session,
    utcnow,
    user_requires_mfa,
)


@dataclass
class AuthContext:
    user: User
    login_session: LoginSession

    @property
    def is_admin(self) -> bool:
        return self.user.user_type == UserType.admin.value

    @property
    def is_reviewer(self) -> bool:
        return self.user.user_type in {UserType.admin.value, UserType.employer.value}

    @property
    def is_candidate(self) -> bool:
        return self.user.user_type == UserType.candidate.value

    def as_dict(self) -> dict:
        return {
            "user": serialize_user(self.user),
            "session": {
                "id": self.login_session.id,
                "expires_at": self.login_session.expires_at.isoformat(),
                "mfa_verified": bool(self.login_session.mfa_verified_at),
            },
        }


DEV_AUTH_HEADER = "x-forge-dev-auth"
DEV_AUTH_QUERY_PARAM = "dev_auth_as"
DEV_AUTH_USERS = {
    "candidate": "candidate_demo",
    "reviewer": "admin_reviewer_demo",
    "admin": "admin_reviewer_demo",
}


def is_dev_bypass_context(context: AuthContext) -> bool:
    return bool(getattr(context.login_session, "_dev_bypass", False))


def resolve_dev_auth_role(request: Request) -> str | None:
    if not settings.auth_dev_bypass_enabled:
        return None
    requested_role = (request.headers.get(DEV_AUTH_HEADER) or request.query_params.get(DEV_AUTH_QUERY_PARAM) or "").strip().lower()
    return requested_role or None


def build_dev_auth_context(db: Session, requested_role: str | None) -> AuthContext | None:
    if not requested_role:
        return None
    user_id = DEV_AUTH_USERS.get(requested_role)
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    login_session = LoginSession(
        id=f"dev_bypass_{user.id}",
        user_id=user.id,
        session_token_hash="dev-bypass",
        csrf_token="dev-bypass",
        expires_at=utcnow() + timedelta(days=365),
        last_seen_at=utcnow(),
        mfa_verified_at=utcnow(),
    )
    login_session._dev_bypass = True  # type: ignore[attr-defined]
    return AuthContext(user=user, login_session=login_session)


def _load_auth_context(
    db: Session,
    session_token: str | None,
) -> AuthContext | None:
    login_session = get_login_session_from_cookie(db, session_token)
    if not login_session:
        return None
    user = db.query(User).filter(User.id == login_session.user_id).first()
    if not user:
        return None
    touch_login_session(db, login_session)
    return AuthContext(user=user, login_session=login_session)


def get_optional_auth_context(
    request: Request,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
) -> AuthContext | None:
    context = _load_auth_context(db, session_token)
    if context:
        return context
    return build_dev_auth_context(db, resolve_dev_auth_role(request))


def get_auth_context(
    context: AuthContext | None = Depends(get_optional_auth_context),
) -> AuthContext:
    if not context:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return context


def require_candidate_auth(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not context.is_candidate:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Candidate access required")
    return context


def require_reviewer_auth(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not context.is_reviewer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer access required")
    if not is_dev_bypass_context(context) and user_requires_mfa(context.user) and not context.login_session.mfa_verified_at:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MFA verification required")
    return context


def require_admin_auth(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not context.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if not is_dev_bypass_context(context) and user_requires_mfa(context.user) and not context.login_session.mfa_verified_at:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MFA verification required")
    return context


def require_csrf_protection(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and not is_dev_bypass_context(context):
        require_csrf(request, context.login_session)
    return context


def require_candidate_csrf(
    request: Request,
    context: AuthContext = Depends(require_candidate_auth),
) -> AuthContext:
    if not is_dev_bypass_context(context):
        require_csrf(request, context.login_session)
    return context


def require_reviewer_csrf(
    request: Request,
    context: AuthContext = Depends(require_reviewer_auth),
) -> AuthContext:
    if not is_dev_bypass_context(context):
        require_csrf(request, context.login_session)
    return context


def require_admin_csrf(
    request: Request,
    context: AuthContext = Depends(require_admin_auth),
) -> AuthContext:
    if not is_dev_bypass_context(context):
        require_csrf(request, context.login_session)
    return context
