from app.db.models import Organization, TrackVersion, User, UserType


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
    existing_track = db.query(TrackVersion).filter(TrackVersion.id == "track_backend_api_v1").first()
    if existing_track:
        return

    organization = Organization(
        id="org_design_partner_demo",
        name="Northstar Foundry",
        billing_plan="design_partner",
        settings_json={
            "review_sla_hours": 24,
            "pilot_roles": ["backend engineer"],
            "workflow": "platform_credential",
        },
    )

    users = [
        User(
            id="candidate_demo",
            email="candidate@example.com",
            full_name="Riley Chen",
            user_type=UserType.candidate.value,
            profile_json={
                "headline": "Backend engineer",
                "years_experience": 4,
                "location": "New York, NY",
                "consented_to_telemetry": True,
            },
        ),
        User(
            id="employer_manager_demo",
            email="manager@northstar.dev",
            full_name="Avery Singh",
            user_type=UserType.employer.value,
            organization_id="org_design_partner_demo",
            profile_json={"title": "Engineering Manager"},
        ),
        User(
            id="admin_reviewer_demo",
            email="reviewer@verified.dev",
            full_name="Jordan Ellis",
            user_type=UserType.admin.value,
            organization_id="org_design_partner_demo",
            profile_json={"title": "Calibration Reviewer"},
        ),
    ]

    track = TrackVersion(
        id="track_backend_api_v1",
        slug="warehouse-ops-api",
        title="Warehouse Ops API",
        role_family="backend",
        version="v1",
        prompt_markdown=TRACK_PROMPT,
        starter_repo_ref="s3://starter-repos/warehouse-ops-api-v1.zip",
        container_image_ref="ghcr.io/verified/platform/warehouse-ops-api:v1",
        duration_minutes=300,
        allowed_tools_json={
            "browser_ide": True,
            "terminal": True,
            "ai_assistant": True,
            "network_egress": "restricted",
        },
        rubric_template_json=RUBRIC_TEMPLATE,
        benchmark_config_json={
            "cohort_minimum": 20,
            "dimensions": ["correctness", "architecture", "code_organization"],
        },
        is_active=True,
    )

    db.add(organization)
    for user in users:
        db.add(user)
    db.add(track)
    db.commit()

