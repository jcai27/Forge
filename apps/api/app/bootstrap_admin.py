from __future__ import annotations

import argparse

from app.db.models import Organization, User, UserType
from app.db.session import SessionLocal, init_db
from app.services.auth import ensure_password_credential


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap an initial Forge admin user.")
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        organization = db.query(Organization).filter(Organization.id == args.organization_id).first()
        if not organization:
            organization = Organization(
                id=args.organization_id,
                name=args.organization_name,
                billing_plan="design_partner",
                settings_json={},
            )
            db.add(organization)
        user = db.query(User).filter(User.id == args.user_id).first()
        if not user:
            user = User(id=args.user_id)
            db.add(user)
        user.email = args.email.lower().strip()
        user.full_name = args.full_name
        user.user_type = UserType.admin.value
        user.auth_provider = "password"
        user.organization_id = organization.id
        user.profile_json = {"title": "Platform Admin"}
        db.flush()
        ensure_password_credential(db, user_id=user.id, password=args.password, must_change_password=False)
        db.commit()
        print(f"bootstrapped_admin:{user.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
