"""The documents the operations agents read, drawn from the sample records.

Harbor Table Group is invented, so its paperwork has to be made: till reports, cash-up sheets,
delivery payout statements, timesheets, stock count sheets, catering enquiries and certificates.
Each is a typed PDF in one of several layouts, with the answer an agent should read from it.

    bash demo/operations/build.sh --documents-only

Writes into demo/operations/data/:

  examples/<kind>-examples.zip   what each agent is built and measured on, with answers
  baseline/<kind>/               the last week's documents, put through the agents when the workspace is built
  live/<kind>/                   documents kept back to upload in front of someone
  held/till/                     one till report with a misprint, to show a document being held
  answers.json                   the answer for every baseline and live document, to check a reading against
  procedures/<kind>.md           the rules each agent is built to follow

The examples come from the first seven weeks and are never the documents the workspace is filled
from. The last week's records are left out of the generated history (see split): that week reaches
the operations pages only through an agent reading these documents.
"""

import io
import json
import random
import zipfile
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sample import END, GROUP, LOCATIONS, MENU, PLATFORMS, START, STOCK, WEEKS, generate

HERE = Path(__file__).parent
DATA = HERE / "data"
STAMP = (2026, 9, 28, 0, 0, 0)
LIVE_WEEK = START + timedelta(days=(WEEKS - 1) * 7)
EXAMPLES = 24
FONTS = (("Helvetica", "Helvetica-Bold"), ("Courier", "Courier-Bold"), ("Times-Roman", "Times-Bold"))
DATES = ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%B %d, %Y", "%m/%d/%y")
MONEY = ("${:,.2f}", "{:,.2f}", "{:.2f}", "$ {:,.2f}")
# Kept out of the workspace when it is built, to upload in front of someone.
LIVE = {
    "till": [("Downtown", END), ("Dockside", END)],
    "cashup": [("Downtown", END), ("Dockside", END)],
    "payout": [("Downtown", "Plate Runner"), ("Dockside", "QuickDish")],
    "timesheet": ["Uptown", "Airport Road"],
    "stockcount": ["Dockside", "Uptown"],
}
REQUESTS = {
    "till": "Record a restaurant's end-of-day till report. You are given the text of the report. Return the location, the date as YYYY-MM-DD, net sales, the sales by channel (dine in, takeout, delivery) and by service (lunch, dinner), the number of guests, discounts, voids and sales tax, all amounts in dollars, and one row for every dish listed: its name, the quantity sold and its sales.",
    "cashup": "Record a restaurant's daily cash-up sheet. You are given the text of the sheet. Return the location, the date as YYYY-MM-DD, the cash the till recorded, the cash counted, card sales, card fees, the amount banked and the card settlement received, all in dollars. Where nothing has been banked or settled yet, return 0 for that amount.",
    "payout": "Record a delivery platform's weekly payout statement to a restaurant. You are given the text of the statement. Return the platform, the restaurant location, the Monday the week starts as YYYY-MM-DD, the number of orders, gross sales, the commission charged, refunds and adjustments, and the amount paid out, all in dollars.",
    "timesheet": "Record a restaurant's weekly timesheet summary. You are given the text of the summary. Return the location, the Monday the week starts as YYYY-MM-DD, and one row for each of the seven days: the date as YYYY-MM-DD, kitchen hours, floor hours, management hours, overtime hours, the hours that were on the rota, labour cost in dollars and tips in dollars.",
    "stockcount": "Record a restaurant's weekly stock count sheet. You are given the text of the sheet. Return the location, the Monday the week starts as YYYY-MM-DD, and one row for every stock category: its name, the opening value, the value of deliveries in the week and the closing value, in dollars.",
    "enquiry": "Record a catering enquiry sent to a restaurant group. You are given the text of the message. Return the customer, a short name for the event, the date of the event as YYYY-MM-DD, the number of guests, the menu package asked for, whether drinks are wanted (yes or no) and the location that would host it.",
    "certificate": "Record a licence or certificate held by a restaurant. You are given the text of the document. Return what the document is, who or what holds it, the restaurant location it belongs to, and the date it expires as YYYY-MM-DD.",
}
NAMES = {
    "till": "Till Report Recorder",
    "cashup": "Cash-up Recorder",
    "payout": "Delivery Payout Recorder",
    "timesheet": "Timesheet Recorder",
    "stockcount": "Stock Count Recorder",
    "enquiry": "Catering Enquiry Recorder",
    "certificate": "Certificate Recorder",
}
# What the customer calls each agent's work.
LABELS = {
    "till": "Daily sales",
    "cashup": "Cash-up and banking",
    "payout": "Delivery payouts",
    "timesheet": "Timesheets",
    "stockcount": "Stock counts",
    "enquiry": "Catering quotes",
    "certificate": "Licences and certificates",
}
COMMON = f"""- **location**: one of our locations, exactly as we name them: {", ".join(f"`{place}`" for place in LOCATIONS)}.
  A document may print it with the group's name in front ("{GROUP} - Downtown") or in capitals; record the location alone.
- Dates are recorded as YYYY-MM-DD, whatever format the document uses.
- Amounts are recorded in dollars as numbers, with no currency sign or thousands separator.
"""
PROCEDURES = {
    "till": f"""# End-of-day till reports

How a location's till report is recorded. Written for this demonstration.

{COMMON}- **net_sales**: sales after discounts and voids, before tax.
- **dine_in**, **takeout**, **delivery**: net sales by channel. They add up to net sales.
- **lunch**, **dinner**: net sales by service. They add up to net sales.
- **guests**: the number of dine-in guests (covers).
- **discounts**, **voids**, **sales_tax**: as printed.
- **items**: one row for every dish in the report's list of what sold, in the order printed:
  **item** (the dish's name exactly as on our menu: {", ".join(MENU)}), **quantity** and **sales**.
""",
    "cashup": f"""# Daily cash-up sheets

How a location's cash-up sheet is recorded. Written for this demonstration.

{COMMON}- **till_cash**: the cash the till says was taken.
- **counted_cash**: the cash counted in the drawer at close.
- **card_sales**, **card_fees**: as printed.
- **banked**: the cash deposited at the bank for this day. 0 when the sheet says it has not been banked yet.
- **card_settled**: the card settlement received from the processor. 0 when the sheet says it is pending.
""",
    "payout": f"""# Delivery platform payout statements

How a platform's weekly payout statement is recorded. Written for this demonstration.

{COMMON}- **platform**: one of the platforms we use, exactly: {", ".join(f"`{name}`" for name in PLATFORMS)}.
- **week_start**: the Monday of the week the statement covers. A statement may give the week as a range or by its last day.
- **orders**: the number of orders.
- **gross_sales**: order value before anything is taken off.
- **commission**: what the platform charged, in dollars, not the rate.
- **refunds**: refunds and adjustments taken off.
- **payout**: the amount paid to us.
""",
    "timesheet": f"""# Weekly timesheet summaries

How a location's weekly timesheet summary is recorded. Written for this demonstration.

{COMMON}- **week_start**: the Monday the week starts.
- **days**: one row for each of the seven days, Monday first: **date**, **kitchen_hours**, **floor_hours**,
  **management_hours**, **overtime_hours**, **scheduled_hours** (the hours on the rota), **labour_cost** and **tips**.
  Not the totals line.
""",
    "stockcount": f"""# Weekly stock count sheets

How a location's weekly stock count is recorded. Written for this demonstration.

{COMMON}- **week_start**: the Monday of the week counted.
- **categories**: one row for every stock category, in the order printed. **category** is exactly one of
  {", ".join(f"`{name}`" for name in STOCK)}; **opening** is the value at the start of the week, **deliveries**
  what came in during it, **closing** the value counted at the end. Not the totals line.
""",
    "enquiry": f"""# Catering enquiries

How a catering enquiry is recorded, so that it can be priced. Written for this demonstration.

{COMMON}- **customer**: the business or family asking, not the person who wrote.
- **event**: a short name for the occasion in the customer's own words, such as `Staff lunch` or `Wedding reception`.
- **date**: the day of the event. Enquiries are for dates in {END.year} unless they say otherwise.
- **guests**: the number of guests, as a whole number.
- **package**: the menu package asked for, exactly one of: `Lunch buffet`, `Seafood supper`, `Seated dinner`.
- **drinks**: `yes` if they ask for beer or drinks to be included, otherwise `no`.
""",
    "certificate": f"""# Licences and certificates

How a licence or certificate is recorded, so its expiry can be watched. Written for this demonstration.

{COMMON}- **document**: what it is, in sentence case, one of: `Food service licence`, `Liquor licence`,
  `Fire inspection certificate`, `Kitchen hood cleaning certificate`, `Food handler card`,
  `Food protection manager certificate`.
- **holder**: `The premises` for a document issued to the location itself. For one issued to a member of staff,
  their job title as printed (such as `Sous chef`), not their name.
- **expires**: the date it expires or is next due, not the date it was issued.
""",
}


class Sheet:
    """One page being drawn: lines of labelled values, tables and paragraphs, in a font and spacing chosen per document."""

    def __init__(self, rng):
        self.rng = rng
        self.font, self.bold = rng.choice(FONTS)
        self.size = rng.choice((9, 10, 11))
        self.step = self.size + rng.choice((5, 6, 8))
        self.shape = rng.choice(DATES)
        self.cash = rng.choice(MONEY)
        self.buffer = io.BytesIO()
        self.page = canvas.Canvas(self.buffer, pagesize=letter, invariant=1)
        self.y = 742

    def day(self, value):
        return (date.fromisoformat(value) if isinstance(value, str) else value).strftime(self.shape)

    def money(self, value):
        return self.cash.format(value)

    def line(self, text, bold=False, size=0, indent=0):
        if self.y < 60:
            self.page.showPage()
            self.y = 742
        self.page.setFont(self.bold if bold else self.font, self.size + size)
        self.page.drawString(60 + indent, self.y, str(text))
        self.y -= self.step + size

    def gap(self, lines=1):
        self.y -= self.step * lines * 0.6

    def pairs(self, pairs):
        """Labelled values: one to a line, the value in a column of its own."""
        for label, value in pairs:
            if self.y < 60:
                self.page.showPage()
                self.y = 742
            self.page.setFont(self.font, self.size)
            self.page.drawString(60, self.y, f"{label}:")
            self.page.drawString(290, self.y, str(value))
            self.y -= self.step

    def table(self, headings, rows, total=None):
        width = 500 // len(headings)
        at = [60 + index * width for index in range(len(headings))]
        for text, x in zip(headings, at, strict=True):
            self.page.setFont(self.bold, self.size)
            self.page.drawString(x, self.y, str(text))
        self.y -= self.step
        for row in rows + ([total] if total else []):
            if self.y < 60:
                self.page.showPage()
                self.y = 742
            self.page.setFont(self.bold if row is total else self.font, self.size)
            for text, x in zip(row, at, strict=True):
                self.page.drawString(x, self.y, str(text))
            self.y -= self.step

    def paragraph(self, text, width=88):
        words, current = text.split(), ""
        for word in words:
            if len(current) + len(word) + 1 > width:
                self.line(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            self.line(current)

    def done(self):
        self.page.save()
        return self.buffer.getvalue()


def site(place, rng):
    """A location as documents print it: sometimes alone, sometimes with the group's name, sometimes in capitals."""
    return rng.choice((place, f"{GROUP} - {place}", place.upper(), f"{GROUP}, {place}"))


def dollars(cents):
    return round(cents / 100, 2)


def week_text(monday, sheet, rng):
    sunday = monday + timedelta(days=6)
    return rng.choice(
        (
            f"Week commencing {sheet.day(monday)}",
            f"{sheet.day(monday)} to {sheet.day(sunday)}",
            f"Week of Monday {sheet.day(monday)}",
            f"Week ending Sunday {sheet.day(sunday)}",
        )
    )


def till(place, day, row, items, rng):
    sheet = Sheet(rng)
    answer = {
        "location": place,
        "date": day.isoformat(),
        "net_sales": dollars(row["net"]),
        "dine_in": dollars(row["dine_in"]),
        "takeout": dollars(row["takeout"]),
        "delivery": dollars(row["delivery"]),
        "lunch": dollars(row["lunch"]),
        "dinner": dollars(row["dinner"]),
        "guests": row["covers"],
        "discounts": dollars(row["discounts"]),
        "voids": dollars(row["voids"]),
        "sales_tax": dollars(row["tax"]),
        "items": [{"item": name, "quantity": qty, "sales": dollars(sales)} for name, qty, sales in items],
    }
    sheet.line(rng.choice(("END OF DAY REPORT", "Daily Sales Summary", "Z REPORT", "Close of Day")), bold=True, size=4)
    sheet.line(site(place, rng))
    sheet.line(f"{rng.choice(('Business date', 'Date', 'Trading day'))}: {sheet.day(day)}")
    sheet.gap()
    channels = [
        (rng.choice(("Dine in", "Dine-in", "Eat in")), answer["dine_in"]),
        (rng.choice(("Takeout", "Take-out", "To go")), answer["takeout"]),
        ("Delivery", answer["delivery"]),
    ]
    services = [("Lunch", answer["lunch"]), ("Dinner", answer["dinner"])]
    blocks = [
        ("Sales by channel", channels),
        ("Sales by service", services),
        (
            "Adjustments",
            [
                ("Discounts", answer["discounts"]),
                ("Voids", answer["voids"]),
                (rng.choice(("Sales tax", "Tax collected")), answer["sales_tax"]),
            ],
        ),
    ]
    rng.shuffle(blocks)
    net = (rng.choice(("NET SALES", "Net sales", "Total net sales")), sheet.money(answer["net_sales"]))
    guests = (rng.choice(("Guests", "Covers", "Guest count")), answer["guests"])
    if rng.random() < 0.5:
        sheet.pairs([net, guests])
        sheet.gap()
    for title, values in blocks:
        sheet.line(title, bold=True)
        sheet.pairs([(label, sheet.money(value)) for label, value in values])
        sheet.gap()
    return sheet, answer, net, guests


def draw_till(place, day, row, items, rng):
    sheet, answer, net, guests = till(place, day, row, items, rng)
    sheet.line(rng.choice(("Items sold", "Product mix", "What sold")), bold=True)
    sheet.table(
        ["Item", "Qty", "Sales"],
        [[item["item"], item["quantity"], sheet.money(item["sales"])] for item in answer["items"]],
    )
    sheet.gap()
    sheet.pairs([net, guests])
    return sheet.done(), answer


def draw_cashup(place, day, row, rng):
    sheet = Sheet(rng)
    answer = {
        "location": place,
        "date": day.isoformat(),
        "till_cash": dollars(row["cash_expected"]),
        "counted_cash": dollars(row["cash_counted"]),
        "card_sales": dollars(row["card_sales"]),
        "card_fees": dollars(row["card_fees"]),
        "banked": dollars(row["cash_banked"] or 0),
        "card_settled": dollars(row["card_settled"] or 0),
    }
    sheet.line(rng.choice(("DAILY CASH-UP", "Cash Up Sheet", "End of Day Cash Reconciliation")), bold=True, size=4)
    sheet.pairs([(rng.choice(("Location", "Site", "Restaurant")), site(place, rng)), ("Date", sheet.day(day))])
    sheet.gap()
    cash = [
        (rng.choice(("Cash per till", "Till cash total", "Cash recorded by till")), sheet.money(answer["till_cash"])),
        (rng.choice(("Cash counted", "Cash in drawer", "Counted cash")), sheet.money(answer["counted_cash"])),
        (
            rng.choice(("Difference", "Over / short")),
            sheet.money(round(answer["counted_cash"] - answer["till_cash"], 2)),
        ),
        (
            rng.choice(("Banked", "Deposit made", "Cash deposited")),
            sheet.money(answer["banked"])
            if answer["banked"]
            else rng.choice(("not yet banked", "NOT BANKED", "awaiting deposit")),
        ),
    ]
    cards = [
        ("Card sales", sheet.money(answer["card_sales"])),
        (rng.choice(("Card fees", "Processor fees")), sheet.money(answer["card_fees"])),
        (
            rng.choice(("Card settlement received", "Settled to bank", "Settlement")),
            sheet.money(answer["card_settled"])
            if answer["card_settled"]
            else rng.choice(("pending", "PENDING", "not yet received")),
        ),
    ]
    for title, values in rng.sample((("Cash", cash), ("Cards", cards)), 2):
        sheet.line(title, bold=True)
        sheet.pairs(values)
        sheet.gap()
    sheet.line(f"Counted by: {rng.choice(('duty manager', 'closing manager', 'shift lead'))}")
    return sheet.done(), answer


def draw_payout(place, monday, row, rng):
    sheet = Sheet(rng)
    answer = {
        "platform": row["platform"],
        "location": place,
        "week_start": monday.isoformat(),
        "orders": row["orders"],
        "gross_sales": dollars(row["gross"]),
        "commission": dollars(row["commission"]),
        "refunds": dollars(row["refunds"]),
        "payout": dollars(row["payout"]),
    }
    sheet.line(row["platform"], bold=True, size=6)
    sheet.line(rng.choice(("Weekly Payout Statement", "Partner Payout Summary", "Remittance Advice")), bold=True)
    sheet.gap()
    sheet.pairs(
        [
            (rng.choice(("Partner", "Restaurant", "Merchant")), site(place, rng)),
            ("Period", week_text(monday, sheet, rng)),
        ]
    )
    sheet.gap()
    rate = row["commission"] / row["gross"] * 100
    sheet.pairs(
        [
            (rng.choice(("Orders", "Completed orders", "Number of orders")), answer["orders"]),
            (rng.choice(("Gross sales", "Order value", "Gross order value")), sheet.money(answer["gross_sales"])),
            (
                f"{rng.choice(('Commission', 'Service fee', 'Platform commission'))} ({rate:.1f}%)",
                "-" + sheet.money(answer["commission"]),
            ),
            (
                rng.choice(("Refunds and adjustments", "Customer refunds", "Adjustments")),
                "-" + sheet.money(answer["refunds"]),
            ),
        ]
    )
    sheet.gap()
    sheet.pairs([(rng.choice(("PAYOUT", "Net payout", "Amount paid to you")), sheet.money(answer["payout"]))])
    sheet.gap()
    sheet.line("Paid by bank transfer. Queries within 14 days of this statement.")
    return sheet.done(), answer


def draw_timesheet(place, monday, days, rng):
    sheet = Sheet(rng)
    answer = {
        "location": place,
        "week_start": monday.isoformat(),
        "days": [
            {
                "date": day.isoformat(),
                "kitchen_hours": row["kitchen_hours"],
                "floor_hours": row["floor_hours"],
                "management_hours": row["management_hours"],
                "overtime_hours": row["overtime_hours"],
                "scheduled_hours": row["scheduled_hours"],
                "labour_cost": dollars(row["cost"]),
                "tips": dollars(row["tips"]),
            }
            for day, row in days
        ],
    }
    sheet.size = min(sheet.size, 9)
    sheet.line(rng.choice(("WEEKLY TIMESHEET SUMMARY", "Labour Summary", "Payroll Hours Summary")), bold=True, size=4)
    sheet.pairs([("Location", site(place, rng)), ("Period", week_text(monday, sheet, rng))])
    sheet.gap()
    rows = [
        [
            sheet.day(day),
            row["kitchen_hours"],
            row["floor_hours"],
            row["management_hours"],
            row["overtime_hours"],
            row["scheduled_hours"],
            sheet.money(dollars(row["cost"])),
            sheet.money(dollars(row["tips"])),
        ]
        for day, row in days
    ]
    total = [
        "Total",
        *(
            round(sum(row[key] for _, row in days), 1)
            for key in ("kitchen_hours", "floor_hours", "management_hours", "overtime_hours", "scheduled_hours")
        ),
        sheet.money(dollars(sum(row["cost"] for _, row in days))),
        sheet.money(dollars(sum(row["tips"] for _, row in days))),
    ]
    sheet.table(
        [
            "Day",
            "Kitchen",
            "Floor",
            "Mgmt",
            "Overtime",
            rng.choice(("Rota", "Scheduled")),
            rng.choice(("Cost", "Labour cost")),
            "Tips",
        ],
        rows,
        total,
    )
    sheet.gap()
    sheet.line("Hours are hours worked. Overtime is included in the hours of its role.")
    return sheet.done(), answer


def draw_stockcount(place, monday, counts, rng):
    sheet = Sheet(rng)
    answer = {
        "location": place,
        "week_start": monday.isoformat(),
        "categories": [
            {
                "category": row["category"],
                "opening": dollars(row["opening"]),
                "deliveries": dollars(row["purchases"]),
                "closing": dollars(row["closing"]),
            }
            for row in counts
        ],
    }
    sheet.line(rng.choice(("STOCK COUNT SHEET", "Weekly Inventory Count", "Stock Take Summary")), bold=True, size=4)
    sheet.pairs(
        [
            (rng.choice(("Location", "Site")), site(place, rng)),
            ("Week", week_text(monday, sheet, rng)),
            ("Counted by", rng.choice(("kitchen manager", "sous chef", "head chef"))),
        ]
    )
    sheet.gap()
    rows = [
        [row["category"], sheet.money(row["opening"]), sheet.money(row["deliveries"]), sheet.money(row["closing"])]
        for row in answer["categories"]
    ]
    total = [
        "Total",
        *(
            sheet.money(round(sum(row[key] for row in answer["categories"]), 2))
            for key in ("opening", "deliveries", "closing")
        ),
    ]
    sheet.table(
        [
            "Category",
            rng.choice(("Opening", "Opening stock")),
            rng.choice(("Deliveries", "Received", "Purchases")),
            rng.choice(("Closing", "Closing count")),
        ],
        rows,
        total,
    )
    sheet.gap()
    sheet.line("Values at cost. Deliveries are goods received in the week.")
    return sheet.done(), answer


PEOPLE = ("Dana", "Priya", "Marcus", "Elena", "Tom", "Aisha", "Ravi", "Hannah", "Luis", "Mei")
CUSTOMERS = (
    ("Lakeshore Dental Group", "Staff lunch"), ("Marlow & Finch Architects", "Client dinner"), ("Riverbend Rowing Club", "Awards banquet"),
    ("Westfield Primary PTA", "Fundraiser supper"), ("Hollis Family", "Rehearsal dinner"), ("Corbin Freight", "Board lunch"),
    ("Skyline Charter", "Crew dinner"), ("Pembroke Yacht Sales", "Launch party"), ("Juniper Yoga Studio", "Anniversary lunch"),
    ("Ashby & Lowe Solicitors", "Partners' dinner"), ("Northside Credit Union", "Staff appreciation lunch"), ("Okafor Family", "Wedding reception"),
    ("Brightwater School", "Teachers' dinner"), ("Halden Insurance", "Quarterly dinner"), ("Tessellate Software", "Offsite lunch"),
    ("Fernhill Garden Centre", "Spring open evening"), ("Castellan Brewing", "Tap takeover supper"), ("Quarry Lane Dance Academy", "Recital supper"),
)  # fmt: skip
PACKS = ("Lunch buffet", "Seafood supper", "Seated dinner")


def draw_enquiry(customer, event, place, held, guests, package, drinks, rng):
    sheet = Sheet(rng)
    answer = {
        "customer": customer,
        "event": event,
        "date": held.isoformat(),
        "guests": guests,
        "package": package,
        "drinks": "yes" if drinks else "no",
        "location": place,
    }
    person = rng.choice(PEOPLE)
    when = held.strftime(rng.choice(("%A %B %d", "%d %B", "%B %d, %Y", "%m/%d/%Y")))
    sheet.line(f"From: {person.lower()}@{''.join(ch for ch in customer.lower() if ch.isalpha())[:14]}.example")
    sheet.line("To: events@harbortable.example")
    sheet.line(f"Subject: {rng.choice(('Catering enquiry', 'Event booking', 'Private dining request', event))}")
    sheet.gap()
    drink = (
        rng.choice(
            (
                "We would like beer included for everyone.",
                "Please include drinks, a couple of beers each.",
                "Could you add beer to that as well?",
            )
        )
        if drinks
        else rng.choice(("No drinks needed, we will sort those ourselves.", "Food only please, no drinks.", ""))
    )
    body = rng.choice(
        (
            f"Hello, I am writing on behalf of {customer}. We are planning our {event.lower()} for {when} and would like to hold it at your {place} restaurant. There will be {guests} of us. We liked the look of the {package} package. {drink} Could you send a quote?",
            f"Hi there, {customer} would like to book the {package} for {guests} guests on {when}, at {place} if it is free. It is for our {event.lower()}. {drink} Please let me know the cost.",
            f"Good morning. Could you quote for a {event.lower()} for {customer}? Date: {when}. Guests: {guests}. Venue: {GROUP}, {place}. Menu: {package}. {drink} Many thanks.",
        )
    )
    sheet.paragraph(body)
    sheet.gap()
    sheet.line(rng.choice(("Kind regards,", "Thanks,", "Best,")))
    sheet.line(person)
    return sheet.done(), answer


AUTHORITIES = {
    "Food service licence": "County Environmental Health Department",
    "Liquor licence": "State Alcohol Licensing Board",
    "Fire inspection certificate": "City Fire Marshal's Office",
    "Kitchen hood cleaning certificate": "Cleanline Exhaust Services",
    "Food handler card": "County Food Safety Programme",
    "Food protection manager certificate": "National Food Safety Council",
}
ROLES = ("Sous chef", "Line cook", "Prep cook", "Kitchen manager", "Head chef", "Shift supervisor")


def draw_certificate(place, name, holder, expires, rng):
    sheet = Sheet(rng)
    answer = {"document": name, "holder": holder, "location": place, "expires": expires.isoformat()}
    issued = expires - timedelta(days=rng.choice((365, 365, 730, 1095)))
    sheet.line(AUTHORITIES[name], bold=True, size=3)
    sheet.gap()
    sheet.line(rng.choice((name.upper(), name, f"Certificate: {name}")), bold=True, size=5)
    sheet.gap()
    staff = holder != "The premises"
    who = f"{rng.choice(PEOPLE)} {rng.choice(('Okoye', 'Lindqvist', 'Marsh', 'Tanaka', 'Rossi', 'Abara'))}"
    pairs = [
        (
            rng.choice(("Certificate no.", "Licence number", "Reference")),
            f"{rng.choice('ABCDEFGH')}{rng.randrange(100000, 999999)}",
        ),
        *(
            [
                ("Issued to", who),
                (rng.choice(("Position", "Job title", "Role")), holder),
                ("Employer", site(place, rng)),
            ]
            if staff
            else [(rng.choice(("Premises", "Issued to", "Establishment")), site(place, rng))]
        ),
        (
            rng.choice(
                (
                    "Date issued",
                    "Issued",
                    "Date of inspection" if "inspection" in name or "cleaning" in name else "Issue date",
                )
            ),
            sheet.day(issued),
        ),
        (
            rng.choice(
                ("Expires", "Valid until", "Expiry date", "Next due" if "cleaning" in name else "Expiration date")
            ),
            sheet.day(expires),
        ),
    ]
    sheet.pairs(pairs)
    sheet.gap()
    sheet.paragraph(
        "This document must be kept on the premises and shown to an inspector on request. It is not transferable."
    )
    return sheet.done(), answer


def split(records):
    """The generated history the workspace starts with, and the documents the rest reaches it through.

    Left out of the history: the last week's sales, cash, payouts, labour and stock counts, every
    certificate, and the quotes not yet answered. Those come only from an agent reading a document.
    """

    def live(row):
        day = date.fromisoformat(row["day"])
        return (
            (
                (row["area"], row["kind"])
                in (
                    ("sales", "day"),
                    ("sales", "item_week"),
                    ("cash", "day"),
                    ("delivery", "payout"),
                    ("labour", "day"),
                    ("inventory", "count_week"),
                )
                and day >= LIVE_WEEK
            )
            or (row["area"], row["kind"]) == ("compliance", "certificate")
            or ((row["area"], row["kind"]) == ("catering", "quote") and row["data"]["status"] == "sent")
        )

    return [row for row in records if not live(row)], [row for row in records if live(row)]


def documents(seed="harbor-table-docs-1"):
    """Every document, as (kind, set, file name, PDF, answer): set is "examples", "baseline" or "live"."""
    records = generate()
    by = {}
    for row in records:
        by.setdefault((row["area"], row["kind"]), []).append(row)
    out = []
    rng = random.Random(seed)

    def add(kind, where, name, made):
        out.append((kind, where, name, *made))

    def chosen(items):
        """About EXAMPLES of the items, spread evenly, in an order that mixes the locations."""
        items = sorted(items, key=lambda item: json.dumps(item[0], default=str))
        picked = (
            [items[round(index * (len(items) - 1) / (EXAMPLES - 1))] for index in range(EXAMPLES)]
            if len(items) > EXAMPLES
            else items
        )
        rng.shuffle(picked)
        return picked

    def daily_items(place, day, net):
        return [
            (dish, round(net * share * rng.uniform(0.94, 1.06) / price), 0)
            for dish, (_, _, price, _, share) in MENU.items()
        ]

    # Till reports and cash-up sheets: one for each location and day.
    sold = {(row["location"], row["day"]): row["data"] for row in by[("sales", "day")]}
    live_items = {}
    for row in by[("sales", "item_week")]:
        if date.fromisoformat(row["day"]) >= LIVE_WEEK:
            live_items.setdefault((row["location"], row["day"]), []).append(
                (row["data"]["item"], row["data"]["qty"], row["data"]["sales"])
            )
    earlier = [((place, day), data) for (place, day), data in sold.items() if date.fromisoformat(day) < LIVE_WEEK]
    for index, ((place, day), data) in enumerate(chosen(earlier)):
        items = [(dish, qty, qty * MENU[dish][2]) for dish, qty, _ in daily_items(place, day, data["net"])]
        add(
            "till", "examples", f"till_{index + 1:03d}.pdf", draw_till(place, date.fromisoformat(day), data, items, rng)
        )
    for (place, day), items in sorted(live_items.items()):
        when = date.fromisoformat(day)
        where = "live" if (place, when) in LIVE["till"] else "baseline"
        add("till", where, f"Till report {place} {day}.pdf", draw_till(place, when, sold[(place, day)], items, rng))
    cash = {(row["location"], row["day"]): row["data"] for row in by[("cash", "day")]}
    for index, ((place, day), data) in enumerate(
        chosen([(key, data) for key, data in cash.items() if date.fromisoformat(key[1]) < LIVE_WEEK])
    ):
        add("cashup", "examples", f"cashup_{index + 1:03d}.pdf", draw_cashup(place, date.fromisoformat(day), data, rng))
    for (place, day), data in sorted(cash.items()):
        when = date.fromisoformat(day)
        if when >= LIVE_WEEK:
            add(
                "cashup",
                "live" if (place, when) in LIVE["cashup"] else "baseline",
                f"Cash-up {place} {day}.pdf",
                draw_cashup(place, when, data, rng),
            )

    payouts = [
        ((row["location"], row["day"], row["data"]["platform"]), row["data"]) for row in by[("delivery", "payout")]
    ]
    for index, ((place, day, _), data) in enumerate(
        chosen([item for item in payouts if date.fromisoformat(item[0][1]) < LIVE_WEEK])
    ):
        add("payout", "examples", f"payout_{index + 1:03d}.pdf", draw_payout(place, date.fromisoformat(day), data, rng))
    for (place, day, platform), data in sorted(payouts):
        if date.fromisoformat(day) >= LIVE_WEEK:
            where = "live" if (place, platform) in LIVE["payout"] else "baseline"
            add(
                "payout",
                where,
                f"{platform} payout {place} {day}.pdf",
                draw_payout(place, date.fromisoformat(day), data, rng),
            )

    weeks = {}
    for row in by[("labour", "day")]:
        day = date.fromisoformat(row["day"])
        weeks.setdefault((row["location"], day - timedelta(days=day.weekday())), []).append((day, row["data"]))
    for index, ((place, monday), days) in enumerate(
        chosen([(key, days) for key, days in weeks.items() if key[1] < LIVE_WEEK])
    ):
        add("timesheet", "examples", f"timesheet_{index + 1:03d}.pdf", draw_timesheet(place, monday, sorted(days), rng))
    for (place, monday), days in sorted(weeks.items()):
        if monday >= LIVE_WEEK:
            add(
                "timesheet",
                "live" if place in LIVE["timesheet"] else "baseline",
                f"Timesheet {place} {monday}.pdf",
                draw_timesheet(place, monday, sorted(days), rng),
            )

    counts = {}
    for row in by[("inventory", "count_week")]:
        counts.setdefault((row["location"], date.fromisoformat(row["day"])), []).append(row["data"])
    for index, ((place, monday), rows) in enumerate(
        chosen([(key, rows) for key, rows in counts.items() if key[1] < LIVE_WEEK])
    ):
        add("stockcount", "examples", f"stockcount_{index + 1:03d}.pdf", draw_stockcount(place, monday, rows, rng))
    for (place, monday), rows in sorted(counts.items()):
        if monday >= LIVE_WEEK:
            add(
                "stockcount",
                "live" if place in LIVE["stockcount"] else "baseline",
                f"Stock count {place} {monday}.pdf",
                draw_stockcount(place, monday, rows, rng),
            )

    # Catering enquiries: invented for the examples; the workspace's are its unanswered quotes, and two more kept back.
    for index in range(EXAMPLES):
        customer, event = rng.choice(CUSTOMERS)
        held = END + timedelta(days=rng.randrange(5, 80))
        add(
            "enquiry",
            "examples",
            f"enquiry_{index + 1:03d}.pdf",
            draw_enquiry(
                customer,
                event,
                rng.choice(list(LOCATIONS)),
                held,
                rng.choice((20, 25, 30, 40, 45, 60, 80, 100, 120, 150)),
                rng.choice(PACKS),
                rng.random() < 0.5,
                rng,
            ),
        )
    for row in sorted(
        (row for row in by[("catering", "quote")] if row["data"]["status"] == "sent"), key=lambda row: row["day"]
    ):
        data = row["data"]
        pack = PACKS[len(data["customer"]) % 3]
        add(
            "enquiry",
            "baseline",
            f"Enquiry {data['customer']}.pdf",
            draw_enquiry(
                data["customer"],
                data["event"],
                row["location"],
                date.fromisoformat(row["day"]),
                data["guests"],
                pack,
                data["guests"] >= 100,
                rng,
            ),
        )
    for customer, event, place, ahead, guests, pack, drinks in (
        ("Fernhill Garden Centre", "Spring open evening", "Uptown", 33, 70, "Seafood supper", True),
        ("Castellan Brewing", "Tap takeover supper", "Dockside", 21, 110, "Seated dinner", False),
    ):
        add(
            "enquiry",
            "live",
            f"Enquiry {customer}.pdf",
            draw_enquiry(customer, event, place, END + timedelta(days=ahead), guests, pack, drinks, rng),
        )

    # Certificates: invented for the examples; the workspace's sixteen, and two renewals kept back.
    for index in range(EXAMPLES):
        name = rng.choice(list(AUTHORITIES))
        holder = rng.choice(ROLES) if "handler" in name or "manager" in name else "The premises"
        add(
            "certificate",
            "examples",
            f"certificate_{index + 1:03d}.pdf",
            draw_certificate(
                rng.choice(list(LOCATIONS)), name, holder, END + timedelta(days=rng.randrange(-60, 700)), rng
            ),
        )
    for row in sorted(by[("compliance", "certificate")], key=lambda row: (row["location"], row["data"]["name"])):
        add(
            "certificate",
            "baseline",
            f"{row['data']['name']} {row['location']} {row['data']['holder']}.pdf",
            draw_certificate(
                row["location"], row["data"]["name"], row["data"]["holder"], date.fromisoformat(row["day"]), rng
            ),
        )
    for place, name, holder, left in (
        ("Dockside", "Kitchen hood cleaning certificate", "The premises", 172),
        ("Airport Road", "Food handler card", "Prep cook", 1103),
    ):
        add(
            "certificate",
            "live",
            f"Renewed {name.lower()} {place}.pdf",
            draw_certificate(place, name, holder, END + timedelta(days=left), rng),
        )
    # One till report with a misprint, to show a document being held: its delivery sales are $300 too high, so
    # the channels no longer add up to net sales. Drawn last and from a stream of its own, so adding it changed
    # no other document.
    place, when = LIVE["till"][0]
    wrong = {**sold[(place, when.isoformat())]}
    wrong["delivery"] += 30000
    add(
        "till",
        "held",
        f"Till report {place} {when} misprinted.pdf",
        draw_till(place, when, wrong, live_items[(place, when.isoformat())], random.Random(seed + "-held")),
    )
    return out


def write():
    made = documents()
    answers = {}
    for folder in ("examples", "baseline", "live", "held", "procedures"):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    for kind in REQUESTS:
        (DATA / "procedures" / f"{kind}.md").write_text(PROCEDURES[kind])
        rows = []
        with zipfile.ZipFile(DATA / "examples" / f"{kind}-examples.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for _, where, name, pdf, answer in (item for item in made if item[0] == kind):
                if where == "examples":
                    archive.writestr(zipfile.ZipInfo(f"documents/{name}", STAMP), pdf, zipfile.ZIP_DEFLATED)
                    rows.append(
                        json.dumps(
                            {
                                "document": f"documents/{name}",
                                **{f"expected_{field}": value for field, value in answer.items()},
                            }
                        )
                    )
                else:
                    (DATA / where / kind).mkdir(parents=True, exist_ok=True)
                    (DATA / where / kind / name).write_bytes(pdf)
                    answers[f"{where}/{kind}/{name}"] = answer
            archive.writestr(zipfile.ZipInfo("examples.jsonl", STAMP), "\n".join(rows) + "\n", zipfile.ZIP_DEFLATED)
        counted = {
            where: sum(1 for item in made if item[0] == kind and item[1] == where)
            for where in ("examples", "baseline", "live")
        }
        print(f"{kind}: {counted}")
    (DATA / "answers.json").write_text(json.dumps(answers, indent=1) + "\n")
    return made


if __name__ == "__main__":
    write()
