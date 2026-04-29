from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Engine, inspect, text


def _has_table(engine: Engine, table_name: str) -> bool:
    return inspect(engine).has_table(table_name)


def _existing_columns(engine: Engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)} if _has_table(engine, table_name) else set()


def _add_columns(engine: Engine, table_name: str, columns: Iterable[tuple[str, str]]) -> None:
    existing = _existing_columns(engine, table_name)
    with engine.begin() as connection:
        for column_name, column_type in columns:
            if column_name in existing:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _create_schema_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY
                )
                """
            )
        )


def _applied_versions(engine: Engine) -> set[int]:
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {int(row[0]) for row in rows}


def _record_version(engine: Engine, version: int) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO schema_migrations(version) VALUES (:version)"), {"version": version})


def _migration_1(engine: Engine) -> None:
    dialect = engine.dialect.name
    json_type = "JSON" if dialect == "postgresql" else "TEXT"

    _add_columns(
        engine,
        "track_versions",
        [
            ("preview_config_json", json_type),
            ("content_metadata_json", json_type),
        ],
    )
    _add_columns(
        engine,
        "sessions",
        [
            ("preview_summary_json", json_type),
            ("attempt_id", "VARCHAR"),
            ("heartbeat_at", "DATETIME"),
            ("expires_at", "DATETIME"),
            ("runtime_failure_reason", "TEXT"),
            ("environment_summary_json", json_type),
        ],
    )
    _add_columns(
        engine,
        "submissions",
        [
            ("preview_summary_json", json_type),
            ("preview_share_token", "VARCHAR"),
            ("evidence_summary_json", json_type),
            ("artifact_manifest_uri", "VARCHAR"),
            ("published_at", "DATETIME"),
        ],
    )
    _add_columns(
        engine,
        "reports",
        [
            ("review_summary_json", json_type),
            ("published_review_id", "VARCHAR"),
        ],
    )
    _add_columns(
        engine,
        "employer_reviews",
        [
            ("state", "VARCHAR"),
            ("escalation_state", "VARCHAR"),
            ("reviewer_annotations_json", json_type),
            ("draft_saved_at", "DATETIME"),
            ("published_at", "DATETIME"),
        ],
    )
    _add_columns(
        engine,
        "reviewer_assignments",
        [
            ("claimed_at", "DATETIME"),
            ("released_at", "DATETIME"),
        ],
    )
    _add_columns(
        engine,
        "calibration_runs",
        [
            ("rubric_version", "VARCHAR"),
        ],
    )


def _migration_2(engine: Engine) -> None:
    from app.db import models

    models.Credential.__table__.create(engine, checkfirst=True)
    models.LoginSession.__table__.create(engine, checkfirst=True)
    models.PasswordResetToken.__table__.create(engine, checkfirst=True)
    models.EmailVerificationToken.__table__.create(engine, checkfirst=True)
    models.MfaEnrollment.__table__.create(engine, checkfirst=True)

    _add_columns(
        engine,
        "runtime_jobs",
        [
            ("available_at", "DATETIME"),
            ("lease_expires_at", "DATETIME"),
            ("heartbeat_at", "DATETIME"),
            ("max_attempts", "INTEGER DEFAULT 5"),
        ],
    )


def run_migrations(engine: Engine) -> None:
    _create_schema_migrations(engine)
    migrations: list[tuple[int, callable]] = [
        (1, _migration_1),
        (2, _migration_2),
    ]
    applied = _applied_versions(engine)
    for version, migration in migrations:
        if version in applied:
            continue
        migration(engine)
        _record_version(engine, version)
