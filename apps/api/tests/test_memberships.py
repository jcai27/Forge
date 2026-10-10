"""Invitation possession, tenant isolation, role revocation and account safety."""

import hashlib
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from factory.api import app, limits
from factory.db import get_db, now
from factory.models import AuditEvent, Membership, OrganizationInvitation
from factory.security import token_for


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    with TestClient(app) as client:
        org, user, *_ = seeded
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def register_recipient(client, email="recipient@example.invalid"):
    result = client.post(
        "/auth/register",
        json={"email": email, "password": "recipient-test-password", "organization": "Recipient original workspace"},
    )
    assert result.status_code == 201, result.text
    return result.json(), {"Authorization": "Bearer " + result.json()["token"]}


def invite(client, email="recipient@example.invalid", role="viewer"):
    result = client.post("/organizations/invitations", json={"email": email, "role": role})
    assert result.status_code == 201, result.text
    return result.json()


def test_single_use_invitation_is_email_bound_hash_only_and_joins_target_tenant(client, db, seeded):
    org, _, *_ = seeded
    recipient, headers = register_recipient(client)
    created = invite(client, " Recipient@Example.Invalid ", "editor")
    record = db.get(OrganizationInvitation, created["id"])
    assert (
        record.email == "recipient@example.invalid"
        and record.token_hash == hashlib.sha256(created["token"].encode()).hexdigest()
    )
    listing = client.get("/organizations/invitations").json()
    assert listing["total"] == 1 and listing["items"][0]["status"] == "pending"
    assert listing["items"][0]["expires_at"].endswith("+00:00")
    assert created["token"] not in str(listing) and record.token_hash not in str(listing)
    assert created["token"] not in str([row.detail for row in db.scalars(select(AuditEvent))])
    assert client.post("/organization-invitations/accept", json={"token": created["token"]}).status_code == 404
    accepted = client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["organization"]["id"] == org.id and result["membership"]["role"] == "editor"
    joined_headers = {"Authorization": "Bearer " + result["token"]}
    assert client.get("/auth/me", headers=joined_headers).json()["role"] == "editor"
    assert client.get("/projects", headers=joined_headers).json()["items"][0]["org_id"] == org.id
    assert client.get("/organizations/invitations", headers=joined_headers).status_code == 403
    assert (
        client.post(
            "/organizations/invitations", json={"email": "other@example.invalid"}, headers=joined_headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/organizations/members/" + result["membership"]["id"], json={"role": "admin"}, headers=joined_headers
        ).status_code
        == 403
    )
    assert (
        client.post("/organizations/invitations/" + created["id"] + "/revoke", headers=joined_headers).status_code
        == 403
    )
    assert (
        client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).status_code
        == 404
    )
    assert record.accepted_by == recipient["user"]["id"] and record.accepted_at
    assert db.scalar(
        select(AuditEvent).where(AuditEvent.org_id == org.id, AuditEvent.action == "organization_invitation_accepted")
    )


@pytest.mark.parametrize("condition", ["expired", "revoked", "replaced", "inviter_demoted"])
def test_unavailable_invites_grant_no_membership(client, db, seeded, condition):
    org, user, *_ = seeded
    recipient, headers = register_recipient(client)
    created = invite(client)
    record = db.get(OrganizationInvitation, created["id"])
    if condition == "expired":
        record.expires_at = now() - timedelta(seconds=1)
        db.commit()
    elif condition == "revoked":
        assert client.post(f"/organizations/invitations/{record.id}/revoke").status_code == 200
    elif condition == "replaced":
        replacement = invite(client, role="editor")
        assert replacement["token"] != created["token"]
        assert record.revoked_at
    else:
        member = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
        member.role = "viewer"
        db.commit()
    assert (
        client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).status_code
        == 404
    )
    assert not db.scalar(
        select(Membership).where(Membership.org_id == org.id, Membership.user_id == recipient["user"]["id"])
    )


def test_role_changes_and_removal_revoke_previously_issued_token_permissions(client, db, seeded):
    recipient, headers = register_recipient(client)
    created = invite(client, role="editor")
    accepted = client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).json()
    joined = {"Authorization": "Bearer " + accepted["token"]}
    member_id = accepted["membership"]["id"]
    assert client.post("/projects", json={"name": "Allowed editor project"}, headers=joined).status_code == 201
    assert client.patch(f"/organizations/members/{member_id}", json={"role": "viewer"}).status_code == 200
    assert client.post("/projects", json={"name": "Forbidden viewer project"}, headers=joined).status_code == 403
    assert client.delete(f"/organizations/members/{member_id}", headers=joined).status_code == 403
    assert client.delete(f"/organizations/members/{member_id}").status_code == 204
    assert client.get("/projects", headers=joined).status_code == 401
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert db.scalar(select(Membership).where(Membership.user_id == recipient["user"]["id"]))


def test_tenant_and_admin_boundaries_self_protection_and_pagination(client, db, seeded):
    org, user, *_ = seeded
    _, other = register_recipient(client)
    mine = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
    assert client.patch(f"/organizations/members/{mine.id}", json={"role": "viewer"}).status_code == 409
    assert client.delete(f"/organizations/members/{mine.id}").status_code == 409
    assert client.patch(f"/organizations/members/{mine.id}", json={"role": "viewer"}, headers=other).status_code == 404
    assert client.delete(f"/organizations/members/{mine.id}", headers=other).status_code == 404
    created = invite(client)
    assert client.post(f"/organizations/invitations/{created['id']}/revoke", headers=other).status_code == 404
    assert client.get("/organizations/invitations", headers=other).json()["items"] == []
    assert client.get("/organizations/members?limit=1").json()["total"] == 1
    assert client.get("/organizations/members?offset=1&limit=1").json()["items"] == []
    assert client.get("/organizations/members?limit=201").status_code == 422
    assert "password_hash" not in client.get("/organizations/members").text
    assert client.post("/organizations/invitations", json={"email": user.email, "role": "viewer"}).status_code == 409
    assert client.post("/organizations/invitations", json={"email": "bad email", "role": "viewer"}).status_code == 422
    assert (
        client.post("/organizations/invitations", json={"email": "a@example.invalid", "role": "owner"}).status_code
        == 422
    )


def test_invitation_cannot_upgrade_an_existing_membership(client, db, seeded):
    org, *_ = seeded
    recipient, headers = register_recipient(client)
    created = invite(client, role="admin")
    member = Membership(org_id=org.id, user_id=recipient["user"]["id"], role="viewer")
    db.add(member)
    db.commit()
    assert (
        client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).status_code
        == 409
    )
    assert member.role == "viewer"


def test_workspace_switch_requires_current_membership(client, seeded):
    org, *_ = seeded
    recipient, headers = register_recipient(client)
    assert client.post("/auth/switch-organization", json={"org_id": org.id}, headers=headers).status_code == 403
    created = invite(client)
    accepted = client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).json()
    joined = {"Authorization": "Bearer " + accepted["token"]}
    profile = client.get("/auth/me", headers=joined).json()
    assert len(profile["memberships"]) == 2 and all(item["organization_name"] for item in profile["memberships"])
    switched = client.post(
        "/auth/switch-organization", json={"org_id": recipient["organization"]["id"]}, headers=joined
    )
    assert switched.status_code == 200
    assert (
        client.get("/auth/me", headers={"Authorization": "Bearer " + switched.json()["token"]}).json()["organization"][
            "id"
        ]
        == recipient["organization"]["id"]
    )
    assert client.delete("/organizations/members/" + accepted["membership"]["id"]).status_code == 204
    assert client.post("/auth/switch-organization", json={"org_id": org.id}, headers=headers).status_code == 403


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL row-lock behavior")
def test_concurrent_admin_demotions_preserve_one_authorized_administrator(client, db, seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException
    from sqlalchemy.orm import sessionmaker

    from factory.memberships import MemberUpdate, update_member
    from factory.security import Principal

    org, user, *_ = seeded
    recipient, headers = register_recipient(client)
    created = invite(client, role="admin")
    accepted = client.post("/organization-invitations/accept", json={"token": created["token"]}, headers=headers).json()
    first = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
    second = accepted["membership"]["id"]
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def demote(actor_id, target_id):
        with sessions() as other:
            barrier.wait(timeout=5)
            try:
                update_member(target_id, MemberUpdate(role="viewer"), Principal(actor_id, org.id, "admin"), other)
                return 200
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(demote, user.id, second)
        b = pool.submit(demote, recipient["user"]["id"], first.id)
        assert sorted([a.result(timeout=10), b.result(timeout=10)]) == [200, 403]
    db.expire_all()
    assert len(list(db.scalars(select(Membership).where(Membership.org_id == org.id, Membership.role == "admin")))) == 1


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL row-lock behavior")
def test_concurrent_invitation_claims_create_one_membership(client, db, seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException
    from sqlalchemy.orm import sessionmaker

    from factory.memberships import AcceptInvitation, accept_invitation
    from factory.security import Principal

    org, *_ = seeded
    recipient, _ = register_recipient(client)
    created = invite(client)
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def claim():
        with sessions() as other:
            barrier.wait(timeout=5)
            try:
                accept_invitation(
                    AcceptInvitation(token=created["token"]),
                    Principal(recipient["user"]["id"], recipient["organization"]["id"], "admin"),
                    other,
                )
                return 200
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(claim), pool.submit(claim)
        assert sorted([a.result(timeout=10), b.result(timeout=10)]) == [200, 404]
    db.expire_all()
    assert (
        len(
            list(
                db.scalars(
                    select(Membership).where(Membership.org_id == org.id, Membership.user_id == recipient["user"]["id"])
                )
            )
        )
        == 1
    )
