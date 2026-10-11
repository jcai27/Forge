"""Grading answers that are tables: a list of rows, each a few named values.

An invoice's line items are the case in point. The expected rows and the answered rows are lined up
in order, each expected row is one check, and a row is right when every one of its fields is. Rows
the agent added that were not expected are one more check. So a forty-line invoice with one misread
price scores thirty-nine in forty, not nothing.

Fields are compared the way a person checking them would: a number is a number however it is
written, text is compared without regard to case or spacing, and a phrase of several words counts
as the same when it is nearly so, because two readings of a faint description rarely agree to the
letter. A code, being one word, must match exactly.
"""

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

# How alike two phrases must be to count as the same reading.
PHRASE_SIMILARITY = 0.85
TOLERANCE = Decimal("0.000001")


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "").removeprefix("$")
        try:
            return Decimal(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None
        except InvalidOperation:
            return None
    return None


def _text(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def same(expected, actual):
    """Whether an answered value is the expected one."""
    if expected is None or expected == "":
        return actual is None or actual == ""
    if actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, (int, float)):
        number = _number(actual)
        return number is not None and abs(number - Decimal(str(expected))) <= TOLERANCE
    if isinstance(expected, str):
        if not isinstance(actual, (str, int, float)):
            return False
        wanted, given = _text(expected), _text(actual)
        if wanted == given:
            return True
        # Several words: a phrase. One word: a code or a number, which is right or wrong.
        return " " in wanted and SequenceMatcher(None, wanted, given).ratio() >= PHRASE_SIMILARITY
    return expected == actual


def wrong_fields(expected, actual):
    """The fields of an expected row that the answered row gets wrong. A field the key leaves out is not judged."""
    if not isinstance(actual, dict):
        return sorted(expected)
    return sorted(field for field, value in expected.items() if not same(value, actual.get(field)))


def _signature(row, fields):
    return tuple(
        _text(row.get(field)) if _number(row.get(field)) is None else str(_number(row.get(field)).normalize())
        for field in fields
    )


def match_rows(expected, actual):
    """Line expected rows up with answered rows, in order.

    Returns (pairs, extra): pairs is one (expected row, answered row or None) per expected row, and
    extra is the answered rows left over. Rows that agree outright anchor the alignment; between
    anchors, rows are paired in order, so a misread row is compared with the row in its place.
    """
    if not isinstance(actual, list):
        return [(row, None) for row in expected], []
    answered = [row for row in actual if isinstance(row, dict)]
    extra = [row for row in actual if not isinstance(row, dict)]
    fields = sorted({field for row in expected for field in row})
    blocks = SequenceMatcher(
        None,
        [_signature(row, fields) for row in expected],
        [_signature(row, fields) for row in answered],
        autojunk=False,
    ).get_opcodes()
    pairs = []
    for _, first, last, start, end in blocks:
        wanted, given = expected[first:last], answered[start:end]
        pairs += [(row, given[index] if index < len(given) else None) for index, row in enumerate(wanted)]
        extra += given[len(wanted) :]
    return pairs, extra


def row_checks(path, expected, actual, category="structured_accuracy"):
    """One check per expected row, and one for rows that were not expected."""
    pairs, extra = match_rows(expected, actual)
    checks = []
    for index, (wanted, given) in enumerate(pairs):
        wrong = wrong_fields(wanted, given)
        checks.append(
            {
                "category": category,
                "path": f"{path}[{index}]",
                "table": path,
                "row": index,
                "scope": "output",
                "passed": not wrong,
                "expected": wanted,
                "actual": given,
                "wrong": wrong,
            }
        )
    checks.append(
        {
            "category": category,
            "path": f"{path}[+]",
            "table": path,
            "scope": "output",
            "passed": not extra,
            "expected": [],
            "actual": extra,
            "evidence": "Rows that were not expected" if extra else "No unexpected rows",
        }
    )
    return checks


def rows_met(expected, actual):
    pairs, extra = match_rows(expected, actual)
    return not extra and all(not wrong_fields(wanted, given) for wanted, given in pairs)
