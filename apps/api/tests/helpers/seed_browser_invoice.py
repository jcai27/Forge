"""Seed a disposable customer invoice workspace for the browser acceptance journey."""

import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.api import demo
from factory.config import settings
from factory.db import SessionLocal, now
from factory.models import (
    AgentRecord,
    AgentVersion,
    Deployment,
    InboxDocument,
    Membership,
    Operation,
    Organization,
    Project,
)


def main():
    if not settings().database_url.startswith("sqlite:////tmp/factory-e2e-"):
        raise RuntimeError("Invoice browser fixtures require the disposable E2E database")
    with SessionLocal() as db:
        import asyncio

        asyncio.run(demo(db))
        parent = db.scalar(select(Organization).where(Organization.kind == "builder"))
        owner = db.scalar(select(Membership).where(Membership.org_id == parent.id))
        org = Organization(name="Invoice Browser Customer", kind="customer", parent_org_id=parent.id)
        db.add(org)
        db.flush()
        db.add_all(
            [
                Membership(org_id=org.id, user_id=owner.user_id, role="admin"),
                Project(org_id=org.id, name="Operations", description="Browser invoice fixture"),
            ]
        )
        project = db.scalar(select(Project).where(Project.org_id == org.id))
        agent = AgentRecord(
            org_id=org.id,
            project_id=project.id,
            name="Invoice browser fixture",
            request="Extract the fields and priced lines from a supplier invoice.",
            template="custom",
        )
        db.add(agent)
        db.flush()
        invoice_schema = {
            "type": "object",
            "properties": {
                "supplier": {"type": "string"},
                "invoice_number": {"type": "string"},
                "invoice_date": {"type": "string"},
                "total_cents": {"type": "integer"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "amount": {"type": "number"},
                        },
                        "required": ["description", "quantity", "unit_price", "amount"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["supplier", "invoice_number", "invoice_date", "total_cents", "items"],
            "additionalProperties": False,
        }
        statement_schema = {
            "type": "object",
            "properties": {
                "supplier": {"type": "string"},
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "invoice_number": {"type": "string"},
                            "invoice_date": {"type": "string"},
                            "amount": {"type": "number"},
                        },
                        "required": ["invoice_number", "amount"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["supplier", "rows"],
            "additionalProperties": False,
        }
        version = AgentVersion(
            org_id=org.id,
            agent_id=agent.id,
            number=1,
            spec={
                "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "output_schema": invoice_schema,
            },
            hypothesis="Browser fixture",
            approved_at=now(),
            approved_by=owner.user_id,
        )
        db.add(version)
        db.flush()
        agent.best_version_id = version.id
        deployment = Deployment(
            org_id=org.id,
            agent_id=agent.id,
            version_id=version.id,
            policy={"max_cost": 1, "lifetime_max_cost": 50, "max_invocations": 100},
        )
        db.add(deployment)
        db.flush()
        agent_operation = Operation(
            org_id=org.id,
            deployment_id=deployment.id,
            actor_id=owner.user_id,
            name="Supplier invoices",
            document_field="text",
            kind="invoice",
        )
        statement_version = AgentVersion(
            org_id=org.id,
            agent_id=agent.id,
            number=2,
            spec={
                "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "output_schema": statement_schema,
            },
            hypothesis="Statement browser fixture",
            approved_at=now(),
            approved_by=owner.user_id,
        )
        db.add(statement_version)
        db.flush()
        statement_deployment = Deployment(
            org_id=org.id, agent_id=agent.id, version_id=statement_version.id, policy=dict(deployment.policy)
        )
        db.add(statement_deployment)
        db.flush()
        statement_operation = Operation(
            org_id=org.id,
            deployment_id=statement_deployment.id,
            actor_id=owner.user_id,
            name="Supplier statements",
            document_field="text",
            kind="statement",
        )
        db.add_all([agent_operation, statement_operation])
        db.flush()
        base = {
            "supplier": "Gordon Food Service",
            "customer": "Invoice Browser Customer",
            "invoice_date": "2026-02-01",
            "items": [
                {"code": "206539", "description": "CASE LARGE EGGS", "quantity": 5, "unit_price": 9.37, "amount": 46.85}
            ],
        }
        clean = {**base, "invoice_number": "1001", "total_cents": 4685}
        bad = {**base, "invoice_number": "1002", "total_cents": 1}
        db.add_all(
            [
                InboxDocument(
                    org_id=org.id,
                    operation_id=agent_operation.id,
                    source="upload",
                    name="invoice-1001.pdf",
                    content_hash="1" * 64,
                    status="processed",
                    stage="ready",
                    output=clean,
                ),
                InboxDocument(
                    org_id=org.id,
                    operation_id=agent_operation.id,
                    source="upload",
                    name="invoice-1002.pdf",
                    content_hash="2" * 64,
                    status="processed",
                    stage="review",
                    exceptions=[{"kind": "lines_do_not_add_up", "message": "The lines and total differ."}],
                    output=bad,
                ),
                InboxDocument(
                    org_id=org.id,
                    operation_id=statement_operation.id,
                    source="upload",
                    name="statement-february.pdf",
                    content_hash="3" * 64,
                    status="processed",
                    stage="ready",
                    output={
                        "supplier": "Gordon Food Service",
                        "rows": [
                            {"invoice_number": "1001", "invoice_date": "2026-02-01", "amount": 46.85},
                            {"invoice_number": "1003", "invoice_date": "2026-02-02", "amount": 20.0},
                        ],
                    },
                ),
            ]
        )
        db.commit()


if __name__ == "__main__":
    main()
