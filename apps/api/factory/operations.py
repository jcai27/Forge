"""A customer's operations beyond its documents: sales, purchasing, stock, labour, cash, delivery
platforms, catering, the profit and loss, and compliance.

Everything here is sums and comparisons over OperationsRecord rows, done in code, like payables.py.
Each area returns the same shape for the page to lay out: tiles, one chart, ranked bars, tables, and
the things that need somebody's attention. What needs attention is decided by the rules written
here, never stored with the data, so sample data cannot carry a finding the rules would not make.

The period is the last `weeks` whole weeks of recorded sales. "Today" is the last day of sales on
record, not the day the page is opened, so a workspace reads the same whenever it is shown.
"""

from collections import namedtuple
from datetime import date, timedelta

Row = namedtuple("Row", "area kind day location data")

# What each area is, and the documents an agent would read to fill it in a working workspace.
AREAS = {
    "overview": ("Overview", "The documents of every area below."),
    "sales": ("Sales", "The till's end-of-day reports."),
    "purchasing": ("Purchasing", "Supplier invoices, credit notes and statements."),
    "inventory": ("Stock and food cost", "Weekly stock count sheets, waste sheets and supplier invoices."),
    "labour": ("Labour", "Timesheets and the weekly rota."),
    "cash": ("Cash and banking", "Daily cash-up sheets, bank statements and card settlement reports."),
    "delivery": ("Delivery platforms", "Each platform's weekly payout statement."),
    "catering": ("Catering and events", "Quotes, event orders and customer invoices."),
    "accounting": ("Profit and loss", "The same documents as every other area: nothing is entered twice."),
    "compliance": ("Compliance and upkeep", "Licences and certificates, temperature logs and repair tickets."),
}

# The area whose records each page is mostly worked out from.
AREA_RECORDS = {
    area: area for area in ("sales", "purchasing", "inventory", "labour", "cash", "delivery", "catering", "compliance")
}

# The rules that decide what needs attention.
CASH_TOLERANCE = 2500  # a till this many cents out is worth a look
BANKING_DAYS = 2  # cash counted but not at the bank after this many days
FOOD_COST_GAP = 2.0  # points between what was used and what the recipes say should have been
LABOUR_LIMIT = 33.0  # labour as a percentage of sales
OVERTIME_LIMIT = 4.0  # overtime as a percentage of hours worked
PRICE_RISE = 5.0  # percent
CREDIT_DAYS = 14  # a credit asked for and not received
EXPIRY_DAYS = 30
REPAIR_DAYS = 14
CHECKS_DONE = 95.0  # percent of temperature checks that must be on record


def percent(part, whole):
    return round(part / whole * 100, 1) if whole else None


def money(cents):
    return f"${cents / 100:,.2f}"


def short(day):
    return f"{day:%b} {day.day}"


class Scope:
    """The records one page is about: one location or all of them, over the chosen weeks."""

    def __init__(self, rows, location=None, weeks=8):
        self.all = [Row(r.area, r.kind, date.fromisoformat(r.day), r.location, r.data) for r in rows]
        self.locations = sorted({row.location for row in self.all if row.location})
        self.location = location if location in self.locations else None
        sold = [row.day for row in self.all if row.area == "sales" and row.kind == "day"]
        self.end = max(sold) if sold else date.today()
        self.weeks = max(1, min(int(weeks), 52))
        self.start = self.end - timedelta(days=self.weeks * 7 - 1)
        if sold:
            self.start = max(self.start, min(sold))

    def rows(self, area, kind, location=None, dated=True):
        """Records of one kind, for the page's location (or the one given), inside the period unless dated is off."""
        where = location or self.location
        return [
            row
            for row in self.all
            if row.area == area
            and row.kind == kind
            and (not where or row.location == where)
            and (not dated or self.start <= row.day <= self.end)
        ]

    def places(self):
        return [self.location] if self.location else self.locations

    def total(self, area, kind, field, location=None):
        return sum(int(row.data.get(field) or 0) for row in self.rows(area, kind, location))

    def by_day(self, area, kind, field):
        found = {}
        for row in self.rows(area, kind):
            found[row.day] = found.get(row.day, 0) + int(row.data.get(field) or 0)
        days = (self.end - self.start).days + 1
        return [
            {
                "start": (self.start + timedelta(days=n)).isoformat(),
                "value": found.get(self.start + timedelta(days=n), 0),
            }
            for n in range(days)
        ]

    def by_week(self, area, kind, field):
        found = {}
        for row in self.rows(area, kind):
            week = row.day - timedelta(days=row.day.weekday())
            found[week] = found.get(week, 0) + int(row.data.get(field) or 0)
        return [{"start": week.isoformat(), "value": value} for week, value in sorted(found.items())]


def tile(label, value, kind, sub="", tone=""):
    return {"label": label, "value": value, "kind": kind, "sub": sub, "tone": tone}


def column(key, label, kind="text"):
    return {"key": key, "label": label, "kind": kind}


def ranked(rows, key="value"):
    return sorted(rows, key=lambda row: -(row[key] or 0))


# Figures several areas share.


def used(scope, location=None, matched=False):
    """Stock used, in cents: what was there at the start, plus what came in, less what is left. With matched,
    only in the weeks food cost can be worked out for (see counted_weeks)."""
    weeks = counted_weeks(scope, location) if matched else None
    return sum(
        row.data["opening"] + row.data["purchases"] - row.data["closing"]
        for row in scope.rows("inventory", "count_week", location)
        if weeks is None or (row.location, row.day) in weeks
    )


def monday(day):
    return day - timedelta(days=day.weekday())


def counted_weeks(scope, location=None):
    """The location-weeks food cost can be worked out for: a stock count is on record, and so is a till report
    for every day the business traded that week. A week's sales with no count would make a location look as if
    it used nothing; a week's count with a day of sales still to come would make it look wasteful."""
    sold = {(row.location, row.day) for row in scope.rows("sales", "day")}
    traded = {day for _, day in sold}
    return {
        (row.location, row.day)
        for row in scope.rows("inventory", "count_week", location)
        if all((row.location, day) in sold for day in traded if monday(day) == row.day)
    }


def counted_sales(scope, location=None):
    """Sales in the weeks that have a stock count, in all and by week."""
    weeks, by_week = counted_weeks(scope, location), {}
    for row in scope.rows("sales", "day", location):
        if (row.location, monday(row.day)) in weeks:
            by_week[monday(row.day)] = by_week.get(monday(row.day), 0) + row.data["net"]
    return sum(by_week.values()), by_week


def sold_items(scope, location=None):
    """What sold in the weeks that have a stock count: the dishes the recipes are costed from."""
    weeks = counted_weeks(scope, location)
    return [row for row in scope.rows("sales", "item_week", location) if (row.location, monday(row.day)) in weeks]


def recipe_cost(scope, location=None):
    """What the recipes say the dishes sold should have used."""
    return sum(row.data["qty"] * row.data["cost"] for row in sold_items(scope, location))


def staffed_sales(scope, location=None):
    """Sales on the days a timesheet covers, in all and by week: labour is a share of those, not of days still to come in."""
    days, by_week = {(row.location, row.day) for row in scope.rows("labour", "day", location)}, {}
    for row in scope.rows("sales", "day", location):
        if (row.location, row.day) in days:
            by_week[monday(row.day)] = by_week.get(monday(row.day), 0) + row.data["net"]
    return sum(by_week.values()), by_week


def staffed_cost(scope, location=None):
    """Labour cost on the days a till report covers, in all and by week: the other half of the same match."""
    days, by_week = {(row.location, row.day) for row in scope.rows("sales", "day", location)}, {}
    for row in scope.rows("labour", "day", location):
        if (row.location, row.day) in days:
            by_week[monday(row.day)] = by_week.get(monday(row.day), 0) + row.data["cost"]
    return sum(by_week.values()), by_week


def missing(scope):
    """Paperwork that has not arrived, by area: a day or week one location has nothing for while the business
    was plainly trading. A page worked out without it is short, and should say so."""
    found = {area: [] for area in ("sales", "cash", "labour", "inventory", "delivery")}

    def note(area, text):
        found[area].append({"level": "warn", "text": text})

    def have(area, kind):
        return {(row.location, row.day) for row in scope.rows(area, kind)}

    sold, cash = have("sales", "day"), have("cash", "day")
    traded = {day for _, day in sold}
    for place in scope.places():
        for day in sorted(traded):
            if (place, day) not in sold:
                note("sales", f"{place}: no till report has arrived for {short(day)}.")
            elif (place, day) not in cash:
                note("cash", f"{place}: no cash-up sheet has arrived for {short(day)}.")
        weeks = sorted({monday(day) for where, day in sold if where == place and monday(day) >= scope.start})
        staffed = {monday(row.day) for row in scope.rows("labour", "day", place)}
        counted = {row.day for row in scope.rows("inventory", "count_week", place)}
        paid = {}
        for row in scope.rows("delivery", "payout", place):
            paid.setdefault(row.day, set()).add(row.data["platform"])
        platforms = set().union(*paid.values()) if paid else set()
        for week in weeks:
            if week not in staffed:
                note("labour", f"{place}: no timesheet has arrived for the week of {short(week)}.")
            if week not in counted:
                note("inventory", f"{place}: no stock count has arrived for the week of {short(week)}.")
            for platform in sorted(platforms - paid.get(week, set())):
                note("delivery", f"{place}: no {platform} payout statement has arrived for the week of {short(week)}.")
    return found


def figures(scope, location=None):
    """One location's profit and loss for the period, or the whole group's."""
    sales = scope.total("sales", "day", "net", location)
    goods = used(scope, location)
    labour = scope.total("labour", "day", "cost", location)
    commission = scope.total("delivery", "payout", "commission", location)
    fees = scope.total("cash", "day", "card_fees", location)
    costs = {}
    for row in scope.rows("accounting", "expense", location):
        costs[row.data["category"]] = costs.get(row.data["category"], 0) + row.data["amount"]
    rent, utilities = costs.pop("Rent", 0), costs.pop("Utilities", 0)
    other = sum(costs.values())
    profit = sales - goods - labour - commission - fees - rent - utilities - other
    return {
        "sales": sales,
        "goods": goods,
        "labour": labour,
        "commission": commission,
        "fees": fees,
        "rent": rent,
        "utilities": utilities,
        "other": other,
        "other_lines": costs,
        "profit": profit,
        # Each against the sales it can be set against: weeks with a stock count, days with a timesheet.
        "food_percent": (food := percent(used(scope, location, matched=True), counted_sales(scope, location)[0])),
        "labour_percent": (staff := percent(staffed_cost(scope, location)[0], staffed_sales(scope, location)[0])),
        "prime_percent": round(food + staff, 1) if food is not None and staff is not None else None,
        "margin": percent(profit, sales),
    }


# The areas.


def sales(scope):
    days = scope.rows("sales", "day")
    net = sum(row.data["net"] for row in days)
    covers = sum(row.data["covers"] for row in days)
    dine_in = sum(row.data["dine_in"] for row in days)
    discounts = sum(row.data["discounts"] for row in days)
    voids = sum(row.data["voids"] for row in days)
    channels = [
        {"name": name, "value": sum(row.data[key] for row in days)}
        for key, name in (("dine_in", "Dine in"), ("takeout", "Takeout"), ("delivery", "Delivery"))
    ]
    parts = [
        {"name": name, "value": sum(row.data[key] for row in days)}
        for key, name in (("lunch", "Lunch"), ("dinner", "Dinner"))
    ]
    items = {}
    for row in scope.rows("sales", "item_week"):
        entry = items.setdefault(
            row.data["item"],
            {"item": row.data["item"], "category": row.data["category"], "qty": 0, "sales": 0, "cost": 0},
        )
        entry["qty"] += row.data["qty"]
        entry["sales"] += row.data["sales"]
        entry["cost"] += row.data["qty"] * row.data["cost"]
    menu = [
        {
            **entry,
            "share": percent(entry["sales"], net),
            "margin": percent(entry["sales"] - entry["cost"], entry["sales"]),
        }
        for entry in ranked(items.values(), "sales")
    ]
    places = []
    for place in scope.places():
        rows = scope.rows("sales", "day", place)
        total, guests = sum(row.data["net"] for row in rows), sum(row.data["covers"] for row in rows)
        places.append(
            {
                "location": place,
                "sales": total,
                "covers": guests,
                "check": round(sum(row.data["dine_in"] for row in rows) / guests) if guests else None,
                "delivery_share": percent(sum(row.data["delivery"] for row in rows), total),
                "discount_rate": percent(sum(row.data["discounts"] for row in rows), total),
            }
        )
    span = (scope.end - scope.start).days + 1
    return {
        "tiles": [
            tile("Net sales", net, "money", f"{money(round(net / span * 7))} a week"),
            tile("Guests served", covers, "count", "dine-in covers"),
            tile("Average check", round(dine_in / covers) if covers else None, "money", "dine-in sales per guest"),
            tile("Discounts and voids", discounts + voids, "money", f"{percent(discounts + voids, net)}% of sales"),
        ],
        "series": {
            "title": "Net sales by day",
            "kind": "money",
            "bucket": "day",
            "points": scope.by_day("sales", "day", "net"),
        },
        "bars": [
            {"title": "By channel", "note": "Where the sales came from.", "kind": "money", "rows": ranked(channels)},
            {"title": "By service", "note": "Lunch against dinner.", "kind": "money", "rows": ranked(parts)},
        ],
        "tables": [
            {
                "title": "By location",
                "note": "",
                "columns": [
                    column("location", "Location"),
                    column("sales", "Net sales", "money"),
                    column("covers", "Guests", "count"),
                    column("check", "Average check", "money"),
                    column("delivery_share", "Delivery share", "percent"),
                    column("discount_rate", "Discounts", "percent"),
                ],
                "rows": ranked(places, "sales"),
            },
            {
                "title": "What sold",
                "note": "Each dish's sales, and what is left after the cost of its recipe.",
                "columns": [
                    column("item", "Dish"),
                    column("category", "Category"),
                    column("qty", "Sold", "count"),
                    column("sales", "Sales", "money"),
                    column("share", "Share of sales", "percent"),
                    column("margin", "Margin after recipe cost", "percent"),
                ],
                "rows": menu,
            },
        ],
        "alerts": [],
    }


def purchasing(scope):
    invoices = scope.rows("purchasing", "invoice")
    spend = sum(row.data["total"] for row in invoices)
    suppliers, categories = {}, {}
    for row in invoices:
        entry = suppliers.setdefault(
            row.data["supplier"], {"supplier": row.data["supplier"], "invoices": 0, "total": 0}
        )
        entry["invoices"] += 1
        entry["total"] += row.data["total"]
        categories[row.data["category"]] = categories.get(row.data["category"], 0) + row.data["total"]
    rises, alerts = [], []
    for row in scope.rows("purchasing", "price"):
        up = percent(row.data["now"] - row.data["was"], row.data["was"])
        rises.append(
            {
                "date": row.day.isoformat(),
                "location": row.location,
                "supplier": row.data["supplier"],
                "item": row.data["item"],
                "was": row.data["was"],
                "now": row.data["now"],
                "up": up,
                "_tone": "warn" if up is not None and up > PRICE_RISE else "",
            }
        )
    over = [rise for rise in rises if rise["_tone"]]
    if over:
        alerts.append(
            {
                "level": "warn",
                "text": f"{len(over)} price {'rise' if len(over) == 1 else 'rises'} over {PRICE_RISE:g}% from suppliers this period.",
            }
        )
    credits = []
    for row in scope.rows("purchasing", "credit", dated=False):
        waiting = (scope.end - row.day).days
        late = row.data["status"] == "open" and waiting > CREDIT_DAYS
        credits.append(
            {
                "asked": row.day.isoformat(),
                "location": row.location,
                "supplier": row.data["supplier"],
                "reason": row.data["reason"],
                "amount": row.data["amount"],
                "status": "waiting" if row.data["status"] == "open" else "received",
                "days": waiting if row.data["status"] == "open" else None,
                "_tone": "bad" if late else "",
            }
        )
        if late:
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{row.location}: a credit of {money(row.data['amount'])} asked of {row.data['supplier']} "
                    f"{waiting} days ago has not arrived ({row.data['reason'].lower()}).",
                }
            )
    owed = sum(credit["amount"] for credit in credits if credit["status"] == "waiting")
    return {
        "tiles": [
            tile("Purchases", spend, "money", f"{len(invoices)} supplier invoices"),
            tile("Suppliers", len(suppliers), "count"),
            tile(
                "Credits waiting",
                owed,
                "money",
                f"{sum(c['status'] == 'waiting' for c in credits)} asked for, not yet received",
                "warn" if owed else "",
            ),
            tile("Price rises", len(over), "count", f"over {PRICE_RISE:g}% this period", "warn" if over else ""),
        ],
        "series": {
            "title": "Purchases by week",
            "kind": "money",
            "bucket": "week",
            "points": scope.by_week("purchasing", "invoice", "total"),
        },
        "bars": [
            {
                "title": "By category",
                "note": "",
                "kind": "money",
                "rows": ranked([{"name": name, "value": value} for name, value in categories.items()]),
            },
            {
                "title": "By supplier",
                "note": "",
                "kind": "money",
                "rows": ranked([{"name": s["supplier"], "value": s["total"]} for s in suppliers.values()]),
            },
        ],
        "tables": [
            {
                "title": "Credits asked for",
                "note": f"Short deliveries, damaged goods and wrong prices. One waiting more than {CREDIT_DAYS} days is marked.",
                "columns": [
                    column("asked", "Asked", "date"),
                    column("location", "Location"),
                    column("supplier", "Supplier"),
                    column("reason", "Reason"),
                    column("amount", "Amount", "money"),
                    column("status", "Status", "badge"),
                    column("days", "Days waiting", "count"),
                ],
                "rows": sorted(credits, key=lambda credit: (credit["status"] != "waiting", credit["asked"])),
            },
            {
                "title": "Prices that changed",
                "note": "Against the last price paid for the same item at the same location.",
                "columns": [
                    column("date", "Date", "date"),
                    column("location", "Location"),
                    column("supplier", "Supplier"),
                    column("item", "Item"),
                    column("was", "Was", "money"),
                    column("now", "Now", "money"),
                    column("up", "Change", "percent"),
                ],
                "rows": sorted(rises, key=lambda rise: -(rise["up"] or 0)),
            },
        ],
        "alerts": alerts,
    }


def inventory(scope):
    counts = scope.rows("inventory", "count_week")
    last = max((row.day for row in counts), default=None)
    on_hand = sum(row.data["closing"] for row in counts if row.day == last)
    food_sales, sold_by_week = counted_sales(scope)
    actual, recipes = used(scope, matched=True), recipe_cost(scope)
    counted = counted_weeks(scope)
    waste = scope.rows("inventory", "waste")
    wasted = sum(row.data["cost"] for row in waste)
    places, alerts = [], []
    for place in scope.places():
        sold = counted_sales(scope, place)[0]
        was_used, should = used(scope, place, matched=True), recipe_cost(scope, place)
        logged = sum(
            row.data["cost"]
            for row in scope.rows("inventory", "waste", place)
            if (row.location, monday(row.day)) in counted
        )
        gap = round(percent(was_used, sold) - percent(should, sold), 1) if sold else None
        unexplained = was_used - should - logged
        places.append(
            {
                "location": place,
                "sales": sold,
                "used": was_used,
                "actual": percent(was_used, sold),
                "recipes": percent(should, sold),
                "gap": gap,
                "waste": logged,
                "unexplained": unexplained,
                "_tone": "bad" if gap is not None and gap > FOOD_COST_GAP else "",
            }
        )
        if gap is not None and gap > FOOD_COST_GAP:
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{place}: food cost ran {gap} points above what the recipes say it should be. "
                    f"{money(unexplained)} of stock used is not explained by sales or the waste sheet.",
                }
            )
    categories = {}
    for row in (row for row in counts if (row.location, row.day) in counted):
        entry = categories.setdefault(
            row.data["category"], {"category": row.data["category"], "used": 0, "closing": 0, "recipes": 0, "waste": 0}
        )
        entry["used"] += row.data["opening"] + row.data["purchases"] - row.data["closing"]
        if row.day == last:
            entry["closing"] += row.data["closing"]
    for row in sold_items(scope):
        if row.data["stock"] in categories:
            categories[row.data["stock"]]["recipes"] += row.data["qty"] * row.data["cost"]
    for row in waste:
        if row.data["category"] in categories:
            categories[row.data["category"]]["waste"] += row.data["cost"]
    by_category = [
        {
            **entry,
            "over": entry["used"] - entry["recipes"],
            "over_percent": percent(entry["used"] - entry["recipes"], entry["recipes"]),
        }
        for entry in ranked(categories.values(), "used")
    ]
    reasons = {}
    for row in waste:
        reasons[row.data["reason"]] = reasons.get(row.data["reason"], 0) + row.data["cost"]
    weekly = {}
    for row in (row for row in counts if (row.location, row.day) in counted):
        weekly[row.day] = weekly.get(row.day, 0) + row.data["opening"] + row.data["purchases"] - row.data["closing"]
    trend = [
        {"start": week.isoformat(), "value": percent(value, sold_by_week.get(week, 0)) or 0}
        for week, value in sorted(weekly.items())
    ]
    gap = round(percent(actual, food_sales) - percent(recipes, food_sales), 1) if food_sales else None
    return {
        "tiles": [
            tile("Food cost", percent(actual, food_sales), "percent", f"{money(actual)} of stock used"),
            tile("What the recipes say", percent(recipes, food_sales), "percent", "the dishes sold, at recipe cost"),
            tile(
                "Gap", gap, "points", "used above recipe cost", "bad" if gap is not None and gap > FOOD_COST_GAP else ""
            ),
            tile("Stock on hand", on_hand, "money", f"counted the week of {short(last)}" if last else ""),
        ],
        "series": {"title": "Food cost by week", "kind": "percent", "bucket": "week", "points": trend},
        "bars": [
            {
                "title": "Waste by reason",
                "note": f"{money(wasted)} written on the waste sheets.",
                "kind": "money",
                "rows": ranked([{"name": name, "value": value} for name, value in reasons.items()]),
            },
            {
                "title": "Stock on hand by category",
                "note": "At the last count.",
                "kind": "money",
                "rows": ranked([{"name": c["category"], "value": c["closing"]} for c in by_category]),
            },
        ],
        "tables": [
            {
                "title": "By location",
                "note": f"Stock used is the opening count plus deliveries less the closing count. A gap over {FOOD_COST_GAP:g} points is marked.",
                "columns": [
                    column("location", "Location"),
                    column("sales", "Sales", "money"),
                    column("used", "Stock used", "money"),
                    column("actual", "Food cost", "percent"),
                    column("recipes", "Recipes say", "percent"),
                    column("gap", "Gap", "points"),
                    column("waste", "Waste recorded", "money"),
                    column("unexplained", "Not explained", "money"),
                ],
                "rows": ranked(places, "sales"),
            },
            {
                "title": "By category",
                "note": "Where stock went beyond what the dishes sold account for.",
                "columns": [
                    column("category", "Category"),
                    column("used", "Stock used", "money"),
                    column("recipes", "Recipes say", "money"),
                    column("over", "Used above recipes", "money"),
                    column("over_percent", "Above", "percent"),
                    column("waste", "Waste recorded", "money"),
                ],
                "rows": by_category,
            },
        ],
        "alerts": alerts,
    }


def labour(scope):
    days = scope.rows("labour", "day")
    cost = sum(row.data["cost"] for row in days)
    hours = sum(row.data["kitchen_hours"] + row.data["floor_hours"] + row.data["management_hours"] for row in days)
    overtime = sum(row.data["overtime_hours"] for row in days)
    sold, sold_by_week = staffed_sales(scope)
    places, alerts = [], []
    for place in scope.places():
        rows = scope.rows("labour", "day", place)
        worked = sum(row.data["kitchen_hours"] + row.data["floor_hours"] + row.data["management_hours"] for row in rows)
        planned = sum(row.data["scheduled_hours"] for row in rows)
        extra = sum(row.data["overtime_hours"] for row in rows)
        paid, sales_here = sum(row.data["cost"] for row in rows), staffed_sales(scope, place)[0]
        share, extra_share = percent(staffed_cost(scope, place)[0], sales_here), percent(extra, worked)
        places.append(
            {
                "location": place,
                "cost": paid,
                "share": share,
                "hours": round(worked),
                "per_hour": round(sales_here / worked) if worked else None,
                "planned": round(planned),
                "over_plan": round(worked - planned),
                "overtime": round(extra),
                "overtime_share": extra_share,
                "_tone": "bad" if (share or 0) > LABOUR_LIMIT or (extra_share or 0) > OVERTIME_LIMIT else "",
            }
        )
        if (share or 0) > LABOUR_LIMIT:
            alerts.append(
                {"level": "bad", "text": f"{place}: labour is {share}% of sales, over the {LABOUR_LIMIT:g}% limit."}
            )
        if (extra_share or 0) > OVERTIME_LIMIT:
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{place}: {round(extra)} overtime hours, {extra_share}% of hours worked, and "
                    f"{round(worked - planned)} hours over the rota.",
                }
            )
    roles = [
        {"name": name, "value": round(sum(row.data[key] for row in days))}
        for key, name in (("kitchen_hours", "Kitchen"), ("floor_hours", "Floor"), ("management_hours", "Management"))
    ]
    matched, weekly = staffed_cost(scope)
    return {
        "tiles": [
            tile("Labour cost", cost, "money", f"{round(hours):,} hours worked"),
            tile(
                "Share of sales",
                percent(matched, sold),
                "percent",
                f"limit {LABOUR_LIMIT:g}%",
                "bad" if (percent(matched, sold) or 0) > LABOUR_LIMIT else "",
            ),
            tile("Sales per hour worked", round(sold / hours) if hours else None, "money"),
            tile("Overtime", round(overtime), "hours", f"{percent(overtime, hours)}% of hours"),
        ],
        "series": {
            "title": "Labour as a share of sales, by week",
            "kind": "percent",
            "bucket": "week",
            "points": [
                {"start": week.isoformat(), "value": percent(value, sold_by_week.get(week, 0)) or 0}
                for week, value in sorted(weekly.items())
            ],
        },
        "bars": [
            {"title": "Hours by role", "note": "", "kind": "hours", "rows": ranked(roles)},
            {
                "title": "Tips paid out",
                "note": "Through payroll, not a cost to the business.",
                "kind": "money",
                "rows": ranked(
                    [{"name": place, "value": scope.total("labour", "day", "tips", place)} for place in scope.places()]
                ),
            },
        ],
        "tables": [
            {
                "title": "By location",
                "note": f"Marked where labour passes {LABOUR_LIMIT:g}% of sales or overtime passes {OVERTIME_LIMIT:g}% of hours.",
                "columns": [
                    column("location", "Location"),
                    column("cost", "Labour cost", "money"),
                    column("share", "Share of sales", "percent"),
                    column("hours", "Hours worked", "hours"),
                    column("per_hour", "Sales per hour", "money"),
                    column("planned", "On the rota", "hours"),
                    column("over_plan", "Over the rota", "hours"),
                    column("overtime", "Overtime", "hours"),
                    column("overtime_share", "Overtime share", "percent"),
                ],
                "rows": ranked(places, "cost"),
            }
        ],
        "alerts": alerts,
    }


def cash(scope):
    days = sorted(scope.rows("cash", "day"), key=lambda row: (row.day, row.location))
    expected = sum(row.data["cash_expected"] for row in days)
    counted = sum(row.data["cash_counted"] for row in days)
    cards = sum(row.data["card_sales"] for row in days)
    fees = sum(row.data["card_fees"] for row in days)
    tills, unbanked, settlements, alerts = [], [], [], []
    for row in days:
        out = row.data["cash_counted"] - row.data["cash_expected"]
        if abs(out) > CASH_TOLERANCE:
            tills.append(
                {
                    "date": row.day.isoformat(),
                    "location": row.location,
                    "expected": row.data["cash_expected"],
                    "counted": row.data["cash_counted"],
                    "out": out,
                    "_tone": "bad",
                }
            )
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{row.location}: the till was {money(abs(out))} {'short' if out < 0 else 'over'} on {short(row.day)}.",
                }
            )
        waiting = (scope.end - row.day).days
        if row.data["cash_banked"] is None and waiting > BANKING_DAYS:
            unbanked.append(
                {
                    "date": row.day.isoformat(),
                    "location": row.location,
                    "amount": row.data["cash_counted"],
                    "days": waiting,
                    "_tone": "bad",
                }
            )
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{row.location}: {money(row.data['cash_counted'])} counted on {short(row.day)} has not reached the bank after {waiting} days.",
                }
            )
        elif row.data["cash_banked"] is not None and row.data["cash_banked"] != row.data["cash_counted"]:
            unbanked.append(
                {
                    "date": row.day.isoformat(),
                    "location": row.location,
                    "amount": row.data["cash_counted"] - row.data["cash_banked"],
                    "days": None,
                    "_tone": "bad",
                }
            )
        due = row.data["card_sales"] - row.data["card_fees"]
        if row.data["card_settled"] is not None and row.data["card_settled"] != due:
            short_by = due - row.data["card_settled"]
            settlements.append(
                {
                    "date": row.day.isoformat(),
                    "location": row.location,
                    "due": due,
                    "settled": row.data["card_settled"],
                    "short": short_by,
                    "_tone": "bad",
                }
            )
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{row.location}: the card settlement for {short(row.day)} came in {money(short_by)} under what the till took.",
                }
            )
    pending = sum(row.data["card_sales"] - row.data["card_fees"] for row in days if row.data["card_settled"] is None)
    daily = {}
    for row in days:
        daily[row.day] = daily.get(row.day, 0) + row.data["cash_counted"] - row.data["cash_expected"]
    span = (scope.end - scope.start).days + 1
    points = [
        {
            "start": (scope.start + timedelta(days=n)).isoformat(),
            "value": abs(daily.get(scope.start + timedelta(days=n), 0)),
        }
        for n in range(span)
    ]
    places = [
        {
            "location": place,
            "expected": scope.total("cash", "day", "cash_expected", place),
            "out": scope.total("cash", "day", "cash_counted", place)
            - scope.total("cash", "day", "cash_expected", place),
            "cards": scope.total("cash", "day", "card_sales", place),
            "fees": scope.total("cash", "day", "card_fees", place),
            "fee_rate": percent(
                scope.total("cash", "day", "card_fees", place), scope.total("cash", "day", "card_sales", place)
            ),
        }
        for place in scope.places()
    ]
    return {
        "tiles": [
            tile("Cash taken", expected, "money", f"{len(days)} tills counted"),
            tile(
                "Tills out, in all",
                counted - expected,
                "money",
                f"{len(tills)} more than {money(CASH_TOLERANCE)} out",
                "bad" if tills else "",
            ),
            tile("Card sales", cards, "money", f"{money(fees)} in fees, {percent(fees, cards)}%"),
            tile("Card money still to arrive", pending, "money", "the last days' settlements"),
        ],
        "series": {"title": "Cash out of balance by day", "kind": "money", "bucket": "day", "points": points},
        "bars": [],
        "tables": [
            {
                "title": "Tills that did not balance",
                "note": f"Counted cash more than {money(CASH_TOLERANCE)} away from what the till recorded.",
                "columns": [
                    column("date", "Day", "date"),
                    column("location", "Location"),
                    column("expected", "Till recorded", "money"),
                    column("counted", "Counted", "money"),
                    column("out", "Difference", "money"),
                ],
                "rows": tills,
            },
            {
                "title": "Cash not at the bank",
                "note": f"Counted and not deposited after {BANKING_DAYS} days, or deposited for a different amount.",
                "columns": [
                    column("date", "Counted on", "date"),
                    column("location", "Location"),
                    column("amount", "Amount", "money"),
                    column("days", "Days", "count"),
                ],
                "rows": unbanked,
            },
            {
                "title": "Card settlements that came in short",
                "note": "What reached the bank against card sales less the agreed fees.",
                "columns": [
                    column("date", "Day", "date"),
                    column("location", "Location"),
                    column("due", "Due", "money"),
                    column("settled", "Received", "money"),
                    column("short", "Short", "money"),
                ],
                "rows": settlements,
            },
            {
                "title": "By location",
                "note": "",
                "columns": [
                    column("location", "Location"),
                    column("expected", "Cash taken", "money"),
                    column("out", "Out of balance", "money"),
                    column("cards", "Card sales", "money"),
                    column("fees", "Card fees", "money"),
                    column("fee_rate", "Fee rate", "percent"),
                ],
                "rows": ranked(places, "cards"),
            },
        ],
        "alerts": alerts,
    }


def delivery(scope):
    payouts = scope.rows("delivery", "payout")
    gross = sum(row.data["gross"] for row in payouts)
    commission = sum(row.data["commission"] for row in payouts)
    refunds = sum(row.data["refunds"] for row in payouts)
    received = sum(row.data["payout"] for row in payouts)
    groups, rows = {}, []
    for row in sorted(payouts, key=lambda row: (row.day, row.location, row.data["platform"])):
        agreed = round(row.data["gross"] * row.data["rate_agreed"] / 10000)
        overcharged = row.data["commission"] - agreed
        due = row.data["gross"] - row.data["commission"] - row.data["refunds"]
        short_by = due - row.data["payout"]
        entry = groups.setdefault(
            (row.location, row.data["platform"]),
            {
                "location": row.location,
                "platform": row.data["platform"],
                "orders": 0,
                "gross": 0,
                "commission": 0,
                "agreed_rate": row.data["rate_agreed"] / 100,
                "overcharged": 0,
                "short": 0,
                "refunds": 0,
                "weeks": 0,
            },
        )
        entry["orders"] += row.data["orders"]
        entry["gross"] += row.data["gross"]
        entry["commission"] += row.data["commission"]
        entry["refunds"] += row.data["refunds"]
        entry["overcharged"] += max(0, overcharged)
        entry["short"] += max(0, short_by)
        entry["weeks"] += overcharged > 0
        if overcharged > 0 or short_by > 0:
            rows.append(
                {
                    "week": row.day.isoformat(),
                    "location": row.location,
                    "platform": row.data["platform"],
                    "gross": row.data["gross"],
                    "agreed": row.data["rate_agreed"] / 100,
                    "charged": percent(row.data["commission"], row.data["gross"]),
                    "overcharged": max(0, overcharged),
                    "short": max(0, short_by),
                    "_tone": "bad",
                }
            )
    alerts = []
    for entry in groups.values():
        entry["charged_rate"] = percent(entry["commission"], entry["gross"])
        entry["_tone"] = "bad" if entry["overcharged"] or entry["short"] else ""
        if entry["overcharged"]:
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{entry['location']}: {entry['platform']} took {money(entry['overcharged'])} more commission than the "
                    f"agreed {entry['agreed_rate']:g}% over {entry['weeks']} {'week' if entry['weeks'] == 1 else 'weeks'}.",
                }
            )
        if entry["short"]:
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{entry['location']}: a {entry['platform']} payout came in {money(entry['short'])} under its own statement.",
                }
            )
    platforms = {}
    for row in payouts:
        platforms[row.data["platform"]] = platforms.get(row.data["platform"], 0) + row.data["gross"]
    owed = sum(entry["overcharged"] + entry["short"] for entry in groups.values())
    return {
        "tiles": [
            tile("Delivery sales", gross, "money", f"{sum(row.data['orders'] for row in payouts):,} orders"),
            tile("Commission", commission, "money", f"{percent(commission, gross)}% of delivery sales"),
            tile("Refunds and adjustments", refunds, "money", f"{percent(refunds, gross)}% of delivery sales"),
            tile(
                "To take up with the platforms", owed, "money", f"{money(received)} was paid out", "bad" if owed else ""
            ),
        ],
        "series": {
            "title": "Delivery sales by week",
            "kind": "money",
            "bucket": "week",
            "points": scope.by_week("delivery", "payout", "gross"),
        },
        "bars": [
            {
                "title": "By platform",
                "note": "",
                "kind": "money",
                "rows": ranked([{"name": name, "value": value} for name, value in platforms.items()]),
            }
        ],
        "tables": [
            {
                "title": "Payouts that do not add up",
                "note": "Commission above the agreed rate, or a payout below sales less commission and refunds.",
                "columns": [
                    column("week", "Week of", "date"),
                    column("location", "Location"),
                    column("platform", "Platform"),
                    column("gross", "Sales", "money"),
                    column("agreed", "Agreed rate", "percent"),
                    column("charged", "Charged", "percent"),
                    column("overcharged", "Commission over", "money"),
                    column("short", "Payout short", "money"),
                ],
                "rows": rows,
            },
            {
                "title": "By location and platform",
                "note": "",
                "columns": [
                    column("location", "Location"),
                    column("platform", "Platform"),
                    column("orders", "Orders", "count"),
                    column("gross", "Sales", "money"),
                    column("agreed_rate", "Agreed rate", "percent"),
                    column("charged_rate", "Charged", "percent"),
                    column("refunds", "Refunds", "money"),
                    column("overcharged", "Commission over", "money"),
                ],
                "rows": ranked(groups.values(), "gross"),
            },
        ],
        "alerts": alerts,
    }


def catering(scope):
    events = [row for row in scope.rows("catering", "quote", dated=False)]
    states = {}
    for row in events:
        entry = states.setdefault(row.data["status"], {"name": row.data["status"].capitalize(), "value": 0, "count": 0})
        entry["value"] += row.data["amount"]
        entry["count"] += 1
    done = [row for row in events if row.data["status"] in ("invoiced", "paid") and scope.start <= row.day <= scope.end]
    billed = sum(row.data["amount"] for row in done)
    decided = [row for row in events if row.data["status"] in ("accepted", "invoiced", "paid", "declined")]
    won = [row for row in decided if row.data["status"] != "declined"]
    owing, upcoming, alerts = [], [], []
    for row in sorted(events, key=lambda row: row.day):
        balance = row.data["amount"] - row.data["paid"]
        if row.data["status"] == "invoiced" and balance > 0:
            due = date.fromisoformat(row.data["due"])
            late = (scope.end - due).days
            owing.append(
                {
                    "customer": row.data["customer"],
                    "event": row.data["event"],
                    "location": row.location,
                    "held": row.day.isoformat(),
                    "amount": row.data["amount"],
                    "balance": balance,
                    "due": row.data["due"],
                    "late": late if late > 0 else None,
                    "_tone": "bad" if late > 0 else "",
                }
            )
            if late > 0:
                alerts.append(
                    {
                        "level": "bad",
                        "text": f"{row.data['customer']} owes {money(balance)} for the {row.data['event'].lower()} on {short(row.day)}, {late} days past due.",
                    }
                )
        if row.day > scope.end and row.data["status"] in ("sent", "accepted"):
            unpaid = row.data["status"] == "accepted" and not row.data["paid"]
            upcoming.append(
                {
                    "date": row.day.isoformat(),
                    "customer": row.data["customer"],
                    "event": row.data["event"],
                    "location": row.location,
                    "guests": row.data["guests"],
                    "amount": row.data["amount"],
                    "status": row.data["status"],
                    "deposit": row.data["paid"],
                    "_tone": "warn" if unpaid else "",
                }
            )
            if unpaid and (row.day - scope.end).days <= 14:
                alerts.append(
                    {
                        "level": "warn",
                        "text": f"{row.data['customer']}: the {row.data['event'].lower()} on {short(row.day)} is confirmed with no deposit taken.",
                    }
                )
    outstanding = sum(row["balance"] for row in owing)
    by_week = {}
    for row in done:
        week = row.day - timedelta(days=row.day.weekday())
        by_week[week] = by_week.get(week, 0) + row.data["amount"]
    order = ["Sent", "Accepted", "Invoiced", "Paid", "Declined"]
    return {
        "tiles": [
            tile("Events billed", billed, "money", f"{len(done)} events held this period"),
            tile("Quotes won", percent(len(won), len(decided)), "percent", f"{len(won)} of {len(decided)} decided"),
            tile(
                "Owed by customers",
                outstanding,
                "money",
                f"{sum(bool(row['late']) for row in owing)} past due",
                "bad" if any(row["late"] for row in owing) else "",
            ),
            tile(
                "Booked ahead",
                sum(row["amount"] for row in upcoming if row["status"] == "accepted"),
                "money",
                f"{sum(row['status'] == 'accepted' for row in upcoming)} confirmed events",
            ),
        ],
        "series": {
            "title": "Events billed by week",
            "kind": "money",
            "bucket": "week",
            "points": [{"start": week.isoformat(), "value": value} for week, value in sorted(by_week.items())],
        },
        "bars": [
            {
                "title": "Quotes by where they stand",
                "note": "By value.",
                "kind": "money",
                "rows": sorted(
                    states.values(), key=lambda state: order.index(state["name"]) if state["name"] in order else 9
                ),
            }
        ],
        "tables": [
            {
                "title": "Owed by customers",
                "note": "Events invoiced and not yet paid in full.",
                "columns": [
                    column("customer", "Customer"),
                    column("event", "Event"),
                    column("location", "Location"),
                    column("held", "Held", "date"),
                    column("amount", "Invoiced", "money"),
                    column("balance", "Still owed", "money"),
                    column("due", "Due", "date"),
                    column("late", "Days late", "count"),
                ],
                "rows": owing,
            },
            {
                "title": "Coming up",
                "note": "Quotes out and events confirmed. A confirmed event with no deposit is marked.",
                "columns": [
                    column("date", "Date", "date"),
                    column("customer", "Customer"),
                    column("event", "Event"),
                    column("location", "Location"),
                    column("guests", "Guests", "count"),
                    column("amount", "Value", "money"),
                    column("status", "Status", "badge"),
                    column("deposit", "Deposit taken", "money"),
                ],
                "rows": upcoming,
            },
        ],
        "alerts": alerts,
    }


def accounting(scope):
    lines = [
        ("sales", "Sales"),
        ("goods", "Cost of goods used"),
        ("gross", "Gross profit"),
        ("labour", "Labour"),
        ("commission", "Delivery commission"),
        ("fees", "Card fees"),
        ("rent", "Rent"),
        ("utilities", "Utilities"),
        ("other", "Other running costs"),
        ("profit", "Operating profit"),
    ]
    books = {place: figures(scope, place) for place in scope.places()}
    whole = figures(scope)
    for book in (*books.values(), whole):
        book["gross"] = book["sales"] - book["goods"]
    statement = []
    for key, label in lines:
        row = {
            "line": label,
            "total": whole[key],
            "share": percent(whole[key], whole["sales"]),
            "_tone": "strong" if key in ("sales", "gross", "profit") else "",
        }
        for place, book in books.items():
            row[place] = book[key]
        statement.append(row)
    places = [
        {
            "location": place,
            "sales": book["sales"],
            "food": book["food_percent"],
            "labour": book["labour_percent"],
            "prime": book["prime_percent"],
            "profit": book["profit"],
            "margin": book["margin"],
            "_tone": "bad" if book["profit"] < 0 else "",
        }
        for place, book in books.items()
    ]
    alerts = [
        {"level": "bad", "text": f"{place}: an operating loss of {money(-book['profit'])} over the period."}
        for place, book in books.items()
        if book["profit"] < 0
    ]
    # A profit worked out before all the paperwork is in is too high by whatever is missing.
    waiting = [alert for area in missing(scope).values() for alert in area]
    if waiting:
        alerts.append(
            {
                "level": "warn",
                "text": f"{len(waiting)} documents for this period have not arrived, so costs here are short of the "
                "truth and profit is overstated until they do. Each is listed on its own page.",
            }
        )
    tax = scope.total("sales", "day", "tax")
    weekly = scope.by_week("sales", "day", "net")
    return {
        "tiles": [
            tile("Sales", whole["sales"], "money"),
            tile("Prime cost", whole["prime_percent"], "percent", "goods used and labour, of sales"),
            tile(
                "Operating profit",
                whole["profit"],
                "money",
                f"{whole['margin']}% of sales",
                "bad" if whole["profit"] < 0 else "",
            ),
            tile("Sales tax collected", tax, "money", "held for the tax authority, not income"),
        ],
        "series": {"title": "Sales by week", "kind": "money", "bucket": "week", "points": weekly},
        "bars": [
            {
                "title": "Operating profit by location",
                "note": "",
                "kind": "money",
                "rows": ranked([{"name": place, "value": book["profit"]} for place, book in books.items()]),
            }
        ],
        "tables": [
            {
                "title": "Profit and loss",
                "note": "Worked out from the other areas: sales from the tills, goods from stock counts, labour from timesheets, commission and fees from statements.",
                "columns": [
                    column("line", ""),
                    *(column(place, place, "money") for place in books),
                    column("total", "All", "money"),
                    column("share", "Of sales", "percent"),
                ],
                "rows": statement,
            },
            {
                "title": "By location",
                "note": "",
                "columns": [
                    column("location", "Location"),
                    column("sales", "Sales", "money"),
                    column("food", "Food cost", "percent"),
                    column("labour", "Labour", "percent"),
                    column("prime", "Prime cost", "percent"),
                    column("profit", "Operating profit", "money"),
                    column("margin", "Margin", "percent"),
                ],
                "rows": ranked(places, "sales"),
            },
        ],
        "alerts": alerts,
    }


def compliance(scope):
    papers, alerts = [], []
    current = {}
    for row in scope.rows("compliance", "certificate", dated=False):
        # A renewal is the same document for the same holder with a later date: the earlier one is spent.
        held = (row.location, row.data["name"], row.data["holder"])
        if held not in current or row.day > current[held].day:
            current[held] = row
    for row in sorted(current.values(), key=lambda row: row.day):
        left = (row.day - scope.end).days
        state = "expired" if left < 0 else "expiring" if left <= EXPIRY_DAYS else "current"
        papers.append(
            {
                "name": row.data["name"],
                "holder": row.data["holder"],
                "location": row.location,
                "expires": row.day.isoformat(),
                "days": left,
                "status": state,
                "_tone": "bad" if state == "expired" else "warn" if state == "expiring" else "",
            }
        )
        if state == "expired":
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{row.location}: the {row.data['name'].lower()} ({row.data['holder']}) expired {-left} days ago.",
                }
            )
        elif state == "expiring":
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{row.location}: the {row.data['name'].lower()} ({row.data['holder']}) expires in {left} days.",
                }
            )
    checks = []
    for place in scope.places():
        rows = scope.rows("compliance", "temperature", place)
        due, done, out = (
            sum(r.data["due"] for r in rows),
            sum(r.data["done"] for r in rows),
            sum(r.data["out_of_range"] for r in rows),
        )
        worst = min(rows, key=lambda r: r.data["done"] / r.data["due"], default=None)
        rate = percent(done, due)
        checks.append(
            {
                "location": place,
                "due": due,
                "done": done,
                "rate": rate,
                "out": out,
                "_tone": "bad" if (rate or 100) < CHECKS_DONE else "",
            }
        )
        if worst is not None and percent(worst.data["done"], worst.data["due"]) < CHECKS_DONE:
            alerts.append(
                {
                    "level": "bad",
                    "text": f"{place}: {worst.data['due'] - worst.data['done']} of {worst.data['due']} temperature checks are missing for the week of {short(worst.day)}.",
                }
            )
    repairs = []
    for row in sorted(scope.rows("compliance", "maintenance", dated=False), key=lambda row: row.day):
        waiting = (scope.end - row.day).days
        is_open = row.data["status"] != "done"
        late = is_open and waiting > REPAIR_DAYS
        if is_open or row.day >= scope.start:
            repairs.append(
                {
                    "reported": row.day.isoformat(),
                    "location": row.location,
                    "equipment": row.data["equipment"],
                    "issue": row.data["issue"],
                    "status": row.data["status"],
                    "days": waiting if is_open else None,
                    "estimate": row.data["estimate"],
                    "_tone": "bad" if late else "",
                }
            )
        if late:
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{row.location}: the {row.data['equipment'].lower()} has been waiting {waiting} days ({row.data['issue'].lower()}).",
                }
            )
    open_repairs = [repair for repair in repairs if repair["status"] != "done"]
    all_due, all_done = sum(check["due"] for check in checks), sum(check["done"] for check in checks)
    weekly = {}
    for row in scope.rows("compliance", "temperature"):
        entry = weekly.setdefault(row.day, [0, 0])
        entry[0] += row.data["done"]
        entry[1] += row.data["due"]
    return {
        "tiles": [
            tile(
                "Licences and certificates",
                len(papers),
                "count",
                f"{sum(p['status'] == 'current' for p in papers)} current",
            ),
            tile(
                "Expired or expiring",
                sum(p["status"] != "current" for p in papers),
                "count",
                f"within {EXPIRY_DAYS} days",
                "bad"
                if any(p["status"] == "expired" for p in papers)
                else "warn"
                if any(p["status"] == "expiring" for p in papers)
                else "",
            ),
            tile(
                "Temperature checks on record", percent(all_done, all_due), "percent", f"{all_due - all_done} missing"
            ),
            tile(
                "Repairs waiting",
                len(open_repairs),
                "count",
                f"{money(sum(r['estimate'] for r in open_repairs))} estimated",
            ),
        ],
        "series": {
            "title": "Temperature checks on record, by week",
            "kind": "percent",
            "bucket": "week",
            "points": [
                {"start": week.isoformat(), "value": percent(done, due) or 0}
                for week, (done, due) in sorted(weekly.items())
            ],
        },
        "bars": [],
        "tables": [
            {
                "title": "Licences and certificates",
                "note": f"Soonest to expire first. Expired, or expiring within {EXPIRY_DAYS} days, is marked.",
                "columns": [
                    column("name", "Document"),
                    column("holder", "Held by"),
                    column("location", "Location"),
                    column("expires", "Expires", "date"),
                    column("days", "Days left", "count"),
                    column("status", "Status", "badge"),
                ],
                "rows": papers,
            },
            {
                "title": "Temperature checks",
                "note": f"Fridges, freezers and hot holding, twice a day. Under {CHECKS_DONE:g}% on record is marked.",
                "columns": [
                    column("location", "Location"),
                    column("due", "Due", "count"),
                    column("done", "On record", "count"),
                    column("rate", "Done", "percent"),
                    column("out", "Out of range", "count"),
                ],
                "rows": checks,
            },
            {
                "title": "Repairs",
                "note": f"Open tickets, and those closed this period. Open more than {REPAIR_DAYS} days is marked.",
                "columns": [
                    column("reported", "Reported", "date"),
                    column("location", "Location"),
                    column("equipment", "Equipment"),
                    column("issue", "Issue"),
                    column("status", "Status", "badge"),
                    column("days", "Days open", "count"),
                    column("estimate", "Estimate", "money"),
                ],
                "rows": repairs,
            },
        ],
        "alerts": alerts,
    }


BUILDERS = {
    "sales": sales,
    "purchasing": purchasing,
    "inventory": inventory,
    "labour": labour,
    "cash": cash,
    "delivery": delivery,
    "catering": catering,
    "accounting": accounting,
    "compliance": compliance,
}


def with_missing(build, area):
    """An area's page with the paperwork it is still waiting for added to what its rules found."""

    def built(scope):
        page = build(scope)
        page["alerts"] = page["alerts"] + missing(scope)[area]
        return page

    return built


for _area in ("sales", "cash", "labour", "inventory", "delivery"):
    BUILDERS[_area] = with_missing(BUILDERS[_area], _area)


def overview(scope):
    """The group at a glance, and everything any area's rules say needs somebody."""
    whole = figures(scope)
    places = []
    for place in scope.places():
        book = figures(scope, place)
        places.append(
            {
                "location": place,
                "sales": book["sales"],
                "food": book["food_percent"],
                "labour": book["labour_percent"],
                "prime": book["prime_percent"],
                "profit": book["profit"],
                "margin": book["margin"],
                "_tone": "bad" if book["profit"] < 0 else "",
            }
        )
    attention = []
    for area, build in BUILDERS.items():
        for alert in build(scope)["alerts"]:
            attention.append({**alert, "area": area, "area_title": AREAS[area][0]})
    attention.sort(key=lambda alert: alert["level"] != "bad")
    return {
        "tiles": [
            tile("Sales", whole["sales"], "money"),
            tile("Food cost", whole["food_percent"], "percent", "stock used, of sales"),
            tile("Labour", whole["labour_percent"], "percent", "of sales"),
            tile(
                "Operating profit",
                whole["profit"],
                "money",
                f"{whole['margin']}% of sales",
                "bad" if whole["profit"] < 0 else "",
            ),
        ],
        "series": {
            "title": "Net sales by day",
            "kind": "money",
            "bucket": "day",
            "points": scope.by_day("sales", "day", "net"),
        },
        "bars": [],
        "tables": [
            {
                "title": "By location",
                "note": "",
                "columns": [
                    column("location", "Location"),
                    column("sales", "Sales", "money"),
                    column("food", "Food cost", "percent"),
                    column("labour", "Labour", "percent"),
                    column("prime", "Prime cost", "percent"),
                    column("profit", "Operating profit", "money"),
                    column("margin", "Margin", "percent"),
                ],
                "rows": ranked(places, "sales"),
            }
        ],
        "alerts": attention,
    }


def view(area, rows, location=None, weeks=8):
    """One area's page for a workspace, from its records."""
    scope = Scope(rows, location, weeks)
    built = overview(scope) if area == "overview" else BUILDERS[area](scope)
    return {
        "area": area,
        "title": AREAS[area][0],
        "fed_by": AREAS[area][1],
        "locations": scope.locations,
        "location": scope.location,
        "from": scope.start.isoformat(),
        "to": scope.end.isoformat(),
        "weeks": scope.weeks,
        "sample": any(getattr(row, "source", "sample") == "sample" for row in rows),
        # How much of what the page is worked out from came through an agent reading a document.
        "from_agents": sum(getattr(row, "source", "") == "agent" for row in rows if row.area == AREA_RECORDS.get(area)),
        **built,
    }


# What a catering quote is priced from. A package is dishes and how many of each a guest is served.
PACKAGES = {
    "Lunch buffet": {"Chicken sandwich": 0.6, "Cheeseburger": 0.4, "Caesar salad": 1, "Fries": 1, "Soft drink": 1.5},
    "Seafood supper": {
        "Clam chowder": 1,
        "Fish and chips": 0.5,
        "Grilled salmon": 0.5,
        "Caesar salad": 0.5,
        "Key lime pie": 1,
    },
    "Seated dinner": {"Clam chowder": 1, "Ribeye": 0.5, "Grilled salmon": 0.5, "Caesar salad": 1, "Key lime pie": 1},
}
GUESTS_PER_SERVER, SERVICE_HOURS, SERVER_RATE = 20, 5, 2200
VOLUME = ((100, 10), (50, 5))  # at this many guests, this percent off the food
DEPOSIT_PERCENT = 30


def draft_quote(menu, package, guests, drinks=False):
    """A catering quote from the menu's own prices and recipe costs: menu is each dish's {"price", "cost"} in cents."""
    menu = {dish: (recipe["price"], recipe["cost"]) for dish, recipe in menu.items()}
    servings = dict(PACKAGES[package])
    if drinks:
        servings["Draft beer"] = 2
    lines, food, cost = [], 0, 0
    for dish, each in servings.items():
        if dish not in menu:
            continue
        portions = -(-guests * each // 1)  # rounded up: nobody is served part of a dish
        price, recipe = menu[dish]
        lines.append({"item": dish, "portions": int(portions), "price": price, "amount": int(portions * price)})
        food += int(portions * price)
        cost += int(portions * recipe)
    off = next((percent_off for least, percent_off in VOLUME if guests >= least), 0)
    discount = round(food * off / 100)
    servers = -(-guests // GUESTS_PER_SERVER)
    staff = servers * SERVICE_HOURS * SERVER_RATE
    total = food - discount + staff
    return {
        "package": package,
        "guests": guests,
        "lines": lines,
        "food": food,
        "discount_percent": off,
        "discount": discount,
        "servers": servers,
        "staff": staff,
        "total": total,
        "per_guest": round(total / guests),
        "deposit": round(total * DEPOSIT_PERCENT / 100),
        "cost": cost + staff,
        "margin": percent(total - cost - staff, total),
    }
