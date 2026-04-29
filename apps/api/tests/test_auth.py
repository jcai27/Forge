import time

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.services.auth import ensure_password_credential
from app.services.auth import _totp_code


def _csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get(settings.auth_csrf_cookie_name)
    return {"x-csrf-token": csrf} if csrf else {}


def test_internal_login_requires_mfa_before_reviewer_access():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "reviewer@verified.dev", "password": "demo-password"})
        assert login.status_code == 200
        assert login.json()["session"]["mfa_required"] is True
        assert login.json()["session"]["mfa_verified"] is False

        denied = client.get("/api/internal/review-queue")
        assert denied.status_code == 403

        enroll = client.post("/api/auth/mfa/enroll", headers=_csrf_headers(client))
        assert enroll.status_code == 200
        secret = enroll.json()["enrollment"]["secret"]

        verify = client.post(
            "/api/auth/mfa/verify",
            json={"code": _totp_code(secret, int(time.time()) // 30)},
            headers=_csrf_headers(client),
        )
        assert verify.status_code == 200
        assert verify.json()["session"]["mfa_verified"] is True

        allowed = client.get("/api/internal/review-queue")
        assert allowed.status_code == 200


def test_password_reset_replaces_password():
    with TestClient(app) as client:
        requested = client.post("/api/auth/password/reset/request", json={"email": "candidate@example.com"})
        assert requested.status_code == 200
        reset_token = requested.json()["reset_token"]

        confirmed = client.post(
            "/api/auth/password/reset/confirm",
            json={"token": reset_token, "new_password": "candidate-password-2"},
        )
        assert confirmed.status_code == 200

        login = client.post("/api/auth/login", json={"email": "candidate@example.com", "password": "candidate-password-2"})
        assert login.status_code == 200
        assert login.json()["user"]["id"] == "candidate_demo"

    db = SessionLocal()
    try:
        ensure_password_credential(db, user_id="candidate_demo", password="demo-password")
        db.commit()
    finally:
        db.close()


def test_candidate_magic_link_redeem_creates_authenticated_candidate_session():
    with TestClient(app) as client:
        requested = client.post(
            "/api/auth/candidate/magic-link/request",
            json={"invite_token": "invite_candidate_demo", "email": "candidate@example.com"},
        )
        assert requested.status_code == 200
        magic_token = requested.json()["token"]

        redeemed = client.post("/api/auth/candidate/magic-link/redeem", json={"token": magic_token})
        assert redeemed.status_code == 200
        assert redeemed.json()["user"]["id"] == "candidate_demo"

        tracks = client.get("/api/candidate/tracks")
        assert tracks.status_code == 200
        assert any(item["id"] == "track_backend_api_v1" for item in tracks.json())
