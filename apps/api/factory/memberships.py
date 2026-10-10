"""Tenant-scoped membership administration and possession-based invitation acceptance."""

import hashlib
import re
import secrets
from datetime import UTC, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator
from sqlalchemy import func, select

from factory.db import get_db, now
from factory.models import Membership, Organization, OrganizationInvitation, User
from factory.schemas import StrictModel
from factory.security import Principal, audit, principal, require_admin, token_for

router = APIRouter()
DB, ACTOR = Depends(get_db), Depends(principal)
Role = Literal["admin", "editor", "viewer"]
OFFSET, LIMIT = Query(0, ge=0), Query(50, ge=1, le=200)


class MemberUpdate(StrictModel):
    role: Role


class CreateInvitation(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    role: Role = "viewer"
    ttl_hours: int = Field(default=72, ge=1, le=168)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Valid email required")
        return value


class AcceptInvitation(StrictModel):
    token: str = Field(min_length=32, max_length=128)


class SwitchOrganization(StrictModel):
    org_id: str = Field(min_length=36, max_length=36)


@router.post("/auth/switch-organization")
def switch_organization(body: SwitchOrganization, actor=ACTOR, db=DB):
    member = db.scalar(select(Membership).where(Membership.org_id == body.org_id, Membership.user_id == actor.user_id))
    if not member:
        raise HTTPException(403, "Workspace membership required")
    org = db.get(Organization, member.org_id)
    return {"token": token_for(actor.user_id, member.org_id), "organization": {"id": org.id, "name": org.name}}


def admin_lock(db, actor):
    require_admin(actor)
    org = db.scalar(select(Organization).where(Organization.id == actor.org_id).with_for_update())
    member = db.scalar(
        select(Membership)
        .where(Membership.org_id == actor.org_id, Membership.user_id == actor.user_id)
        .execution_options(populate_existing=True)
    )
    if not org or not member or member.role != "admin":
        raise HTTPException(403, "Administrator role required")


def member_view(member, user):
    return {
        "id": member.id,
        "org_id": member.org_id,
        "user_id": member.user_id,
        "email": user.email,
        "role": member.role,
        "created_at": member.created_at.isoformat(),
    }


def invitation_view(invitation):
    expiry = (
        invitation.expires_at.replace(tzinfo=UTC) if invitation.expires_at.tzinfo is None else invitation.expires_at
    )
    status = (
        "accepted"
        if invitation.accepted_at
        else "revoked"
        if invitation.revoked_at
        else "expired"
        if expiry <= now()
        else "pending"
    )
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "created_at": invitation.created_at.isoformat(),
        "expires_at": expiry.isoformat(),
        "status": status,
    }


@router.get("/organizations/members")
def members(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    query = select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == actor.org_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Membership.created_at, Membership.id).offset(offset).limit(limit))
    return {
        "items": [member_view(member, user) for member, user in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.patch("/organizations/members/{member_id}")
def update_member(member_id: str, body: MemberUpdate, actor=ACTOR, db=DB):
    admin_lock(db, actor)
    member = db.scalar(select(Membership).where(Membership.id == member_id, Membership.org_id == actor.org_id))
    if not member:
        raise HTTPException(404, "Member not found")
    if member.user_id == actor.user_id and body.role != "admin":
        raise HTTPException(409, "Cannot demote your own administrator membership")
    member.role = body.role
    audit(db, actor, "membership_role_changed", member.id, {"role": body.role})
    db.commit()
    return member_view(member, db.get(User, member.user_id))


@router.delete("/organizations/members/{member_id}", status_code=204)
def remove_member(member_id: str, actor=ACTOR, db=DB):
    admin_lock(db, actor)
    member = db.scalar(select(Membership).where(Membership.id == member_id, Membership.org_id == actor.org_id))
    if not member:
        raise HTTPException(404, "Member not found")
    if member.user_id == actor.user_id:
        raise HTTPException(409, "Cannot remove your own administrator membership")
    audit(db, actor, "membership_removed", member.id, {"user_id": member.user_id})
    db.delete(member)
    db.commit()


@router.get("/organizations/invitations")
def invitations(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    require_admin(actor)
    query = select(OrganizationInvitation).where(OrganizationInvitation.org_id == actor.org_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(OrganizationInvitation.created_at.desc(), OrganizationInvitation.id).offset(offset).limit(limit)
    )
    return {"items": [invitation_view(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.post("/organizations/invitations", status_code=201)
def create_invitation(body: CreateInvitation, actor=ACTOR, db=DB):
    admin_lock(db, actor)
    existing = db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == actor.org_id, User.email == body.email)
    )
    if existing:
        raise HTTPException(409, "Recipient is already a member")
    # Replacing an invitation invalidates old links and previously granted roles.
    for old in db.scalars(
        select(OrganizationInvitation).where(
            OrganizationInvitation.org_id == actor.org_id,
            OrganizationInvitation.email == body.email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
    ):
        old.revoked_at = now()
    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        org_id=actor.org_id,
        email=body.email,
        role=body.role,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_by=actor.user_id,
        expires_at=now() + timedelta(hours=body.ttl_hours),
    )
    db.add(invitation)
    db.flush()
    audit(db, actor, "organization_invitation_created", invitation.id, {"email": body.email, "role": body.role})
    db.commit()
    return {**invitation_view(invitation), "token": token}


@router.post("/organizations/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: str, actor=ACTOR, db=DB):
    admin_lock(db, actor)
    invitation = db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.id == invitation_id, OrganizationInvitation.org_id == actor.org_id
        )
    )
    if not invitation:
        raise HTTPException(404, "Invitation not found")
    if invitation.accepted_at:
        raise HTTPException(409, "Invitation already accepted")
    if not invitation.revoked_at:
        invitation.revoked_at = now()
        audit(db, actor, "organization_invitation_revoked", invitation.id)
    db.commit()
    return invitation_view(invitation)


@router.post("/organization-invitations/accept")
def accept_invitation(body: AcceptInvitation, actor=ACTOR, db=DB):
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    invitation = db.scalar(select(OrganizationInvitation).where(OrganizationInvitation.token_hash == digest))
    if not invitation:
        raise HTTPException(404, "Invitation unavailable")
    # Same lock order as administrative mutations, then reread after waiting.
    db.scalar(select(Organization).where(Organization.id == invitation.org_id).with_for_update())
    invitation = db.scalar(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.id == invitation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = db.get(User, actor.user_id)
    inviter = db.scalar(
        select(Membership)
        .where(Membership.org_id == invitation.org_id, Membership.user_id == invitation.created_by)
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or user.email.lower().strip() != invitation.email
        or invitation_view(invitation)["status"] != "pending"
        or not inviter
        or inviter.role != "admin"
    ):
        raise HTTPException(404, "Invitation unavailable")
    member = db.scalar(
        select(Membership).where(Membership.org_id == invitation.org_id, Membership.user_id == actor.user_id)
    )
    if member:
        raise HTTPException(409, "Already a member; invitation cannot change an existing role")
    member = Membership(org_id=invitation.org_id, user_id=actor.user_id, role=invitation.role)
    db.add(member)
    invitation.accepted_at, invitation.accepted_by = now(), actor.user_id
    audit(
        db,
        Principal(actor.user_id, invitation.org_id, invitation.role),
        "organization_invitation_accepted",
        invitation.id,
        {"joined_org_id": invitation.org_id, "role": invitation.role},
    )
    db.commit()
    org = db.get(Organization, invitation.org_id)
    return {
        "token": token_for(actor.user_id, invitation.org_id),
        "organization": {"id": org.id, "name": org.name},
        "membership": member_view(member, user),
    }
