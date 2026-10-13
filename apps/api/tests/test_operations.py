"""The operations pages: figures worked out in code from recorded facts, and the rules that say what needs somebody."""

import sys
from pathlib import Path
from types import SimpleNamespace

from factory.models import OperationsRecord, Organization
from factory.operations import AREAS, view
from tests.test_intake import client, member  # noqa: F401

sys.path.insert(0, str(Path(__file__).parents[3] / "demo" / "operations"))


def row(area, kind, day, location, **data):
    return SimpleNamespace(area=area, kind=kind, day=day, location=location, data=data, source="sample")


def sold(day, location, net=100000):
    return row(
        "sales", "day", day, location, net=net, covers=40, dine_in=net, takeout=0, delivery=0, lunch=0, dinner=net,
        discounts=0, voids=0, tax=round(net * 0.07),
    )  # fmt: skip


def test_the_rules_find_a_short_till_a_late_deposit_and_an_overcharged_commission():
    def till(day, counted, banked, settled=77920):
        return row(
            "cash", "day", day, "CAFE", cash_expected=20000, cash_counted=counted, cash_banked=banked,
            card_sales=80000, card_fees=2080, card_settled=settled,
        )  # fmt: skip

    rows = [sold(f"2026-03-{day:02d}", "CAFE") for day in range(2, 9)] + [
        till("2026-03-02", 20000, 20000),
        # $2 out is a till; $84 out is something to ask about.
        till("2026-03-03", 19800, 19800),
        till("2026-03-04", 11600, 11600),
        # Counted four days before the last day on record and never deposited. Yesterday's is simply not there yet.
        till("2026-03-04", 20000, None),
        till("2026-03-07", 20000, None, settled=None),
        till("2026-03-05", 20000, 20000, settled=70000),
    ]
    cash = view("cash", rows)
    assert [(found["location"], found["out"]) for found in cash["tables"][0]["rows"]] == [("CAFE", -8400)]
    assert [(found["date"], found["days"]) for found in cash["tables"][1]["rows"]] == [("2026-03-04", 4)]
    assert [found["short"] for found in cash["tables"][2]["rows"]] == [7920]
    assert (
        "$84.00 short" in cash["alerts"][0]["text"] and [alert["level"] for alert in cash["alerts"][:3]] == ["bad"] * 3
    )
    # Two days the business traded have no cash-up sheet at all: that is said, not passed over.
    assert [alert["text"] for alert in cash["alerts"][3:]] == [
        "CAFE: no cash-up sheet has arrived for Mar 6.",
        "CAFE: no cash-up sheet has arrived for Mar 8.",
    ]

    def payout(day, commission, paid):
        return row(
            "delivery", "payout", day, "CAFE", platform="Plate Runner", orders=30, gross=100000, rate_agreed=2500,
            commission=commission, refunds=2000, payout=paid,
        )  # fmt: skip

    # Agreed 25%: a week charged at 28% is $30 over. A payout $50 under its own arithmetic is short.
    delivery = view("delivery", [*rows, payout("2026-03-02", 28000, 70000), payout("2026-03-02", 25000, 68000)])
    (group,) = delivery["tables"][1]["rows"]
    assert (group["overcharged"], group["short"], group["charged_rate"]) == (3000, 5000, 26.5)
    assert delivery["tiles"][3]["value"] == 8000 and len(delivery["alerts"]) == 2
    # Labour is a share of the sales on the days a timesheet covers, and the week without one is reported.
    worked = [
        row(
            "labour",
            "day",
            f"2026-03-{day:02d}",
            "CAFE",
            kitchen_hours=10,
            floor_hours=10,
            management_hours=4,
            overtime_hours=0,
            scheduled_hours=24,
            cost=30000,
            tips=0,
        )
        for day in range(2, 9)
    ]
    later = [sold(f"2026-03-{day:02d}", "CAFE") for day in range(9, 16)]
    staffed = view("labour", [*rows, *worked, *later], weeks=2)
    assert staffed["tiles"][1]["value"] == 30.0  # $2,100 of labour on $7,000 of sales, not on the fortnight's $14,000
    assert "CAFE: no timesheet has arrived for the week of Mar 9." in [alert["text"] for alert in staffed["alerts"]]


def test_food_cost_is_stock_used_against_what_the_recipes_say():
    rows = [sold(f"2026-03-{day:02d}", "CAFE") for day in range(2, 9)] + [
        row("sales", "item_week", "2026-03-02", "CAFE", item="Chowder", category="Starters", stock="Seafood", qty=1000, sales=700000, cost=200),
        # Opened with $900 of seafood, took in $2,400, closed with $800: $2,500 used, against $2,000 by the recipes.
        row("inventory", "count_week", "2026-03-02", "CAFE", category="Seafood", opening=90000, purchases=240000, closing=80000),
        row("inventory", "waste", "2026-03-04", "CAFE", category="Seafood", reason="Spoiled", cost=10000),
    ]  # fmt: skip
    seen = view("inventory", rows)
    (place,) = seen["tables"][0]["rows"]
    assert (place["used"], place["actual"], place["recipes"], place["gap"]) == (250000, 35.7, 28.6, 7.1)
    # Of the $500 used beyond the recipes, the waste sheet accounts for $100.
    assert place["unexplained"] == 40000 and place["_tone"] == "bad" and len(seen["alerts"]) == 1
    # The profit and loss takes its cost of goods from the same count.
    statement = {line["line"]: line["total"] for line in view("accounting", rows)["tables"][0]["rows"]}
    assert (statement["Sales"], statement["Cost of goods used"], statement["Gross profit"]) == (700000, 250000, 450000)


def test_the_sample_workspace_fills_every_area_and_stays_inside_its_tenant(client, seeded, db):  # noqa: F811
    from sample import generate

    made = client.post("/customers", json={"name": "Harbor Table Group"}).json()
    org = db.get(Organization, made["id"])
    db.add_all(OperationsRecord(org_id=org.id, source="sample", **item) for item in generate())
    db.commit()
    person = member(db, org, "customer")
    me = client.get("/portal/me", headers=person).json()
    assert me["sample"] is True and [item["area"] for item in me["areas"]] == list(AREAS)
    for area in AREAS:
        seen = client.get(f"/portal/areas/{area}", headers=person)
        assert seen.status_code == 200, area
        body = seen.json()
        assert body["sample"] is True and len(body["tiles"]) == 4 and body["locations"] == sorted(body["locations"])
    # The four locations' books add up to the group's.
    books = client.get("/portal/areas/accounting", headers=person).json()["tables"][0]["rows"]
    for line in books:
        assert sum(line[place] for place in ("Airport Road", "Dockside", "Downtown", "Uptown")) == line["total"], line
    # One location, four weeks.
    one = client.get("/portal/areas/sales?location=Dockside&weeks=4", headers=person).json()
    assert (one["location"], one["weeks"], len(one["series"]["points"])) == ("Dockside", 4, 28)
    # Another customer has no records, and cannot reach these.
    other = client.post("/customers", json={"name": "Another Cafe"}).json()
    rival = member(db, db.get(Organization, other["id"]), "customer")
    assert client.get("/portal/areas/sales", headers=rival).status_code == 404
    assert client.get("/portal/me", headers=rival).json()["areas"] == []
    assert client.get("/portal/areas/nothing", headers=person).status_code == 404


def masters():
    from sample import generate

    from factory.recording import Masters

    return Masters([SimpleNamespace(**item) for item in generate()])


TILL = {
    "location": "DOCKSIDE", "date": "2026-09-27", "net_sales": 1000.0, "dine_in": 600.0, "takeout": 150.0, "delivery": 250.0,
    "lunch": 380.0, "dinner": 620.0, "guests": 22, "discounts": 14.0, "voids": 5.0, "sales_tax": 70.0,
    "items": [{"item": "Ribeye", "quantity": 4, "sales": 136.0}, {"item": "Fries", "quantity": 10, "sales": 60.0}],
}  # fmt: skip


def test_an_answer_is_recorded_only_when_it_holds_together():
    from factory.recording import check, kind_of, records

    known = masters()
    assert check("till", TILL, known) == []
    made = records("till", TILL, known)
    # The location is recorded as the workspace names it, amounts in cents, and each dish with its recipe's cost.
    area, kind, day, place, data = made[0]
    assert (area, kind, day, place, data["net"], data["covers"]) == (
        "sales",
        "day",
        "2026-09-27",
        "Dockside",
        100000,
        22,
    )
    assert [(row[1], row[4]["item"], row[4]["qty"], row[4]["cost"], row[4]["stock"]) for row in made[1:]] == [
        ("item_week", "Ribeye", 4, 1320, "Meat"),
        ("item_week", "Fries", 10, 110, "Produce"),
    ]
    # A misread channel, a place we do not have, a dish not on the menu, a second copy: each is held, with the reason.
    reasons = lambda answer, earlier=(): [found["kind"] for found in check("till", answer, known, earlier)]  # noqa: E731
    assert reasons({**TILL, "delivery": 520.0}) == ["does_not_add_up"]
    assert reasons({**TILL, "location": "Harbourside"}) == ["unknown_location"]
    assert reasons({**TILL, "items": [{"item": "Lobster roll", "quantity": 1, "sales": 24.0}]}) == ["unknown_item"]
    assert reasons(TILL, [{**TILL, "location": "Dockside"}]) == ["duplicate"]
    assert reasons({**TILL, "date": None}) == ["missing_field"]
    payout = {
        "platform": "Dash Away",
        "location": "Uptown",
        "week_start": "2026-09-21",
        "orders": 1,
        "gross_sales": 1,
        "commission": 1,
        "refunds": 0,
        "payout": 0,
    }
    assert [found["kind"] for found in check("payout", payout, known)] == ["unknown_platform"]
    # An answer missing what its kind needs is held, not a crash.
    assert [found["kind"] for found in check("till", {"location": "Uptown", "date": "2026-09-27"}, known)] == [
        "missing_field"
    ]
    week = {
        "location": "Uptown",
        "week_start": "2026-09-22",
        "categories": [{"category": "Seafood", "opening": 1, "deliveries": 2, "closing": 1}],
    }
    assert [found["kind"] for found in check("stockcount", week, known)] == ["bad_date"]  # a Tuesday
    # A quote is priced from the menu, never by the agent: 60 guests is 5% off the food, and three servers.
    enquiry = {
        "customer": "Okafor Family",
        "event": "Wedding",
        "date": "2026-10-06",
        "guests": 60,
        "package": "Seated dinner",
        "drinks": "no",
        "location": "Dockside",
    }
    ((_, _, held, _, quote),) = records("enquiry", enquiry, known)
    assert (held, quote["status"], quote["due"]) == ("2026-10-06", "sent", "2026-10-20")
    assert (
        quote["amount"] == quote["quote"]["food"] - quote["quote"]["discount"] + 33000
        and quote["quote"]["discount_percent"] == 5
    )
    assert [found["kind"] for found in check("enquiry", {**enquiry, "package": "Free lunch"}, known)] == [
        "unknown_item"
    ]

    # The kind of document is told from the shape of the answer.
    def shape(fields, rows=()):
        table = {"rows": {"type": "array", "items": {"properties": {row: {} for row in rows}}}} if rows else {}
        return {**{field: {"type": "number"} for field in fields}, **table}

    assert kind_of(shape(["net_sales"])) == "till" and kind_of(shape(["location"], ["kitchen_hours"])) == "timesheet"
    assert kind_of(shape(["invoice_number", "total_cents"], ["unit_price"])) is None


def test_a_document_read_by_an_agent_fills_its_page_and_a_doubtful_one_waits(client, seeded, db, monkeypatch):  # noqa: F811
    import json

    from sample import generate
    from sqlalchemy import select

    from factory.config import settings
    from factory.db import now
    from factory.models import AgentVersion, Deployment, Operation
    from tests.test_documents import pdf, upload
    from tests.test_intake import Model, direct_agent, reply, user_text

    class Scripted(Model):
        async def get_response(
            self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        ):
            payload = json.loads(user_text(input))
            return reply(json.loads(payload.get("input", payload)["text"].split("DATA ", 1)[1].splitlines()[0]))

        async def stream_response(self, *args, **kwargs):
            raise NotImplementedError
            yield

    org, user, *_ = seeded
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = Scripted()
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)

    def sheet(place, day, counted=200.0):
        return {
            "location": place,
            "date": day,
            "till_cash": 200.0,
            "counted_cash": counted,
            "card_sales": 800.0,
            "card_fees": 20.8,
            "banked": 0,
            "card_settled": 0,
        }

    created = direct_agent(client, seeded, request="Record a restaurant's daily cash-up sheet in full")
    rows = [
        {
            "text": f"sheet {n}",
            **{
                f"expected_{k}": v
                for k, v in sheet(("Uptown", "Dockside", "Harbourside")[n % 3], f"2026-01-{n + 1:02d}").items()
            },
        }
        for n in range(16)
    ]
    attached = client.post(
        f"/agents/{created['id']}/datasets",
        json={
            "name": "Sheets",
            "content": "\n".join(json.dumps(row) for row in rows),
            "format": "jsonl",
            "development": 8,
            "selection": 0,
            "validation": 8,
        },
    )
    assert attached.status_code == 201, attached.text
    version = db.get(AgentVersion, attached.json()["version"]["id"])
    version.approved_at, version.approved_by = now(), user.id
    deployment = Deployment(org_id=org.id, agent_id=created["id"], version_id=version.id, policy={"max_cost": 1})
    db.add(deployment)
    db.commit()
    customer = client.post("/customers", json={"name": "Harbor Table Group"}).json()
    there = db.get(Organization, customer["id"])
    db.add_all(OperationsRecord(org_id=there.id, source="sample", **item) for item in generate())
    db.commit()
    installed = client.post(
        f"/customers/{there.id}/operations", json={"deployment_id": deployment.id, "name": "Cash-up and banking"}
    )
    assert installed.status_code == 201, installed.text
    operation = db.scalar(select(Operation).where(Operation.org_id == there.id))
    # The kind is told from the answer's shape, and the workspace is told what the agent reads and fills.
    person = member(db, there, "customer")
    (listed,) = client.get("/portal/me", headers=person).json()["operations"]
    assert (operation.kind, listed["reads"], listed["area"]) == ("cashup", "Daily cash-up sheets", "cash")

    def send(answer, name):
        made = client.post(
            f"/portal/operations/{operation.id}/documents", headers=person,
            files=upload(pdf([name, "DATA " + json.dumps(answer, separators=(",", ":"))]), name),
        )  # fmt: skip
        assert made.status_code == 201, made.text
        return made.json()

    def written(document):
        return list(db.scalars(select(OperationsRecord).where(OperationsRecord.document_id == document["id"])))

    before = client.get("/portal/areas/cash", headers=person).json()
    # A clean sheet is recorded as it is read: $84 short, which the cash rules then find.
    first = send(sheet("Uptown", "2026-09-27", counted=116.0), "a.pdf")
    (row,) = written(first)
    assert (first["stage"], row.source, row.location, row.day, row.data["cash_counted"]) == (
        "ready",
        "agent",
        "Uptown",
        "2026-09-27",
        11600,
    )
    after = client.get("/portal/areas/cash", headers=person).json()
    assert after["from_agents"] == 1 and before["from_agents"] == 0
    assert any("Uptown: the till was $84.00 short on Sep 27" in alert["text"] for alert in after["alerts"])
    shown = client.get(f"/portal/documents/{first['id']}/records", headers=person).json()["items"]
    assert [(item["area"], item["area_title"], item["location"]) for item in shown] == [
        ("cash", "Cash and banking", "Uptown")
    ]
    # The same day again, and a place we do not have: both wait, and neither writes anything.
    again = send(sheet("Uptown", "2026-09-27"), "b.pdf")
    lost = send(sheet("Harbourside", "2026-09-27"), "c.pdf")
    assert (again["stage"], lost["stage"], written(again), written(lost)) == ("review", "review", [], [])
    assert [item["kind"] for item in lost["exception_list"]] == ["unknown_location"]
    # A person puts the place right: the checks pass and it is recorded. Approving cannot record an unknown place.
    refused = client.post(f"/portal/documents/{lost['id']}/review", headers=person, json={"approve": True}).json()
    assert written(refused) == []
    fixed = client.post(
        f"/portal/documents/{lost['id']}/review",
        headers=person,
        json={"corrected": sheet("Dockside", "2026-09-27"), "approve": True},
    ).json()
    assert [(row.location, row.data["cash_counted"]) for row in written(fixed)] == [("Dockside", 20000)]
    # A second copy is a person's call: approved, it is recorded.
    client.post(f"/portal/documents/{again['id']}/review", headers=person, json={"approve": True})
    assert len(written(again)) == 1
    # Another customer cannot see what a document was recorded as.
    other = client.post("/customers", json={"name": "Another Cafe"}).json()
    rival = member(db, db.get(Organization, other["id"]), "customer")
    assert client.get(f"/portal/documents/{first['id']}/records", headers=rival).status_code == 404
