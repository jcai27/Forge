"""Sample records for a restaurant group that does not exist, for showing the operations pages.

Harbor Table Group is invented: four locations, eight weeks. Its suppliers, delivery platforms and
customers are invented too, and no real company is named. The figures are drawn from one model of a
restaurant's week so the areas agree with each other: the dishes sold decide what stock should have
been used, sales decide the cash in the till and the hours worked, delivery sales decide the payouts.

A few things are made to go wrong, because a page with nothing to find shows nothing: one location
uses more seafood than its sales explain, one runs on overtime, a till comes up short twice, a
deposit is late, a delivery platform charges above its agreed rate, a customer has not paid, a
licence has lapsed. None of them is marked in the data. The rules in factory/operations.py find
them, as they would in real records.

The same seed gives the same records every time.
"""

import random
from datetime import date, timedelta

GROUP = "Harbor Table Group"
START, WEEKS = date(2026, 8, 3), 8  # a Monday
END = START + timedelta(days=WEEKS * 7 - 1)
# Location: sales on an ordinary weekday in dollars, share of sales delivered, labour above the norm, weekly rent.
LOCATIONS = {
    "Downtown": (9200, 0.20, 0.000, 6300),
    "Dockside": (7100, 0.16, 0.005, 5000),
    "Uptown": (5300, 0.27, 0.030, 3700),
    "Airport Road": (4000, 0.31, 0.010, 2900),
}
WEEKDAY = (0.78, 0.82, 0.90, 1.00, 1.32, 1.48, 1.12)
# Dish: menu category, the stock it mostly draws on, price and recipe cost in cents, share of sales.
MENU = {
    "Fish and chips": ("Mains", "Seafood", 1850, 590, 0.13),
    "Grilled salmon": ("Mains", "Seafood", 2600, 960, 0.10),
    "Shrimp tacos": ("Mains", "Seafood", 1600, 510, 0.08),
    "Clam chowder": ("Starters", "Seafood", 900, 230, 0.05),
    "Cheeseburger": ("Mains", "Meat", 1500, 440, 0.13),
    "Ribeye": ("Mains", "Meat", 3400, 1320, 0.09),
    "Chicken sandwich": ("Mains", "Meat", 1400, 390, 0.09),
    "Caesar salad": ("Starters", "Produce", 1200, 280, 0.06),
    "Fries": ("Sides", "Produce", 600, 110, 0.06),
    "Key lime pie": ("Desserts", "Dry goods and dairy", 800, 190, 0.04),
    "Draft beer": ("Drinks", "Beverages", 700, 160, 0.12),
    "Soft drink": ("Drinks", "Beverages", 350, 45, 0.05),
}
STOCK = ("Seafood", "Meat", "Produce", "Dry goods and dairy", "Beverages")
SUPPLIERS = {
    "Seafood": "Bay Street Seafood",
    "Meat": "Carver Meats",
    "Produce": "Greenline Produce",
    "Dry goods and dairy": "Northgate Foodservice",
    "Beverages": "Tidewater Beverage",
}
# How far stock used runs above recipe cost, by location and category, where it is not the usual 2 to 4%.
OVERUSE = {("Dockside", "Seafood"): 0.17, ("Uptown", "Meat"): 0.07}
PLATFORMS = {
    "QuickDish": (0.6, 2200),
    "Plate Runner": (0.4, 2500),
}  # share of delivery sales, agreed rate in basis points


def record(area, kind, day, location, **data):
    return {"area": area, "kind": kind, "day": day.isoformat(), "location": location, "data": data}


def generate(seed="harbor-table-1"):
    rng = random.Random(seed)

    def cents(dollars):
        return int(round(dollars * 100))

    out = []
    for place, (base, delivered, labour_extra, rent) in LOCATIONS.items():
        closing = {category: None for category in STOCK}
        for week in range(WEEKS):
            monday = START + timedelta(days=week * 7)
            week_sales = week_delivery = 0
            for offset in range(7):
                day = monday + timedelta(days=offset)
                net = cents(base * WEEKDAY[offset] * (1 + 0.004 * week) * rng.uniform(0.93, 1.07))
                delivery = round(net * delivered * rng.uniform(0.9, 1.1))
                takeout = round(net * 0.15 * rng.uniform(0.9, 1.1))
                dine_in = net - delivery - takeout
                lunch = round(net * rng.uniform(0.34, 0.40))
                out.append(
                    record(
                        "sales",
                        "day",
                        day,
                        place,
                        net=net,
                        dine_in=dine_in,
                        takeout=takeout,
                        delivery=delivery,
                        lunch=lunch,
                        dinner=net - lunch,
                        covers=round(dine_in / rng.uniform(2550, 2850)),
                        discounts=round(net * rng.uniform(0.012, 0.024)),
                        voids=round(net * rng.uniform(0.003, 0.008)),
                        tax=round(net * 0.07),
                    )
                )
                week_sales += net
                week_delivery += delivery
                # Labour follows sales, on top of a management day that does not.
                cost = round(net * (0.262 + labour_extra) * rng.uniform(0.96, 1.04)) + 31000
                kitchen, floor, management = cost * 0.47 / 1900, cost * 0.35 / 1300, cost * 0.18 / 2800
                hours = kitchen + floor + management
                overrun = rng.uniform(0.07, 0.11) if place == "Uptown" else rng.uniform(0.0, 0.03)
                out.append(
                    record(
                        "labour",
                        "day",
                        day,
                        place,
                        cost=cost,
                        kitchen_hours=round(kitchen, 1),
                        floor_hours=round(floor, 1),
                        management_hours=round(management, 1),
                        overtime_hours=round(
                            hours * (rng.uniform(0.05, 0.08) if place == "Uptown" else rng.uniform(0.005, 0.02)), 1
                        ),
                        scheduled_hours=round(hours * (1 - overrun), 1),
                        tips=round(dine_in * rng.uniform(0.13, 0.16)),
                    )
                )
                # The till: cash is a fifth of what is paid on the premises, the rest is cards.
                on_site = dine_in + takeout
                cash = round(on_site * rng.uniform(0.17, 0.20))
                counted = cash + cents(rng.choice((0, 0, 0, -1, 1, -2, 2, -4, 3, -6)))
                if place == "Airport Road" and (week, offset) in ((2, 5), (5, 4)):
                    counted = cash - cents(84 if week == 2 else 61)
                days_ago = (END - day).days
                banked = None if days_ago == 0 or (place == "Dockside" and days_ago == 5) else counted
                cards = on_site - cash
                fees = round(cards * 0.026)
                settled = None if days_ago <= 1 else cards - fees
                if place == "Downtown" and (week, offset) == (4, 5):
                    settled = cards - fees - cents(312.40)
                out.append(
                    record(
                        "cash",
                        "day",
                        day,
                        place,
                        cash_expected=cash,
                        cash_counted=counted,
                        cash_banked=banked,
                        card_sales=cards,
                        card_fees=fees,
                        card_settled=settled,
                    )
                )
            # What sold, and so what the recipes say was used.
            should = {category: 0 for category in STOCK}
            for dish, (category, stock, price, cost, share) in MENU.items():
                sold = round(week_sales * share * rng.uniform(0.94, 1.06) / price)
                out.append(
                    record(
                        "sales",
                        "item_week",
                        monday,
                        place,
                        item=dish,
                        category=category,
                        stock=stock,
                        qty=sold,
                        sales=sold * price,
                        cost=cost,
                    )
                )
                should[stock] += sold * cost
            for category in STOCK:
                over = OVERUSE.get((place, category), rng.uniform(0.02, 0.04))
                usage = round(should[category] * (1 + over) * rng.uniform(0.985, 1.015))
                opening = closing[category] if closing[category] is not None else round(usage * rng.uniform(0.5, 0.7))
                closing[category] = round(usage * rng.uniform(0.5, 0.7))
                bought = usage + closing[category] - opening
                out.append(
                    record(
                        "inventory",
                        "count_week",
                        monday,
                        place,
                        category=category,
                        opening=opening,
                        purchases=bought,
                        closing=closing[category],
                    )
                )
                # Two deliveries a week from the category's supplier.
                first = round(bought * rng.uniform(0.45, 0.55))
                for _number, (offset, total) in enumerate(((1, first), (4, bought - first))):
                    out.append(
                        record(
                            "purchasing",
                            "invoice",
                            monday + timedelta(days=offset),
                            place,
                            supplier=SUPPLIERS[category],
                            category=category,
                            total=total,
                            number=f"{SUPPLIERS[category][:2].upper()}{rng.randrange(100000, 999999)}",
                        )
                    )
                # What staff wrote on the waste sheet: a little of what was used, whatever the real loss.
                for reason in rng.sample(("Spoiled", "Over-prepared", "Dropped or burnt", "Returned by guest"), 2):
                    out.append(
                        record(
                            "inventory",
                            "waste",
                            monday + timedelta(days=rng.randrange(7)),
                            place,
                            category=category,
                            reason=reason,
                            cost=round(usage * rng.uniform(0.004, 0.011)),
                        )
                    )
            for platform, (share, agreed) in PLATFORMS.items():
                gross = round(week_delivery * share)
                rate = 2800 if (platform, place) == ("Plate Runner", "Downtown") and 3 <= week <= 6 else agreed
                commission, refunds = round(gross * rate / 10000), round(gross * rng.uniform(0.012, 0.028))
                payout = gross - commission - refunds
                if (platform, place, week) == ("QuickDish", "Uptown", 5):
                    payout -= cents(146.20)
                out.append(
                    record(
                        "delivery",
                        "payout",
                        monday,
                        place,
                        platform=platform,
                        orders=round(gross / rng.uniform(2900, 3300)),
                        gross=gross,
                        rate_agreed=agreed,
                        commission=commission,
                        refunds=refunds,
                        payout=payout,
                    )
                )
            for category, amount in (
                ("Rent", cents(rent)),
                ("Utilities", round(week_sales * 0.036)),
                ("Marketing", round(week_sales * 0.012)),
                ("Repairs and cleaning", cents(rng.uniform(280, 520))),
                ("Insurance and licences", cents(215)),
                ("Supplies", round(week_sales * 0.011)),
                ("Office, software and bank charges", round(week_sales * 0.018)),
            ):
                out.append(record("accounting", "expense", monday, place, category=category, amount=amount))
            checks = 98
            done = 71 if (place, week) == ("Airport Road", 6) else checks - rng.choice((0, 0, 1, 1, 2))
            out.append(
                record(
                    "compliance",
                    "temperature",
                    monday,
                    place,
                    due=checks,
                    done=done,
                    out_of_range=rng.choice((0, 0, 0, 1, 2)),
                )
            )

    def day(offset):
        return END - timedelta(days=offset)

    prices = (
        ("Dockside", 6, "Bay Street Seafood", "Atlantic salmon fillet, 10 lb", 8900, 9790),
        ("Downtown", 11, "Bay Street Seafood", "Atlantic salmon fillet, 10 lb", 8900, 9790),
        ("Uptown", 9, "Carver Meats", "Ground beef 80/20, 20 lb", 6840, 7320),
        ("Downtown", 17, "Greenline Produce", "Romaine hearts, case of 24", 3150, 3890),
        ("Airport Road", 20, "Northgate Foodservice", "Fryer oil, 35 lb", 4210, 4390),
        ("Dockside", 24, "Tidewater Beverage", "Lager keg, half barrel", 14200, 14650),
        ("Uptown", 31, "Greenline Produce", "Russet potatoes, 50 lb", 2380, 2140),
    )
    for place, ago, supplier, item, was, now in prices:
        out.append(record("purchasing", "price", day(ago), place, supplier=supplier, item=item, was=was, now=now))
    credits = (
        ("Dockside", 23, "Bay Street Seafood", "Two cases of cod short on delivery", 18640, "open"),
        ("Downtown", 19, "Carver Meats", "Ribeye invoiced at the old price", 9420, "open"),
        ("Uptown", 6, "Greenline Produce", "Case of lettuce arrived spoiled", 3890, "open"),
        ("Airport Road", 33, "Northgate Foodservice", "Fryer oil delivered damaged", 4210, "received"),
        ("Downtown", 40, "Tidewater Beverage", "Keg returned flat", 14200, "received"),
    )
    for place, ago, supplier, reason, amount, status in credits:
        out.append(
            record(
                "purchasing", "credit", day(ago), place, supplier=supplier, reason=reason, amount=amount, status=status
            )
        )
    # Catering: (location, days from the last day, customer, event, guests, dollars, status, share paid, days until due)
    events = (
        ("Downtown", -44, "Lakeshore Dental Group", "Staff lunch", 45, 1620, "paid", 1.0, 14),
        ("Dockside", -39, "Marlow & Finch Architects", "Client dinner", 28, 2380, "paid", 1.0, 14),
        ("Downtown", -33, "Riverbend Rowing Club", "Awards banquet", 110, 6050, "invoiced", 0.3, 14),
        ("Uptown", -30, "Westfield Primary PTA", "Fundraiser buffet", 80, 2960, "paid", 1.0, 14),
        ("Dockside", -26, "Hollis Family", "Rehearsal dinner", 36, 3240, "paid", 1.0, 14),
        ("Downtown", -21, "Corbin Freight", "Board lunch", 18, 990, "invoiced", 0.0, 14),
        ("Airport Road", -17, "Skyline Charter", "Crew catering, weekly", 30, 1350, "invoiced", 0.0, 30),
        ("Dockside", -12, "Pembroke Yacht Sales", "Launch party", 95, 7410, "invoiced", 0.5, 30),
        ("Uptown", -9, "Juniper Yoga Studio", "Anniversary brunch", 40, 1480, "paid", 1.0, 14),
        ("Downtown", -5, "Ashby & Lowe Solicitors", "Partners' dinner", 22, 2640, "invoiced", 0.0, 30),
        ("Downtown", 4, "Northside Credit Union", "Staff appreciation lunch", 120, 4680, "accepted", 0.0, 14),
        ("Dockside", 9, "Okafor Family", "Wedding reception", 140, 13300, "accepted", 0.3, 14),
        ("Uptown", 12, "Brightwater School", "Teachers' dinner", 60, 2700, "sent", 0.0, 14),
        ("Dockside", 18, "Pembroke Yacht Sales", "Boat show hospitality", 200, 15400, "sent", 0.0, 30),
        ("Downtown", 25, "Corbin Freight", "Holiday party", 85, 6800, "accepted", 0.25, 14),
        ("Airport Road", 30, "Skyline Charter", "Pilots' dinner", 35, 1925, "sent", 0.0, 30),
        ("Uptown", -47, "Tessellate Software", "Offsite lunch", 50, 1900, "declined", 0.0, 14),
        ("Downtown", -36, "Halden Insurance", "Quarterly dinner", 40, 3400, "declined", 0.0, 14),
    )
    for place, ahead, customer, event, guests, dollars, status, paid, terms in events:
        held = END + timedelta(days=ahead)
        out.append(
            record(
                "catering",
                "quote",
                held,
                place,
                customer=customer,
                event=event,
                guests=guests,
                amount=cents(dollars),
                status=status,
                paid=round(cents(dollars) * paid),
                due=(held + timedelta(days=terms)).isoformat(),
            )
        )
    papers = (
        ("Downtown", "Food service licence", "The premises", 212),
        ("Downtown", "Liquor licence", "The premises", 96),
        ("Downtown", "Fire inspection certificate", "The premises", 141),
        ("Downtown", "Food handler card", "Sous chef", 19),
        ("Dockside", "Food service licence", "The premises", 188),
        ("Dockside", "Liquor licence", "The premises", 301),
        ("Dockside", "Kitchen hood cleaning certificate", "The premises", -11),
        ("Dockside", "Food handler card", "Line cook", 240),
        ("Uptown", "Food service licence", "The premises", 44),
        ("Uptown", "Liquor licence", "The premises", 27),
        ("Uptown", "Fire inspection certificate", "The premises", 310),
        ("Uptown", "Food protection manager certificate", "Kitchen manager", 402),
        ("Airport Road", "Food service licence", "The premises", 265),
        ("Airport Road", "Fire inspection certificate", "The premises", 73),
        ("Airport Road", "Food handler card", "Prep cook", 8),
        ("Airport Road", "Kitchen hood cleaning certificate", "The premises", 128),
    )
    for place, name, holder, left in papers:
        out.append(record("compliance", "certificate", END + timedelta(days=left), place, name=name, holder=holder))
    repairs = (
        ("Dockside", 31, "Walk-in freezer", "Door seal split, frosting over", "waiting for parts", 640),
        ("Uptown", 22, "Dish machine", "Rinse temperature running low", "open", 380),
        ("Downtown", 9, "Fryer no. 2", "Thermostat sticking", "booked", 275),
        ("Airport Road", 4, "Ice machine", "Leaking at the drain", "open", 190),
        ("Downtown", 27, "Reach-in fridge, bar", "Compressor replaced", "done", 910),
        ("Dockside", 16, "Grill", "Igniter replaced", "done", 145),
        ("Uptown", 38, "Extraction fan", "Belt replaced", "done", 220),
    )
    for place, ago, equipment, issue, status, dollars in repairs:
        out.append(
            record(
                "compliance",
                "maintenance",
                day(ago),
                place,
                equipment=equipment,
                issue=issue,
                status=status,
                estimate=cents(dollars),
            )
        )
    return out
