"""What becomes of a document an operations agent has read: checked, then written into the records the
operations pages are worked out from.

An agent reads a till report, a cash-up sheet, a payout statement, a timesheet, a stock count, a
catering enquiry or a certificate into a few fields. Everything after that is code, here: whether
the answer can be trusted enough to record, and which OperationsRecord rows it becomes. A document
the checks doubt is held for a person and writes nothing until one approves it. A quote's price is
arithmetic over the menu, not something the agent proposes.

The kind of document an agent reads is told from the shape of its answer, as it is for invoices and
statements, so installing an agent needs nothing declared.
"""

from datetime import date, timedelta

from factory.operations import PACKAGES, draft_quote

# Kind: the answer field that marks it (in a table where noted), what the agent reads, the area it fills.
KINDS = {
    "till": ("net_sales", False, "End-of-day till reports", "sales"),
    "cashup": ("counted_cash", False, "Daily cash-up sheets", "cash"),
    "payout": ("payout", False, "Delivery platform payout statements", "delivery"),
    "timesheet": ("kitchen_hours", True, "Weekly timesheets", "labour"),
    "stockcount": ("closing", True, "Weekly stock count sheets", "inventory"),
    "enquiry": ("package", False, "Catering enquiries", "catering"),
    "certificate": ("expires", False, "Licences and certificates", "compliance"),
}
QUOTE_TERMS_DAYS = 14


def kind_of(properties):
    """The kind of document an answer of this shape comes from, or None for one this module does not record."""
    for kind, (field, in_table, _, _) in KINDS.items():
        if in_table:
            if any(
                field in shape.get("items", {}).get("properties", {})
                for shape in properties.values()
                if shape.get("type") == "array"
            ):
                return kind
        elif field in properties:
            return kind
    return None


def cents(value):
    return round(float(value) * 100)


def day_of(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def table(data):
    """The rows of the answer's one table."""
    return next((value for value in data.values() if isinstance(value, list)), [])


class Masters:
    """What a workspace already knows that a document is checked against: its locations, its menu with
    recipe costs, the stock categories, and the rate agreed with each delivery platform."""

    def __init__(self, rows):
        self.locations = sorted({row.location for row in rows if row.location})
        self.menu = {row.data["item"]: row.data for row in rows if (row.area, row.kind) == ("master", "recipe")}
        self.stock = sorted({recipe["stock"] for recipe in self.menu.values()})
        self.rates = {
            row.data["platform"]: row.data["rate"] for row in rows if (row.area, row.kind) == ("master", "contract")
        }

    def place(self, name):
        """A location as the workspace names it, whatever the capitals and spacing on the document."""
        wanted = " ".join(str(name or "").split()).casefold()
        return next((place for place in self.locations if place.casefold() == wanted), None)


def key(kind, data, masters):
    """What makes two documents the same one: the same day's report for the same place, and so on."""
    place = masters.place(data.get("location")) or str(data.get("location"))
    if kind in ("till", "cashup"):
        return (place, str(data.get("date")))
    if kind == "payout":
        return (place, str(data.get("platform")), str(data.get("week_start")))
    if kind in ("timesheet", "stockcount"):
        return (place, str(data.get("week_start")))
    if kind == "enquiry":
        return (str(data.get("customer")), str(data.get("event")), str(data.get("date")))
    return (place, str(data.get("document")), str(data.get("holder")), str(data.get("expires")))


def check(kind, data, masters, earlier=()):
    """What stops an answer being recorded as it stands. earlier is the answers of the documents before it."""
    try:
        return _check(kind, data, masters, earlier)
    except (KeyError, TypeError, ValueError):
        # An answer without what its kind needs, or with words where a number belongs.
        return [
            {
                "kind": "missing_field",
                "message": "Part of this document could not be read into what is needed to record it.",
            }
        ]


def _check(kind, data, masters, earlier):
    found = []

    def flag(reason, message, **more):
        found.append({"kind": reason, "message": message, **more})

    for field, value in data.items():
        if value is None or (isinstance(value, str) and (not value.strip() or "[illegible]" in value)):
            flag("missing_field", f"The {field.replace('_', ' ')} could not be read.", field=field)
    if found:
        return found
    if masters.place(data.get("location")) is None:
        flag("unknown_location", f"{data.get('location')!r} is not one of your locations.", field="location")
    when = "week_start" if "week_start" in data else "expires" if kind == "certificate" else "date"
    day = day_of(data.get(when))
    if day is None:
        flag("bad_date", f"{data.get(when)!r} is not a date.", field=when)
    elif when == "week_start" and day.weekday() != 0:
        flag("bad_date", f"The week is said to start on {day:%A %B} {day.day}, which is not a Monday.", field=when)
    if kind == "till":
        net = cents(data["net_sales"])
        for parts, name in ((("dine_in", "takeout", "delivery"), "channels"), (("lunch", "dinner"), "services")):
            total = sum(cents(data[part]) for part in parts)
            if abs(total - net) > 1:
                flag(
                    "does_not_add_up",
                    f"The {name} add up to ${total / 100:,.2f} and net sales are ${net / 100:,.2f}. A figure has been misread.",
                )
        unknown = [str(item.get("item")) for item in table(data) if item.get("item") not in masters.menu]
        if unknown:
            flag("unknown_item", f"Not on the menu: {', '.join(unknown[:5])}.")
    elif kind == "payout" and data.get("platform") not in masters.rates:
        flag("unknown_platform", f"There is no agreed rate on file for {data.get('platform')!r}.", field="platform")
    elif kind == "timesheet":
        days = [day_of(row.get("date")) for row in table(data)]
        if len(days) != 7 or None in days or (day and sorted(days) != [day + timedelta(days=n) for n in range(7)]):
            flag("does_not_add_up", "A week's timesheet should have one row for each of its seven days.")
    elif kind == "stockcount":
        unknown = [str(row.get("category")) for row in table(data) if row.get("category") not in masters.stock]
        if unknown:
            flag("unknown_item", f"Not one of your stock categories: {', '.join(unknown[:5])}.")
    elif kind == "enquiry":
        if data.get("package") not in PACKAGES:
            flag(
                "unknown_item",
                f"{data.get('package')!r} is not a package on offer, so it cannot be priced.",
                field="package",
            )
        elif not 5 <= int(data.get("guests") or 0) <= 2000:
            flag("does_not_add_up", f"An event for {data.get('guests')} guests cannot be priced.", field="guests")
    mine = key(kind, data, masters)
    if any(key(kind, other, masters) == mine for other in earlier):
        flag("duplicate", "This has been received before: the same document for the same place and time.")
    return found


def records(kind, data, masters):
    """The operations records one checked answer becomes, as (area, kind, day, location, data)."""
    place = masters.place(data.get("location"))
    if kind == "till":
        day = data["date"]
        made = [
            (
                "sales", "day", day, place,
                {
                    "net": cents(data["net_sales"]), "dine_in": cents(data["dine_in"]), "takeout": cents(data["takeout"]),
                    "delivery": cents(data["delivery"]), "lunch": cents(data["lunch"]), "dinner": cents(data["dinner"]),
                    "covers": int(data["guests"]), "discounts": cents(data["discounts"]), "voids": cents(data["voids"]),
                    "tax": cents(data["sales_tax"]),
                },
            )
        ]  # fmt: skip
        for item in table(data):
            recipe = masters.menu[item["item"]]
            made.append(
                (
                    "sales", "item_week", day, place,
                    {
                        "item": item["item"], "category": recipe["category"], "stock": recipe["stock"],
                        "qty": int(item["quantity"]), "sales": cents(item["sales"]), "cost": recipe["cost"],
                    },
                )
            )  # fmt: skip
        return made
    if kind == "cashup":
        return [
            (
                "cash", "day", data["date"], place,
                {
                    "cash_expected": cents(data["till_cash"]), "cash_counted": cents(data["counted_cash"]),
                    "card_sales": cents(data["card_sales"]), "card_fees": cents(data["card_fees"]),
                    # A sheet with nothing banked or settled yet says so with a zero.
                    "cash_banked": cents(data["banked"]) or None, "card_settled": cents(data["card_settled"]) or None,
                },
            )
        ]  # fmt: skip
    if kind == "payout":
        return [
            (
                "delivery", "payout", data["week_start"], place,
                {
                    "platform": data["platform"], "orders": int(data["orders"]), "gross": cents(data["gross_sales"]),
                    "rate_agreed": masters.rates[data["platform"]], "commission": cents(data["commission"]),
                    "refunds": cents(data["refunds"]), "payout": cents(data["payout"]),
                },
            )
        ]  # fmt: skip
    if kind == "timesheet":
        return [
            (
                "labour", "day", row["date"], place,
                {
                    "kitchen_hours": float(row["kitchen_hours"]), "floor_hours": float(row["floor_hours"]),
                    "management_hours": float(row["management_hours"]), "overtime_hours": float(row["overtime_hours"]),
                    "scheduled_hours": float(row["scheduled_hours"]), "cost": cents(row["labour_cost"]), "tips": cents(row["tips"]),
                },
            )
            for row in table(data)
        ]  # fmt: skip
    if kind == "stockcount":
        return [
            (
                "inventory", "count_week", data["week_start"], place,
                {"category": row["category"], "opening": cents(row["opening"]), "purchases": cents(row["deliveries"]), "closing": cents(row["closing"])},
            )
            for row in table(data)
        ]  # fmt: skip
    if kind == "enquiry":
        quote = draft_quote(
            masters.menu, data["package"], int(data["guests"]), str(data.get("drinks")).lower() == "yes"
        )
        held = day_of(data["date"])
        return [
            (
                "catering", "quote", data["date"], place,
                {
                    "customer": data["customer"], "event": data["event"], "guests": int(data["guests"]), "amount": quote["total"],
                    "status": "sent", "paid": 0, "due": (held + timedelta(days=QUOTE_TERMS_DAYS)).isoformat(),
                    "package": data["package"], "quote": quote,
                },
            )
        ]  # fmt: skip
    return [("compliance", "certificate", data["expires"], place, {"name": data["document"], "holder": data["holder"]})]
