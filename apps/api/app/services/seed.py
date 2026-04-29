from datetime import UTC, datetime, timedelta

from app.db.models import AssessmentAttempt, AttemptStatus, Organization, TrackVersion, User, UserType
from app.services.auth import ensure_password_credential


TRACK_PROMPT = """
# Warehouse Ops API Track

Build and harden a small backend API for warehouse inventory events.

## Objectives

- Implement CRUD and filtered query endpoints for inventory adjustments.
- Add validation and error handling for duplicate or invalid inventory events.
- Improve tests for correctness and edge cases.
- Make one performance-conscious decision and document the tradeoff.

## Constraints

- Work inside the provided starter repository only.
- AI assistance is allowed, but it is logged and summarized in the final report.
- The runtime is bounded and network access is restricted.
""".strip()


RUBRIC_TEMPLATE = {
    "dimensions": [
        {"key": "correctness", "label": "Correctness", "weight": 0.35},
        {"key": "architecture", "label": "Architecture quality", "weight": 0.20},
        {"key": "code_organization", "label": "Code organization", "weight": 0.15},
        {"key": "debugging_strategy", "label": "Debugging strategy", "weight": 0.10},
        {"key": "tradeoff_awareness", "label": "Tradeoff awareness", "weight": 0.10},
        {"key": "explanation_quality", "label": "Explanation quality", "weight": 0.10},
    ]
}


def seed_database(db) -> None:
    organization = db.query(Organization).filter(Organization.id == "org_design_partner_demo").first()
    if not organization:
        organization = Organization(id="org_design_partner_demo")
        db.add(organization)
    organization.name = "Northstar Foundry"
    organization.billing_plan = "design_partner"
    organization.settings_json = {
        "review_sla_hours": 24,
        "pilot_roles": ["backend engineer"],
        "workflow": "platform_credential",
    }

    seeded_users = [
        {
            "id": "candidate_demo",
            "email": "candidate@example.com",
            "full_name": "Riley Chen",
            "user_type": UserType.candidate.value,
            "organization_id": None,
            "profile_json": {
                "headline": "Backend engineer",
                "years_experience": 4,
                "location": "New York, NY",
                "consented_to_telemetry": True,
            },
        },
        {
            "id": "employer_manager_demo",
            "email": "manager@northstar.dev",
            "full_name": "Avery Singh",
            "user_type": UserType.employer.value,
            "organization_id": "org_design_partner_demo",
            "profile_json": {"title": "Engineering Manager"},
        },
        {
            "id": "admin_reviewer_demo",
            "email": "reviewer@verified.dev",
            "full_name": "Jordan Ellis",
            "user_type": UserType.admin.value,
            "organization_id": "org_design_partner_demo",
            "profile_json": {"title": "Calibration Reviewer"},
        },
    ]

    for user_payload in seeded_users:
        user = db.query(User).filter(User.id == user_payload["id"]).first()
        if not user:
            user = User(id=user_payload["id"])
            db.add(user)
        user.email = user_payload["email"]
        user.full_name = user_payload["full_name"]
        user.user_type = user_payload["user_type"]
        user.auth_provider = "seeded"
        user.organization_id = user_payload["organization_id"]
        user.profile_json = user_payload["profile_json"]
        ensure_password_credential(db, user_id=user.id, password="demo-password", must_change_password=False)

    track = db.query(TrackVersion).filter(TrackVersion.id == "track_backend_api_v1").first()
    if not track:
        track = TrackVersion(id="track_backend_api_v1")
        db.add(track)
    track.slug = "warehouse-ops-api"
    track.title = "Warehouse Ops API"
    track.role_family = "backend"
    track.version = "v1"
    track.prompt_markdown = TRACK_PROMPT
    track.starter_repo_ref = "local://warehouse-ops-api-v1"
    track.container_image_ref = "local-dev/warehouse-ops-api:v3"
    track.duration_minutes = 300
    track.allowed_tools_json = {
        "browser_ide": True,
        "terminal": True,
        "ai_assistant": True,
        "network_egress": "restricted",
    }
    track.rubric_template_json = RUBRIC_TEMPLATE
    track.benchmark_config_json = {
        "cohort_minimum": 20,
        "dimensions": ["correctness", "architecture", "code_organization"],
    }
    track.content_metadata_json = {
        "prompt_version": "backend-api-prompt-v1",
        "starter_repo_version": "warehouse-ops-api-v1",
        "runtime_image_version": "local-dev/warehouse-ops-api:v3",
        "rubric_version": "backend-api-rubric-v1",
        "benchmark_cohort": "track_version_exact",
    }
    track.preview_config_json = {
        "enabled": True,
        "mode": "http",
        "start_command_template": "python -m uvicorn app.main:app --host 0.0.0.0 --port {PORT}",
        "readiness_path": "/health",
        "default_path": "/docs",
        "startup_timeout_seconds": 20,
    }
    track.is_active = True

    attempt = db.query(AssessmentAttempt).filter(AssessmentAttempt.id == "attempt_candidate_demo").first()
    if not attempt:
        attempt = AssessmentAttempt(id="attempt_candidate_demo")
        db.add(attempt)
    attempt.user_id = "candidate_demo"
    attempt.organization_id = "org_design_partner_demo"
    attempt.track_version_id = "track_backend_api_v1"
    attempt.candidate_label = "Riley Chen"
    attempt.invite_token = "invite_candidate_demo"
    attempt.status = AttemptStatus.pending.value
    attempt.notes = "Seeded managed-pilot attempt."
    attempt.expires_at = datetime.now(UTC) + timedelta(days=7)

    db.commit()
