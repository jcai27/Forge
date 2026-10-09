from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, text

from factory.db import make_engine, now, uid


def test_sqlite_upgrade_and_downgrade_preserve_existing_evaluation_history(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/migration.db")
    directory = Path(__file__).resolve().parents[1]
    config = Config(str(directory / "alembic.ini"))
    config.set_main_option("script_location", str(directory / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002")
        tables = MetaData()
        tables.reflect(bind=connection)
        org, user, project, agent, version, suite, case, evaluation, execution, result = [uid() for _ in range(10)]
        common = {"org_id": org, "created_at": now()}
        rows = [
            ("organizations", {"id": org, "created_at": now(), "name": "Migration fixture"}),
            (
                "users",
                {"id": user, "created_at": now(), "email": "migration@example.invalid", "password_hash": "test-only"},
            ),
            ("projects", {**common, "id": project, "name": "Existing project", "description": ""}),
            (
                "agent_specs",
                {
                    **common,
                    "id": agent,
                    "project_id": project,
                    "name": "Existing agent",
                    "request": "Process orders",
                    "template": "orders",
                },
            ),
            (
                "agent_versions",
                {
                    **common,
                    "id": version,
                    "agent_id": agent,
                    "number": 1,
                    "spec": {},
                    "hypothesis": "Existing hypothesis",
                },
            ),
            ("evaluation_suites", {**common, "id": suite, "agent_id": agent, "name": "Existing suite"}),
            (
                "evaluation_cases",
                {
                    **common,
                    "id": case,
                    "suite_id": suite,
                    "name": "Existing case",
                    "split": "development",
                    "source": "synthetic",
                    "input": {},
                    "assertions": [],
                    "critical": False,
                    "trials": 1,
                },
            ),
            (
                "evaluation_runs",
                {
                    **common,
                    "id": evaluation,
                    "version_id": version,
                    "suite_id": suite,
                    "status": "completed",
                    "scorecard": {},
                },
            ),
            (
                "execution_runs",
                {
                    **common,
                    "id": execution,
                    "version_id": version,
                    "mode": "demo",
                    "status": "completed",
                    "input": {},
                    "output": {},
                    "metrics": {},
                },
            ),
            (
                "evaluation_results",
                {
                    **common,
                    "id": result,
                    "evaluation_run_id": evaluation,
                    "case_id": case,
                    "execution_id": execution,
                    "trial": 0,
                    "passed": True,
                    "checks": [],
                    "failures": [],
                },
            ),
        ]
        existing_usage_id = uid()
        rows.append(
            ("usage_records", {**common, "id": existing_usage_id, "run_id": execution, "tokens": 7, "cost": 0.25})
        )
        for name, row in rows:
            connection.execute(tables.tables[name].insert().values(**row))
        command.upgrade(config, "head")
        assert connection.execute(
            text("SELECT cost, role FROM usage_records WHERE id = :id"), {"id": existing_usage_id}
        ).one() == (0.25, "execution")
        assert (
            connection.execute(
                text("SELECT environment FROM evaluation_cases WHERE id = :id"), {"id": case}
            ).scalar_one()
            == "{}"
        )
        assert (
            connection.execute(
                text("SELECT case_id FROM evaluation_results WHERE id = :id"), {"id": result}
            ).scalar_one()
            == case
        )
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        command.check(config)
        command.downgrade(config, "0002")
        assert (
            connection.execute(
                text("SELECT cost FROM usage_records WHERE id = :id"), {"id": existing_usage_id}
            ).scalar_one()
            == 0.25
        )
        assert (
            connection.execute(text("SELECT name FROM evaluation_cases WHERE id = :id"), {"id": case}).scalar_one()
            == "Existing case"
        )
        command.upgrade(config, "head")
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        command.check(config)
    engine.dispose()
