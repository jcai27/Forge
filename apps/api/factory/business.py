"""Deterministic business policies shared by model and demo tool execution."""

import re
from decimal import ROUND_CEILING, Decimal
from difflib import SequenceMatcher


def match_product(name, customer, products, rules):
    query = name.strip().lower()
    exact = [p for p in products if query in (p["name"].lower(), p["sku"].lower())]
    if exact:
        return exact[0]
    if rules.get("resolve_aliases"):
        sku = customer.get("aliases", {}).get(query)
        if sku:
            return next((p for p in products if p["sku"] == sku), None)
    if rules.get("fuzzy_match"):
        matches = sorted(
            [(SequenceMatcher(None, query, p["name"].lower()).ratio(), p) for p in products],
            key=lambda x: x[0],
            reverse=True,
        )
        if matches and matches[0][0] >= 0.80 and (len(matches) == 1 or matches[0][0] - matches[1][0] >= 0.1):
            return matches[0][1]
    return None


def parse_items(text):
    body = text.split(":", 1)[-1].split(";")[0].strip()
    pattern = r"(-?\d+(?:\.\d+)?)\s+(?:(kg|kilograms?|bottles?|litres?|liters?|cases?|bags?)\s+)?(.+?)(?=,|\n|$)"
    items = []
    for match in re.finditer(pattern, body, re.IGNORECASE):
        qty, unit, name = match.groups()
        unit = (unit or "").lower()
        unit = {"kilogram": "kg", "kilograms": "kg", "liter": "litre", "liters": "litre", "litres": "litre"}.get(
            unit, unit
        )
        unit = unit.removesuffix("s")
        items.append({"quantity": float(qty), "unit": unit, "name": name.strip().rstrip(".")})
    return items


def prepare_operation(spec, input_data, state):
    text = input_data.get("text", "")
    if spec.template == "hiring":
        return prepare_hiring(text, state)
    if spec.template not in ("orders", "quotes"):
        return {
            "kind": "custom",
            "flags": ["custom_workflow_requires_model"],
            "requires_approval": True,
            "lines": [],
            "total_cents": 0,
        }
    customer = next(
        (
            c
            for c in state["customers"]
            if c["name"].lower() in text.lower() or c["id"] == input_data.get("customer_id")
        ),
        None,
    )
    flags = []
    if not customer:
        flags.append("unknown_customer")
        customer = {"id": None, "aliases": {}, "prices": {}}
    request_id = input_data.get("request_id")
    if request_id and any(o.get("request_id") == request_id for o in state["orders"]):
        flags.insert(0, "duplicate_request")
    lines = []
    items = input_data.get("items") or parse_items(text)
    if not items:
        flags.append("missing_items")
    for item in items:
        name = item["name"]
        qty = Decimal(str(item["quantity"]))
        if not qty.is_finite() or qty <= 0 or qty > 100000:
            flags.append(f"invalid_quantity:{name}")
            continue
        product = match_product(name, customer, state["products"], spec.rules)
        if product is None:
            flags.append(f"missing_sku:{name}")
            continue
        if item.get("unit") != product["unit"]:
            flags.append(f"ambiguous_unit:{product['sku']}")
        if spec.template == "orders":
            cents = customer["prices"].get(product["sku"], product["price_cents"])
        else:
            margin = Decimal(str(customer.get("margin", spec.rules.get("margin", 0.25))))
            if margin < 0 or margin >= 1:
                raise ValueError("Margin must be in [0, 1)")
            cents = int(
                (Decimal(product["supplier_cents"]) / (1 - margin)).quantize(Decimal(1), rounding=ROUND_CEILING)
            )
        previous = (
            next((line for line in lines if line["sku"] == product["sku"]), None)
            if spec.rules.get("aggregate_duplicates", True)
            else None
        )
        if previous:
            previous["quantity"] += float(qty)
            previous["line_total_cents"] = int(Decimal(str(previous["quantity"])) * cents)
        else:
            lines.append(
                {
                    "sku": product["sku"],
                    "name": product["name"],
                    "unit": product["unit"],
                    "quantity": float(qty),
                    "unit_price_cents": cents,
                    "line_total_cents": int(qty * cents),
                }
            )
    if spec.template == "orders" and spec.rules.get("check_inventory", True):
        for line in lines:
            product = next(p for p in state["products"] if p["sku"] == line["sku"])
            if line["quantity"] > product["stock"]:
                flags.append(f"insufficient_stock:{line['sku']}")
    return {
        "kind": spec.template,
        "customer_id": customer["id"],
        "request_id": request_id,
        "lines": lines,
        "flags": flags,
        "total_cents": sum(line["line_total_cents"] for line in lines),
        "requires_approval": True,
    }


def prepare_hiring(text, state):
    result = {"kind": "hiring", "lines": [], "total_cents": 0, "requires_approval": True, "flags": []}
    if re.search(r"\b(reject|screen|rank|age|gender|race)\b", text, re.IGNORECASE):
        result["flags"] = ["unsupported_employment_decision"]
        return result
    candidate = next((c for c in state["candidates"] if c["name"].lower() in text.lower()), None)
    if not candidate:
        result["flags"] = ["unknown_candidate"]
        return result
    action = "follow_up" if "follow" in text.lower() else "schedule"
    availability = next((a for a in state["availability"] if a["job_id"] == candidate["job_id"]), None)
    result.update(
        candidate_id=candidate["id"],
        job_id=candidate["job_id"],
        action_type=action,
        slot=availability["slot"] if availability and action == "schedule" else None,
        message=f"Please confirm your {action.replace('_', ' ')} for {candidate['name']}.",
    )
    if action == "schedule" and not availability:
        result["flags"].append("no_availability")
    return result


def apply_operation(output, state, operation_id):
    """Only invoked at an approved write boundary, including isolated evaluation writes."""
    if output["flags"]:
        raise ValueError("Flagged operations require corrected input and a new approval")
    if output["kind"] == "orders":
        if any(o.get("operation_id") == operation_id for o in state["orders"]):
            return
        for line in output["lines"]:
            product = next(p for p in state["products"] if p["sku"] == line["sku"])
            if product["stock"] < line["quantity"]:
                raise ValueError("Inventory changed since approval")
        for line in output["lines"]:
            next(p for p in state["products"] if p["sku"] == line["sku"])["stock"] -= line["quantity"]
        state["orders"].append({**output, "id": operation_id, "operation_id": operation_id})
    elif output["kind"] == "quotes":
        state["quotes"].append({**output, "id": operation_id, "operation_id": operation_id})
    elif output["kind"] == "hiring":
        state["communications"].append(
            {
                "id": operation_id,
                "operation_id": operation_id,
                "candidate_id": output["candidate_id"],
                "message": output["message"],
            }
        )
        candidate = next(c for c in state["candidates"] if c["id"] == output["candidate_id"])
        candidate["stage"] = "scheduled" if output["action_type"] == "schedule" else "followed_up"
