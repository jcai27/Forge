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
    assert len(cash["alerts"]) == 3 and "$84.00 short" in cash["alerts"][0]["text"]

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
