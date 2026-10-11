"""Table answers: an invoice's line items are graded row by row, not all or nothing."""

import json
from types import SimpleNamespace

import pytest

from factory.evaluation import grade, graded_score, meets_expectations
from factory.intake import IntakeError, answer_checks, check_mapping, derive_schemas, parse_records, to_examples
from factory.tables import match_rows, same, wrong_fields

LINES = [
    {
        "code": "206539",
        "description": "CASE 6-2.5 DZN GFS LARGE EGGS",
        "quantity": 5,
        "unit_price": 9.37,
        "amount": 46.85,
    },
    {"code": "206032", "description": "CASE 25# TOMATO 5X6 XLRG", "quantity": 2, "unit_price": 21.2, "amount": 42.4},
    {"code": "284998", "description": "CASE 1-24CT LEAF LETTUCE", "quantity": 1, "unit_price": 15.91, "amount": 15.91},
]


def test_values_are_compared_as_a_person_checking_them_would():
    # A number is a number however it is written.
    assert same(9.37, "9.370") and same(5, 5.0) and same(1240, "1,240") and not same(9.37, 9.38)
    # Text ignores case and spacing; a phrase may differ by a letter or two; a code may not.
    assert same("Steel City's Diner", "STEEL  CITY'S DINER")
    assert same("CASE 2-10# GFS PEELD SLCD AMER", "CASE 2-10# GFS PEELED SLCD AMER")
    assert not same("206539", "206530") and not same("CASE 25# TOMATO", "CASE 4-5# LETTUCE SALAD MIX")
    assert same(True, True) and not same(True, "true") and not same("x", None) and same(None, None)
    assert wrong_fields(LINES[0], {**LINES[0], "unit_price": 9.87, "note": "extra fields are not judged"}) == [
        "unit_price"
    ]


def test_rows_are_lined_up_in_order_so_one_bad_row_costs_one_row():
    misread = [LINES[0], {**LINES[1], "unit_price": 27.2}, LINES[2]]
    pairs, extra = match_rows(LINES, misread)
    assert [wrong_fields(wanted, given) for wanted, given in pairs] == [[], ["unit_price"], []] and extra == []
    # A row left out is missing; the rows after it are still matched with their own.
    pairs, extra = match_rows(LINES, [LINES[0], LINES[2]])
    assert [given is None or not wrong_fields(wanted, given) for wanted, given in pairs] == [True, True, True]
    assert [given for _, given in pairs][1] is None and extra == []
    # A row that was not expected is extra, and the expected ones are unaffected.
    invented = {"code": "999999", "description": "FUEL SURCHARGE", "quantity": 1, "unit_price": 4.0, "amount": 4.0}
    pairs, extra = match_rows(LINES, [LINES[0], invented, LINES[1], LINES[2]])
    assert all(not wrong_fields(wanted, given) for wanted, given in pairs) and extra == [invented]
    assert match_rows(LINES, "not a table") == ([(row, None) for row in LINES], [])


def graded(output, assertions):
    run = SimpleNamespace(output=output, status="completed", error=None, metrics={"tools_offered": 0})
    case = SimpleNamespace(assertions=assertions, input={}, source="dataset", rubric=None)
    return grade(run, case, {})


def test_a_table_answer_earns_credit_per_row_and_still_passes_only_when_whole():
    assertions = [
        {"op": "equals", "path": "invoice_number", "value": "131862443", "category": "structured_accuracy"},
        {"op": "similar", "path": "customer", "value": "STEEL CITY'S DINER", "category": "structured_accuracy"},
        {"op": "rows_match", "path": "items", "value": LINES, "category": "structured_accuracy"},
    ]
    right = {"invoice_number": "131862443", "customer": "Steel City's Diner", "items": LINES}
    checks, failures = graded(right, assertions)
    assert failures == [] and graded_score(checks) == 1
    assert meets_expectations(SimpleNamespace(assertions=assertions), right)

    one_off = {**right, "items": [LINES[0], {**LINES[1], "amount": 44.4}, LINES[2]]}
    checks, failures = graded(one_off, assertions)
    rows = [check for check in checks if check.get("table") == "items"]
    # Three rows and the no-extra-rows check: one row is wrong, and it says which field.
    assert [check["passed"] for check in rows] == [True, False, True, True] and rows[1]["wrong"] == ["amount"]
    assert failures == ["structured_accuracy"] and graded_score(checks) == pytest.approx(5 / 6)
    assert not meets_expectations(SimpleNamespace(assertions=assertions), one_off)

    # No table in the answer at all: every expected row is missing, and nothing crashes.
    checks, _ = graded({"invoice_number": "131862443", "customer": "Steel City's Diner"}, assertions)
    assert sum(not check["passed"] for check in checks if check.get("table") == "items") == 3


def test_an_examples_file_may_give_a_table_as_an_answer_but_not_as_part_of_the_request():
    rows = [
        {
            "invoice": f"Invoice text {n}",
            "expected_customer": f"Diner number {n}",
            "expected_items": [{**LINES[0], "quantity": n}],
        }
        for n in range(1, 13)
    ]
    records = parse_records("\n".join(json.dumps(row) for row in rows), "jsonl")
    mapping = {"input": {"text": "invoice"}, "expected": {"customer": "expected_customer", "items": "expected_items"}}
    examples, _ = to_examples(records, mapping)
    _, output, labels = derive_schemas(examples)
    items = output["properties"]["items"]
    assert items["type"] == "array" and items["items"]["properties"]["unit_price"] == {"type": "number"}
    assert set(items["items"]["required"]) == set(LINES[0])
    # Free text is judged as a reading, the table row by row.
    assert answer_checks(examples, labels) == {"customer": "similar", "items": "rows_match"}
    for bad in (
        '{"invoice": "x", "expected_items": [[1, 2]]}',
        '{"invoice": "x", "expected_items": [{"a": {"b": 1}}]}',
    ):
        with pytest.raises(IntakeError):
            parse_records(bad, "json")
    with pytest.raises(IntakeError, match="nested"):
        parse_records('[{"invoice": {"a": 1}, "answer": "x"}]', "json")
    with pytest.raises(IntakeError, match="not part of the request"):
        check_mapping({"input": {"items": "expected_items"}, "expected": {"customer": "expected_customer"}}, records)
