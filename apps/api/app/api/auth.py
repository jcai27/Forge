from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, get_auth_context, is_dev_bypass_context, require_csrf_protection
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db
from app.schemas import (
    CandidateMagicLinkRedeem,
    CandidateMagicLinkRequest,
    LoginRequest,
    MfaVerifyRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.services.auth import (
    authenticate_password_login,
    clear_session_cookies,
    consume_email_token,
    consume_password_reset_token,
    create_candidate_magic_link,
    create_login_session,
    enroll_mfa,
    get_active_mfa_enrollment,
    get_user_by_email,
    issue_password_reset_token,
    revoke_login_session,
    serialize_login_session,
    serialize_user,
    set_session_cookies,
    totp_provisioning_uri,
    user_requires_mfa,
    verify_mfa_enrollment,
)
from app.services.runtime_control import log_audit_event

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = authenticate_password_login(db, email=payload.email, password=payload.password)
    login_session, raw_token = create_login_session(db, user=user, request=request, mfa_verified=not user_requires_mfa(user))
    log_audit_event(
        db,
        event_type="auth_login",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_label="password_login",
        payload={"email": user.email},
    )
    db.commit()
    db.refresh(login_session)
    set_session_cookies(response, session_token=raw_token, csrf_token=login_session.csrf_token)
    return {"user": serialize_user(user), "session": serialize_login_session(login_session, user, db=db)}


@router.get("/session")
def get_session(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)):
    return {
        "user": serialize_user(context.user),
        "session": serialize_login_session(context.login_session, context.user, db=db),
    }


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_csrf_protection),
):
    if not is_dev_bypass_context(context):
        revoke_login_session(db, context.login_session)
    clear_session_cookies(response)
    return {"ok": True}


@router.post("/password/reset/request")
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, payload.email)
    token = issue_password_reset_token(db, user=user) if user else None
    if user:
        log_audit_event(
            db,
            event_type="password_reset_requested",
            target_type="user",
            target_id=user.id,
            actor_id=user.id,
            actor_label="password_reset",
            payload={"email": user.email},
        )
        db.commit()
    response: dict[str, object] = {"ok": True}
    if token and not settings.is_production:
        response["reset_token"] = token
    return response


@router.post("/password/reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    user = consume_password_reset_token(db, raw_token=payload.token, new_password=payload.new_password)
    log_audit_event(
        db,
        event_type="password_reset_completed",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_label="password_reset",
        payload={},
    )
    db.commit()
    return {"ok": True}


@router.post("/candidate/magic-link/request")
def request_candidate_magic_link(payload: CandidateMagicLinkRequest, db: Session = Depends(get_db)):
    attempt, token = create_candidate_magic_link(db, invite_token=payload.invite_token, email=payload.email)
    db.commit()
    response: dict[str, object] = {"ok": True, "attempt_id": attempt.id}
    if not settings.is_production:
        response["token"] = token
    return response


@router.post("/candidate/magic-link/redeem")
def redeem_candidate_magic_link(
    payload: CandidateMagicLinkRedeem,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = consume_email_token(db, raw_token=payload.token, purpose="candidate_magic_link")
    user = db.query(User).filter(User.id == token.user_id).first() if token.user_id else None
    if not user:
        raise ValueError("Magic-link user not found")
    login_session, raw_token = create_login_session(db, user=user, request=request, mfa_verified=True)
    log_audit_event(
        db,
        event_type="candidate_magic_link_redeemed",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_label="candidate_magic_link",
        payload={"attempt_id": token.attempt_id},
    )
    db.commit()
    db.refresh(login_session)
    set_session_cookies(response, session_token=raw_token, csrf_token=login_session.csrf_token)
    return {"user": serialize_user(user), "session": serialize_login_session(login_session, user, db=db)}


@router.post("/mfa/enroll")
def begin_mfa_enrollment(
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_csrf_protection),
):
    if context.user.user_type == "candidate":
        return {"ok": False, "detail": "MFA is only required for internal users"}
    enrollment = enroll_mfa(db, user=context.user)
    recovery_codes = getattr(enrollment, "_plain_recovery_codes", [])
    log_audit_event(
        db,
        event_type="mfa_enrollment_started",
        target_type="user",
        target_id=context.user.id,
        actor_id=context.user.id,
        actor_label="mfa_enroll",
        payload={},
    )
    db.commit()
    db.refresh(enrollment)
    return {
        "enrollment": {
            "id": enrollment.id,
            "secret": enrollment.totp_secret,
            "provisioning_uri": totp_provisioning_uri(email=context.user.email, secret=enrollment.totp_secret),
            "recovery_codes": recovery_codes,
        }
    }


@router.post("/mfa/verify")
def complete_mfa_verification(
    payload: MfaVerifyRequest,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_csrf_protection),
):
    enrollment = get_active_mfa_enrollment(db, context.user.id)
    if not enrollment:
        return {"ok": False, "detail": "MFA enrollment not found"}
    if not verify_mfa_enrollment(db, enrollment=enrollment, code=payload.code):
        return {"ok": False, "detail": "MFA code invalid"}
    context.login_session.mfa_verified_at = context.login_session.mfa_verified_at or enrollment.verified_at
    db.add(context.login_session)
    log_audit_event(
        db,
        event_type="mfa_verified",
        target_type="user",
        target_id=context.user.id,
        actor_id=context.user.id,
        actor_label="mfa_verify",
        payload={},
    )
    db.commit()
    db.refresh(context.login_session)
    return {
        "ok": True,
        "user": serialize_user(context.user),
        "session": serialize_login_session(context.login_session, context.user, db=db),
    }
