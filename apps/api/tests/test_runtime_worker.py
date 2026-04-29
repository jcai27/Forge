import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Report, RuntimeJob, RuntimeJobStatus, Session as CandidateSession, SessionStatus, TrackVersion, User, UserType
from app.db.session import Base
from app.schemas import SessionCreate, SubmissionCreate
from app.services.platform import create_session, create_submission, get_session_or_404, provision_session_workspace
from app.services.runtime_worker import RuntimeJobWorkerService


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def seed_track_and_user(db):
    db.add(
        User(
            id="candidate_1",
            email="candidate_1@example.com",
            full_name="Candidate One",
            user_type=UserType.candidate.value,
            auth_provider="seeded",
            organization_id=None,
            profile_json={},
        )
    )
    db.add(
        TrackVersion(
            id="track_backend_api_v1",
            slug="warehouse-ops-api",
            title="Warehouse Ops API",
            role_family="backend",
            version="v1",
            prompt_markdown="Build the API",
            starter_repo_ref="local://warehouse-ops-api-v1",
            container_image_ref="local-dev/warehouse-ops-api:v1",
            duration_minutes=120,
            allowed_tools_json={},
            rubric_template_json={},
            benchmark_config_json={"cohort_minimum": 2},
            preview_config_json={"enabled": False},
            content_metadata_json={"rubric_version": "v1"},
            is_active=True,
        )
    )
    db.commit()


def test_worker_processes_provision_job(monkeypatch):
    session_factory = make_session_factory()
    monkeypatch.setattr("app.services.runtime_worker.SessionLocal", session_factory)

    db = session_factory()
    seed_track_and_user(db)
    session = create_session(db, SessionCreate(user_id="candidate_1", track_version_id="track_backend_api_v1"))
    queued_session, job = provision_session_workspace(db, session.id)
    assert queued_session.status == SessionStatus.queued.value
    assert job.status == RuntimeJobStatus.queued.value

    monkeypatch.setattr(
        "app.services.runtime_worker.runtime_provisioner.provision_workspace",
        lambda **_: {"status": "provisioned", "seeded_file_count": 3, "backend": "docker"},
    )

    worker = RuntimeJobWorkerService()
    processed = asyncio.run(worker.run_once())
    assert processed == 1

    verification_db = session_factory()
    refreshed = get_session_or_404(verification_db, session.id)
    latest_job = verification_db.query(RuntimeJob).filter(RuntimeJob.id == job.id).first()
    assert refreshed.status == SessionStatus.ready.value
    assert refreshed.environment_summary_json["readiness"] == "ready"
    assert latest_job is not None
    assert latest_job.status == RuntimeJobStatus.succeeded.value


def test_worker_processes_submission_freeze_job(monkeypatch):
    session_factory = make_session_factory()
    monkeypatch.setattr("app.services.runtime_worker.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.platform.runtime_provisioner.workspace_summary", lambda _: {"workspace_id": "ws_demo"})
    monkeypatch.setattr("app.services.runtime_worker.runtime_provisioner.workspace_summary", lambda _: {"workspace_id": "ws_demo"})

    db = session_factory()
    seed_track_and_user(db)
    session = create_session(db, SessionCreate(user_id="candidate_1", track_version_id="track_backend_api_v1"))
    session.status = SessionStatus.ready.value
    db.add(session)
    db.commit()

    queued = create_submission(db, SubmissionCreate(session_id=session.id, immutable_snapshot={"files": ["app/main.py"]}))
    assert queued["session"]["status"] == SessionStatus.submitting.value
    assert queued["report"]["candidate_summary"]["submission"]["status"] == "finalizing"

    monkeypatch.setattr(
        "app.services.runtime_worker.runtime_provisioner.create_submission_artifact",
        lambda **_: {
            "artifact_uri": "object://submissions/sub_demo/repo",
            "artifact_sha": "abc123",
            "build_log_uri": "object://submissions/sub_demo/logs/build.log",
            "test_log_uri": "object://submissions/sub_demo/logs/tests.log",
            "artifact_manifest_uri": "object://submissions/sub_demo/manifest.json",
            "immutable_snapshot": {
                "files": ["app/main.py"],
                "evidence_uris": {"events": "object://submissions/sub_demo/events.log"},
            },
        },
    )

    worker = RuntimeJobWorkerService()
    processed = asyncio.run(worker.run_once())
    assert processed == 1

    verification_db = session_factory()
    refreshed_session = verification_db.query(CandidateSession).filter(CandidateSession.id == session.id).first()
    refreshed_report = verification_db.query(Report).filter(Report.id == queued["report"]["id"]).first()
    latest_job = (
        verification_db.query(RuntimeJob)
        .filter(RuntimeJob.target_type == "session", RuntimeJob.target_id == session.id)
        .order_by(RuntimeJob.created_at.desc())
        .first()
    )

    assert refreshed_session is not None
    assert refreshed_session.status == SessionStatus.submitted.value
    assert refreshed_report is not None
    assert refreshed_report.candidate_summary_json["submission"]["artifact_uri"] == "object://submissions/sub_demo/repo"
    assert refreshed_report.review_summary_json["publication_state"] == "draft"
    assert latest_job is not None
    assert latest_job.status == RuntimeJobStatus.succeeded.value
