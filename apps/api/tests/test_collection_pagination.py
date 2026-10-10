"""Bounded, stable, tenant-owned collection traversal beyond default first pages."""

import pytest
from fastapi.testclient import TestClient

from factory.api import app, limits
from factory.db import get_db
from factory.models import Deployment, EvaluationSuite, Membership, Organization, User
from factory.security import passwords, token_for


@pytest.mark.parametrize("kind", ["suites", "deployments"])
def test_all_agent_collections_accept_bounded_pagination_without_cross_tenant_rows(db, seeded, kind):
    org, user, agent, version, *_ = seeded
    cls = EvaluationSuite if kind == "suites" else Deployment
    # Keep the authored suite and its dependent cases; add enough rows to traverse pages.
    for index in range(52 if kind == "suites" else 53):
        fields = (
            {"name": f"Suite {index}"}
            if kind == "suites"
            else {"version_id": version.id, "active": False, "policy": {}}
        )
        db.add(cls(org_id=org.id, agent_id=agent.id, **fields))
    otherorg = Organization(name="Other collection tenant")
    otheruser = User(
        email="other-collection@example.invalid", password_hash=passwords.hash("collection-other-password")
    )
    db.add_all([otherorg, otheruser])
    db.flush()
    db.add(Membership(org_id=otherorg.id, user_id=otheruser.id, role="admin"))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            path = f"/agents/{agent.id}/{kind}"
            first = client.get(path).json()
            assert first["total"] == 53 and first["offset"] == 0 and first["limit"] == 50 and len(first["items"]) == 50
            final = client.get(path + "?offset=50&limit=5").json()
            assert final["total"] == 53 and final["offset"] == 50 and final["limit"] == 5 and len(final["items"]) == 3
            assert not set(row["id"] for row in first["items"]) & set(row["id"] for row in final["items"])
            assert client.get(path + "?offset=50&limit=5").json() == final
            assert client.get(path + "?offset=53&limit=5").json()["items"] == []
            assert client.get(path + "?limit=201").status_code == 422
            assert client.get(path + "?offset=-1").status_code == 422
            denied = client.get(path, headers={"Authorization": "Bearer " + token_for(otheruser.id, otherorg.id)})
            assert denied.status_code == 404
    finally:
        app.dependency_overrides.clear()
