"""Supplier invoices after they are read: checked, coded to accounts, exported, reconciled.

Everything here is arithmetic and comparison over what an agent recorded, done in code. An agent
reads a page; whether its lines add up, whether the invoice was seen before, whether a price is
plausible, which ledger account a supplier's goods belong to and whether a supplier's statement
agrees with the invoices received are not questions for a model.

The checks decide who has to look. A document they find nothing wrong with is ready to approve; one
they flag waits for a person, with the reason. They are deliberately suspicious of the reading: a
total that does not match its lines, or a price three times last week's, is far more often a
misread digit than a fact.
"""

import csv
import io
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# A price is called risen when it is more than this far above the last price paid for the item.
PRICE_RISE = Decimal("0.05")
# Beyond this factor up or down, a price is taken to be misread until a person confirms it.
IMPLAUSIBLE = Decimal(3)
HEADER = ("supplier", "invoice_number", "invoice_date", "total_cents")
CENT = Decimal("0.011")
EXPORT_FORMATS = {
    "xero": "Xero bills import (CSV)",
    "quickbooks": "QuickBooks Online bills import (CSV)",
    "lines": "Every line (CSV)",
}
# QuickBooks advises importing no more than this many bills in one file, and takes only spreadsheets of
# fewer than 1,000 rows. Both are from Intuit's own help pages, cited in docs/ACCOUNTING_EXPORTS.md.
QUICKBOOKS_BATCH = 100
QUICKBOOKS_ROWS = 999
# How a date is written in an export file. Neither system takes one fixed format: Xero reads dates the way
# the organisation's region writes them, and QuickBooks asks which format the file uses while importing.
DATE_FORMATS = {"mdy": "%m/%d/%Y", "dmy": "%d/%m/%Y", "iso": "%Y-%m-%d"}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def answer(document):
    """What the document says: the corrected answer when a person has corrected it, otherwise the agent's."""
    return document.corrected if document.corrected is not None else document.output


def items_of(data):
    """The priced lines of an answer, or None when it has none: the first table whose rows carry a unit price."""
    for value in (data or {}).values():
        if isinstance(value, list) and value and isinstance(value[0], dict) and "unit_price" in value[0]:
            return value
    return None


def statement_rows(data):
    """The rows of a supplier's statement: the first table whose rows name an invoice and an amount."""
    for value in (data or {}).values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if "invoice_number" in value[0] and "amount" in value[0]:
                return value
    return None


def same_number(left, right):
    """Invoice numbers compared as a person would: digits and letters only, leading zeros aside."""

    def plain(value):
        return re.sub(r"[^0-9A-Z]", "", str(value or "").upper()).lstrip("0")

    return bool(plain(left)) and plain(left) == plain(right)


def item_key(data, item):
    name = str(item.get("code") or item.get("description") or "").strip().upper()
    return (str(data.get("supplier") or "").strip().upper(), str(data.get("customer") or "").strip().upper(), name)


def line_units(item):
    """What the unit price multiplies: pounds for an item sold by weight, otherwise the quantity."""
    quantity, price, amount = number(item.get("quantity")), number(item.get("unit_price")), number(item.get("amount"))
    if None not in (quantity, price, amount) and abs(quantity * price - amount) <= CENT:
        return quantity
    weight = re.search(r"([\d.]+)\s*LB\s*$", str(item.get("description") or "").strip())
    if weight and None not in (price, amount) and abs(Decimal(weight.group(1)) * price - amount) <= CENT:
        return Decimal(weight.group(1))
    return None


def implausible(price, before):
    return before > 0 and (price >= before * IMPLAUSIBLE or price * IMPLAUSIBLE <= before)


def walk(documents):
    """Invoices in the order they were issued, each with the last price paid for its items before it.

    Yields (document, data, items, last). A price that looks misread does not become the last price
    for its item unless a person has approved the document it is on: one bad reading should not
    make the next good one look like a change.
    """
    rows = []
    for document in documents:
        data = answer(document) or {}
        items = items_of(data)
        if items:
            rows.append((str(data.get("invoice_date") or ""), document, data, items))
    rows.sort(key=lambda row: (row[0], row[1].created_at))
    last = {}
    for day, document, data, items in rows:
        yield document, data, items, last
        seen = {}
        for item in items:
            price, key = number(item.get("unit_price")), item_key(data, item)
            if price is None or not key[2]:
                continue
            before = last.get(key)
            if before and implausible(price, before["price"]) and not document.approved_by:
                continue
            seen[key] = {"price": price, "date": day}
        # An invoice is compared with what came before it, not with its own earlier lines.
        last.update(seen)


def check(document, documents):
    """What the automatic checks find in one invoice, given the operation's other documents."""
    data = answer(document) or {}
    found = []

    def flag(kind, message, **more):
        found.append({"kind": kind, "message": message, **more})

    for field in HEADER:
        value = data.get(field)
        if value is None or str(value).strip() == "" or "[illegible]" in str(value):
            flag(
                "missing_field", f"The {field.replace('_cents', '').replace('_', ' ')} could not be read.", field=field
            )
    day = str(data.get("invoice_date") or "")
    if day and "[illegible]" not in day:
        try:
            if date.fromisoformat(day) > date.today() + timedelta(days=1):
                flag("bad_date", f"The invoice date {day} is in the future.", field="invoice_date")
        except ValueError:
            flag("bad_date", f"The invoice date {day!r} is not a date.", field="invoice_date")
    items = items_of(data)
    if not items:
        flag("no_lines", "No lines were read from this invoice.")
        return found
    unread = [n for n, item in enumerate(items, 1) if number(item.get("amount")) is None]
    if unread:
        flag("unreadable_line", f"{len(unread)} line(s) have no readable amount: line {_listed(unread)}.", lines=unread)
    wrong = [
        n
        for n, item in enumerate(items, 1)
        if None not in (number(item.get("unit_price")), number(item.get("amount"))) and line_units(item) is None
    ]
    if wrong:
        flag(
            "line_arithmetic",
            f"On {len(wrong)} line(s) the quantity times the unit price is not the amount: line {_listed(wrong)}.",
            lines=wrong,
        )
    total, lines = number(data.get("total_cents")), sum(number(item.get("amount")) or 0 for item in items)
    # Where the answer records the tax, the lines and the tax together must make the total.
    tax = number(data.get("tax_cents")) if "tax_cents" in data else None
    if total is not None and abs(lines * 100 + (tax or 0) - total) > 1:
        flag(
            "lines_do_not_add_up",
            (
                f"The lines add up to ${lines:,.2f}, the tax is ${(tax or 0) / 100:,.2f} and the total is "
                f"${total / 100:,.2f}. A figure has been misread, or the invoice charges something that is not on a line."
                if tax is not None
                else f"The lines add up to ${lines:,.2f} and the total is ${total / 100:,.2f}. "
                "The difference may be tax or a charge that is not on a line, or a misread figure."
            ),
            difference_cents=int(total - lines * 100 - (tax or 0)),
        )
    for other in documents:
        if other.id == document.id or other.status != "processed" or other.created_at > document.created_at:
            continue
        theirs = answer(other) or {}
        if str(theirs.get("supplier") or "").strip().upper() == str(data.get("supplier") or "").strip().upper():
            if same_number(theirs.get("invoice_number"), data.get("invoice_number")):
                flag("duplicate", f"This looks like the same invoice as {other.name}.", document_id=other.id)
                break
    for seen, their_data, their_items, last in walk(documents):
        if seen.id != document.id:
            continue
        odd = []
        for n, item in enumerate(their_items, 1):
            price, before = number(item.get("unit_price")), last.get(item_key(their_data, item))
            if price is not None and before and implausible(price, before["price"]):
                odd.append((n, item, before["price"]))
        if odd:
            n, item, before = odd[0]
            flag(
                "price_looks_misread",
                f"{len(odd)} price(s) are far from the last price paid, which usually means a misread figure: "
                f"line {n}, {item.get('description')}, {number(item.get('unit_price'))} against {before} last time.",
                lines=[n for n, _, _ in odd],
            )
    return found


def _listed(numbers):
    return ", ".join(str(n) for n in numbers[:6]) + (" and more" if len(numbers) > 6 else "")


def insights(documents):
    """Price movements and spend from the recorded lines. A price that looks misread is not reported as
    a rise; it is raised on its document for a person to check instead."""
    rises, spend, compared = [], {}, 0
    for document, data, items, last in walk(documents):
        compared += 1
        supplier = str(data.get("supplier") or "")
        total = number(data.get("total_cents"))
        if total is not None:
            entry = spend.setdefault(supplier, {"supplier": supplier, "documents": 0, "total_cents": 0})
            entry["documents"] += 1
            entry["total_cents"] += int(total)
        for item in items:
            price, before = number(item.get("unit_price")), last.get(item_key(data, item))
            if price is None or not before or before["price"] <= 0:
                continue
            if implausible(price, before["price"]) and not document.approved_by:
                continue
            if price > before["price"] * (1 + PRICE_RISE):
                units = line_units(item) or number(item.get("quantity")) or Decimal(0)
                rises.append(
                    {
                        "document_id": document.id,
                        "date": str(data.get("invoice_date") or ""),
                        "supplier": supplier,
                        "customer": str(data.get("customer") or ""),
                        "code": item.get("code"),
                        "description": item.get("description"),
                        "last_price": float(before["price"]),
                        "last_date": before["date"],
                        "price": float(price),
                        "rise_percent": round(float((price / before["price"] - 1) * 100), 1),
                        "quantity": float(units),
                        "extra_cents": int(((price - before["price"]) * units * 100).to_integral_value()),
                    }
                )
    return {
        "applies": compared > 0,
        "documents": compared,
        "price_rises": sorted(rises, key=lambda rise: (rise["date"], rise["rise_percent"]), reverse=True),
        "extra_cents": sum(rise["extra_cents"] for rise in rises),
        "spend": sorted(spend.values(), key=lambda entry: -entry["total_cents"]),
        "threshold_percent": float(PRICE_RISE * 100),
    }


# Coding to accounts, and files an accounting system can import.


def account_for(settings, supplier):
    """The ledger account a supplier's invoices are coded to: the supplier's own, else the default."""
    by_supplier = {name.strip().upper(): code for name, code in (settings.get("supplier_accounts") or {}).items()}
    return by_supplier.get(str(supplier or "").strip().upper()) or settings.get("default_account") or ""


def uncoded(settings, documents):
    """Suppliers on these documents with no account to code them to."""
    return sorted(
        {
            str((answer(document) or {}).get("supplier") or "")
            for document in documents
            if not account_for(settings, (answer(document) or {}).get("supplier"))
        }
    )


def bill_lines(document, settings):
    """A document as the lines of a bill: (header, lines), each line (description, quantity, unit amount,
    amount). The lines always add up to the invoice total: what the invoice charges beyond its lines
    goes on a line of its own, since an accounting system will not accept a bill that does not add up."""
    data = answer(document) or {}
    issued = str(data.get("invoice_date") or "")
    try:
        due = (date.fromisoformat(issued) + timedelta(days=int(settings.get("terms_days", 30)))).isoformat()
    except ValueError:
        due = ""
    shape = DATE_FORMATS.get(str(settings.get("date_format") or "iso"), "%Y-%m-%d")

    def written(day):
        try:
            return date.fromisoformat(day).strftime(shape)
        except ValueError:
            return day

    header = {
        "supplier": str(data.get("supplier") or ""),
        "number": str(data.get("invoice_number") or ""),
        "date": written(issued),
        "due": written(due),
        "account": account_for(settings, data.get("supplier")),
        "tax": str(settings.get("tax_code") or ""),
    }
    lines, summed = [], Decimal(0)
    for item in items_of(data) or []:
        amount = number(item.get("amount"))
        if amount is None:
            continue
        quantity, price = number(item.get("quantity")), number(item.get("unit_price"))
        text = " ".join(str(part) for part in (item.get("code"), item.get("description")) if part)
        if None in (quantity, price) or abs(quantity * price - amount) > CENT:
            # Sold by weight, or otherwise not quantity times price: one unit at the line's amount.
            quantity, price = Decimal(1), amount
        lines.append((text, quantity, price, amount))
        summed += amount
    total, tax = number(data.get("total_cents")), number(data.get("tax_cents"))
    if tax:
        charged = (tax / 100).quantize(Decimal("0.01"))
        lines.append(("Tax", Decimal(1), charged, charged))
        summed += charged
    if total is not None and abs(total - summed * 100) > 1:
        rest = (total / 100 - summed).quantize(Decimal("0.01"))
        lines.append(("Tax and charges not on a line", Decimal(1), rest, rest))
    if not lines and total is not None:
        lines.append(("Invoice total", Decimal(1), total / 100, total / 100))
    return header, lines


def _safe(value):
    # A cell that a spreadsheet would run as a formula is written as text.
    return "'" + value if isinstance(value, str) and value and value[0] in "=+-@" else value


def export_file(kind, documents, settings):
    """The approved documents as one file of the given kind. Column headings follow each system's
    published import template; check them against the template of the account they go into."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if kind == "xero":
        writer.writerow(
            [
                "*ContactName",
                "*InvoiceNumber",
                "*InvoiceDate",
                "*DueDate",
                "*Description",
                "*Quantity",
                "*UnitAmount",
                "*AccountCode",
                "*TaxType",
            ]
        )
        for document in documents:
            header, lines = bill_lines(document, settings)
            for text, quantity, price, _ in lines:
                row = [
                    header["supplier"],
                    header["number"],
                    header["date"],
                    header["due"],
                    text,
                    f"{quantity.normalize():f}",
                    f"{price:f}",
                    header["account"],
                    header["tax"],
                ]
                writer.writerow([_safe(cell) for cell in row])
    elif kind == "quickbooks":
        writer.writerow(
            [
                "Bill no.",
                "Supplier",
                "Bill Date",
                "Due Date",
                "Account",
                "Line Description",
                "Line Amount",
                "Line Tax Code",
            ]
        )
        for document in documents:
            header, lines = bill_lines(document, settings)
            for text, _, _, amount in lines:
                row = [
                    header["number"],
                    header["supplier"],
                    header["date"],
                    header["due"],
                    header["account"],
                    text,
                    f"{amount:.2f}",
                    header["tax"],
                ]
                writer.writerow([_safe(cell) for cell in row])
    else:
        columns = [
            "document",
            "supplier",
            "customer",
            "invoice_number",
            "invoice_date",
            "account",
            "code",
            "description",
            "quantity",
            "unit_price",
            "amount",
        ]
        writer.writerow(columns)
        for document in documents:
            data = answer(document) or {}
            for item in items_of(data) or [{}]:
                row = {**{key: value for key, value in data.items() if not isinstance(value, (list, dict))}, **item}
                row.update(document=document.name, account=account_for(settings, data.get("supplier")))
                writer.writerow([_safe(row.get(column, "")) for column in columns])
    return buffer.getvalue()


def unsendable(kind, documents, settings):
    """Why approved documents cannot go into a file of this kind as things stand, if they cannot. The rules are
    the receiving system's own, so a file that would be refused on import is not produced."""
    if kind == "xero" and not str(settings.get("tax_code") or "").strip():
        return (
            "Xero's bill template needs a tax type on every line. Set one under Accounts and approval: it must be "
            "the name of a tax rate in your Xero organisation, exactly as Xero shows it."
        )
    if kind == "quickbooks":
        credits = [
            document.name for document in documents if (number((answer(document) or {}).get("total_cents")) or 0) < 0
        ]
        if credits:
            return (
                "QuickBooks' bill import does not take a bill with a total below zero, and has no credit notes: "
                + ", ".join(credits[:5])
                + ". Enter these in QuickBooks by hand, or send them another way."
            )
    return None


def quickbooks_batch(documents, settings):
    """As many of the documents as one QuickBooks file may hold: up to its bill limit and its row limit."""
    chosen, rows = [], 1
    for document in documents[:QUICKBOOKS_BATCH]:
        lines = len(bill_lines(document, settings)[1])
        if chosen and rows + lines > QUICKBOOKS_ROWS:
            break
        chosen.append(document)
        rows += lines
    return chosen


# A supplier's statement against the invoices received.


def reconcile(statement, invoices):
    """Each row of a supplier's statement against the invoices on file from that supplier.

    A statement row is matched to an invoice by its number. Returns the rows with what was found:
    "matched", "amount_differs" or "not_received"; and the supplier's invoices dated within the
    statement's span that the statement does not list.
    """
    data = answer(statement) or {}
    supplier = str(data.get("supplier") or "").strip().upper()
    rows = statement_rows(data) or []
    ours = []
    for invoice in invoices:
        theirs = answer(invoice) or {}
        name = str(theirs.get("supplier") or "").strip().upper()
        if invoice.status == "processed" and (not supplier or not name or supplier in name or name in supplier):
            ours.append((invoice, theirs))
    used, lines = set(), []
    for row in rows:
        amount = number(row.get("amount"))
        match = next(
            (
                (invoice, theirs)
                for invoice, theirs in ours
                if invoice.id not in used and same_number(theirs.get("invoice_number"), row.get("invoice_number"))
            ),
            None,
        )
        line = {
            "invoice_number": row.get("invoice_number"),
            "invoice_date": row.get("invoice_date"),
            "amount": float(amount) if amount is not None else None,
        }
        if match is None:
            lines.append({**line, "status": "not_received"})
            continue
        invoice, theirs = match
        used.add(invoice.id)
        total = number(theirs.get("total_cents"))
        agrees = amount is not None and total is not None and abs(amount * 100 - total) <= 1
        lines.append(
            {
                **line,
                "status": "matched" if agrees else "amount_differs",
                "document_id": invoice.id,
                "our_amount": float(total / 100) if total is not None else None,
            }
        )
    days = sorted(str(row.get("invoice_date") or "") for row in rows if row.get("invoice_date"))
    unlisted = []
    for invoice, theirs in ours:
        day = str(theirs.get("invoice_date") or "")
        if invoice.id not in used and days and days[0] <= day <= days[-1]:
            total = number(theirs.get("total_cents"))
            unlisted.append(
                {
                    "document_id": invoice.id,
                    "invoice_number": theirs.get("invoice_number"),
                    "invoice_date": day,
                    "our_amount": float(total / 100) if total is not None else None,
                }
            )
    counts = {
        status: sum(line["status"] == status for line in lines)
        for status in ("matched", "amount_differs", "not_received")
    }
    return {
        "supplier": data.get("supplier"),
        "rows": lines,
        "not_on_statement": unlisted,
        "counts": {**counts, "not_on_statement": len(unlisted)},
        "statement_total": float(sum(number(row.get("amount")) or 0 for row in rows)),
    }


# Two prices for the same item on the same day are called different when they are this far apart.
PRICE_GAP = Decimal("0.02")


def gap_lines(documents):
    """The same item from the same supplier, invoiced on the same day to different locations at
    different prices. What a location paid above the lowest price that day is the gap.

    The same day, not the same week: a supplier's prices move during a week, so two prices a few days
    apart are as likely a price change as a difference between locations, and a change is already
    counted as a price rise. A price that looks misread is left out.
    """
    from datetime import date as day_of

    bought = {}
    for document in documents:
        data = answer(document) or {}
        try:
            issued = day_of.fromisoformat(str(data.get("invoice_date") or ""))
        except ValueError:
            continue
        day = issued.isoformat()
        supplier, place = str(data.get("supplier") or "").strip().upper(), str(data.get("customer") or "").strip()
        for item in items_of(data) or []:
            price, units = number(item.get("unit_price")), line_units(item)
            name = str(item.get("code") or item.get("description") or "").strip().upper()
            if not name or not place or price is None or price <= 0 or units is None:
                continue
            bought.setdefault((supplier, name, day), []).append(
                {
                    "place": place,
                    "price": price,
                    "units": units,
                    "item": item,
                    "document": document,
                    "supplier": data.get("supplier"),
                }
            )
    gaps = []
    for (_, _, day), lines in bought.items():
        if len({line["place"] for line in lines}) < 2:
            continue
        low = min(line["price"] for line in lines)
        cheapest = next(line["place"] for line in lines if line["price"] == low)
        at_low = {line["place"] for line in lines if line["price"] == low}
        for line in lines:
            # A location that paid both prices that day is not being charged more than another.
            if line["place"] in at_low:
                continue
            if line["price"] > low * (1 + PRICE_GAP) and not implausible(line["price"], low):
                gaps.append(
                    {
                        "day": day,
                        "supplier": line["supplier"],
                        "code": line["item"].get("code"),
                        "description": line["item"].get("description"),
                        "customer": line["place"],
                        "price": float(line["price"]),
                        "lowest_price": float(low),
                        "lowest_at": cheapest,
                        "above_percent": round(float((line["price"] / low - 1) * 100), 1),
                        "extra_cents": int(((line["price"] - low) * line["units"] * 100).to_integral_value()),
                        "document_id": line["document"].id,
                    }
                )
    return sorted(gaps, key=lambda gap: -gap["extra_cents"])


def price_gaps(documents):
    """The gaps as findings: one for each item, day, location and price, however many lines it was bought on.

    A case of chicken sold by weight is a line of its own for every case, so twelve cases at one price are
    one finding with twelve lines, not twelve findings.
    """
    found = {}
    for gap in gap_lines(documents):
        key = (gap["day"], gap["supplier"], gap["code"] or gap["description"], gap["customer"], gap["price"])
        if key not in found:
            found[key] = {**gap, "lines": 0, "extra_cents": 0}
        found[key]["lines"] += 1
        found[key]["extra_cents"] += gap["extra_cents"]
    return sorted(found.values(), key=lambda gap: -gap["extra_cents"])


def movers(rises):
    """Price rises gathered by item: how often each rose, from what to what, and what the rises cost."""
    found = {}
    for rise in rises:
        entry = found.setdefault(
            (rise["supplier"], rise["code"] or rise["description"]),
            {
                "description": rise["description"],
                "code": rise["code"],
                "supplier": rise["supplier"],
                "times": 0,
                "extra_cents": 0,
                "from": rise["last_price"],
                "to": rise["price"],
            },
        )
        entry["times"] += 1
        entry["extra_cents"] += rise["extra_cents"]
        entry["from"], entry["to"] = min(entry["from"], rise["last_price"]), max(entry["to"], rise["price"])
    return sorted(found.values(), key=lambda row: -row["extra_cents"])


# Past this many days of invoices, what came in is charted by week instead of by day.
DAILY_SPAN = 45


def analytics(documents, place=None):
    """What was bought, for the person who runs the business: how much came in, when, to which location,
    from whom, which items the money went on and which prices moved.

    Sums and counts over recorded lines. place narrows everything to one location; the list of locations
    is always the whole one. Quantity is what the invoice gives as the quantity of a line: cases or pieces,
    not pounds.
    """
    invoices = [document for document in documents if items_of(answer(document) or {})]
    places = sorted({str((answer(document) or {}).get("customer") or "Not stated") for document in invoices})
    if place:
        invoices = [d for d in invoices if str((answer(d) or {}).get("customer") or "Not stated") == place]
    by_day, by_place, by_supplier, goods = {}, {}, {}, {}
    spend = lines = 0
    units = Decimal(0)
    for document in invoices:
        data = answer(document) or {}
        total = int(number(data.get("total_cents")) or 0)
        where, supplier = str(data.get("customer") or "Not stated"), str(data.get("supplier") or "Not stated")
        try:
            issued = date.fromisoformat(str(data.get("invoice_date") or ""))
        except ValueError:
            issued = None
        received = Decimal(0)
        for item in items_of(data) or []:
            quantity, amount, price = (
                number(item.get("quantity")),
                number(item.get("amount")),
                number(item.get("unit_price")),
            )
            name = str(item.get("code") or item.get("description") or "").strip().upper()
            lines += 1
            received += quantity if quantity is not None and quantity > 0 else 0
            if not name:
                continue
            entry = goods.setdefault(
                (supplier.upper(), name),
                {
                    "code": item.get("code"),
                    "description": item.get("description"),
                    "supplier": supplier,
                    "quantity": Decimal(0),
                    "cents": 0,
                    "times": 0,
                    "places": set(),
                    "prices": [],
                },
            )
            entry["quantity"] += quantity if quantity is not None and quantity > 0 else 0
            entry["cents"] += int((amount or 0) * 100)
            entry["times"] += 1
            entry["places"].add(where)
            if price is not None and price > 0:
                entry["prices"].append((issued or date.min, price))
        spend += total
        units += received
        for table, key in ((by_place, where), (by_supplier, supplier)):
            row = table.setdefault(key, {"name": key, "total_cents": 0, "invoices": 0, "quantity": Decimal(0)})
            row["total_cents"] += total
            row["invoices"] += 1
            row["quantity"] += received
        if issued:
            row = by_day.setdefault(issued, {"total_cents": 0, "invoices": 0, "quantity": Decimal(0)})
            row["total_cents"] += total
            row["invoices"] += 1
            row["quantity"] += received
    days = sorted(by_day)
    span = (days[-1] - days[0]).days + 1 if days else 0
    weekly = span > DAILY_SPAN
    series = {}
    if days:
        # Every day in the range, bought on or not: a gap in deliveries should look like one.
        for offset in range(span):
            day = days[0] + timedelta(days=offset)
            start = day - timedelta(days=day.weekday()) if weekly else day
            row = series.setdefault(
                start, {"start": start.isoformat(), "total_cents": 0, "invoices": 0, "quantity": 0.0}
            )
            if day in by_day:
                row["total_cents"] += by_day[day]["total_cents"]
                row["invoices"] += by_day[day]["invoices"]
                row["quantity"] += float(by_day[day]["quantity"])
    items = []
    for entry in goods.values():
        prices = [price for _, price in sorted(entry["prices"], key=lambda pair: pair[0])]
        items.append(
            {
                "code": entry["code"],
                "description": entry["description"],
                "supplier": entry["supplier"],
                "quantity": float(entry["quantity"]),
                "total_cents": entry["cents"],
                "times": entry["times"],
                "places": len(entry["places"]),
                "low_price": float(min(prices)) if prices else None,
                "high_price": float(max(prices)) if prices else None,
                "last_price": float(prices[-1]) if prices else None,
            }
        )
    seen = insights(invoices)

    def ranked(table):
        return sorted(
            ({**row, "quantity": float(row["quantity"])} for row in table.values()), key=lambda r: -r["total_cents"]
        )

    return {
        "places": places,
        "place": place if place in places else None,
        "invoices": len(invoices),
        "spend_cents": spend,
        "lines": lines,
        "quantity": float(units),
        "items": len(goods),
        "from": days[0].isoformat() if days else None,
        "to": days[-1].isoformat() if days else None,
        "days": span,
        "delivery_days": len(days),
        "bucket": "week" if weekly else "day",
        "series": list(series.values()),
        "by_place": ranked(by_place),
        "by_supplier": ranked(by_supplier),
        "top_items": sorted(items, key=lambda row: -row["total_cents"])[:15],
        "most_received": sorted(items, key=lambda row: -row["quantity"])[:15],
        "price_rises": len(seen["price_rises"]),
        "price_rise_cents": seen["extra_cents"],
        "movers": movers(seen["price_rises"])[:8],
        "threshold_percent": seen["threshold_percent"],
    }


def overview(documents, statements=()):
    """What the work added up to, for the person who owns the business: how much was handled, how much of
    it needed nobody, what was caught, where prices moved and where the money went.

    Counts and sums over what was recorded. statements are reconciliations already worked out.
    """
    from datetime import date as day_of

    invoices = [document for document in documents if items_of(answer(document) or {})]
    seen = insights(invoices)
    lines = sum(len(items_of(answer(document) or {}) or []) for document in invoices)
    flagged = [document for document in invoices if document.exceptions]
    caught = {}
    for document in flagged:
        for kind in {item["kind"] for item in document.exceptions}:
            caught[kind] = caught.get(kind, 0) + 1
    by_place, by_week, days = {}, {}, []
    for document in invoices:
        data = answer(document) or {}
        total = number(data.get("total_cents"))
        if total is None:
            continue
        place = str(data.get("customer") or "Not stated")
        by_place[place] = by_place.get(place, 0) + int(total)
        try:
            issued = day_of.fromisoformat(str(data.get("invoice_date") or ""))
        except ValueError:
            continue
        days.append(issued)
        week = (issued - timedelta(days=issued.weekday())).isoformat()
        by_week[week] = by_week.get(week, 0) + int(total)
    listed = {"not_received": 0, "amount_differs": 0, "not_on_statement": 0, "matched": 0}
    billed_not_received = overbilled = Decimal(0)
    for result in statements:
        for key in listed:
            listed[key] += result["counts"].get(key, 0)
        for row in result["rows"]:
            if row["status"] == "not_received" and row["amount"]:
                billed_not_received += Decimal(str(row["amount"]))
            elif row["status"] == "amount_differs" and row["amount"] and row.get("our_amount") is not None:
                overbilled += max(Decimal(0), Decimal(str(row["amount"])) - Decimal(str(row["our_amount"])))
    gaps = price_gaps(invoices)
    # A line can be both dearer than the location's own last price and dearer than another location's
    # price that day. It is one overpayment: counted with the gaps, and taken out of the rises.
    also_gap, rises_only = {}, 0
    for gap in gap_lines(invoices):
        line = (gap["document_id"], gap["code"] or gap["description"])
        also_gap[line] = also_gap.get(line, 0) + gap["extra_cents"]
    for rise in seen["price_rises"]:
        line = (rise["document_id"], rise["code"] or rise["description"])
        shared = min(rise["extra_cents"], also_gap.get(line, 0))
        also_gap[line] = also_gap.get(line, 0) - shared
        rises_only += rise["extra_cents"] - shared
    twice = sum(
        int(number((answer(document) or {}).get("total_cents")) or 0)
        for document in flagged
        if any(item["kind"] == "duplicate" for item in document.exceptions)
    )
    # What looking at every invoice turned up, in money. Each line is something to take up with a supplier
    # or put right, not money already recovered. An invoice a statement lists that is not on file is not
    # among them: far more often it has simply not been sent in yet, and what to do is ask for a copy.
    found = [
        {"kind": "statement_overbilled", "cents": int(overbilled * 100), "count": listed["amount_differs"]},
        {"kind": "duplicates", "cents": twice, "count": caught.get("duplicate", 0)},
        {"kind": "price_gaps", "cents": sum(gap["extra_cents"] for gap in gaps), "count": len(gaps)},
        {"kind": "price_rises", "cents": rises_only, "count": len(seen["price_rises"])},
    ]
    span = (max(days) - min(days)).days + 1 if days else 0
    return {
        "invoices": len(invoices),
        "lines": lines,
        "pages": sum(len(document.pages or []) for document in invoices),
        "clean": len(invoices) - len(flagged),
        "flagged": len(flagged),
        "corrected": sum(document.corrected is not None for document in invoices),
        "stages": {
            stage: sum(document.stage == stage for document in invoices)
            for stage in ("review", "ready", "approved", "exported")
        },
        "caught": caught,
        "from": min(days).isoformat() if days else None,
        "to": max(days).isoformat() if days else None,
        "billed_cents": sum(by_place.values()),
        "by_place": sorted(
            ({"name": name, "total_cents": total} for name, total in by_place.items()),
            key=lambda row: -row["total_cents"],
        ),
        "by_week": [{"week": week, "total_cents": total} for week, total in sorted(by_week.items())],
        "by_supplier": seen["spend"],
        "price_rises": len(seen["price_rises"]),
        "extra_cents": seen["extra_cents"],
        "movers": movers(seen["price_rises"])[:8],
        "threshold_percent": seen["threshold_percent"],
        "statements": {"count": len(statements), **listed, "not_received_cents": int(billed_not_received * 100)},
        "found": [row for row in found if row["cents"] > 0],
        "found_cents": sum(row["cents"] for row in found),
        "days": span,
        "price_gaps": gaps[:12],
        "price_gap_count": len(gaps),
    }
