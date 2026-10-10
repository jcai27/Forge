"""Deterministic output verifiers. A closed vocabulary: no expressions, no code, no model calls."""

from jsonschema import Draft202012Validator

MISSING = object()


def get_path(value, path):
    if path in ("$", ""):
        return value
    for segment in path.split("."):
        if isinstance(value, list):
            value = value[int(segment)]
        elif isinstance(value, dict):
            value = value[segment]
        else:
            raise KeyError(path)
    return value


def _value(output, path):
    try:
        return get_path(output, path)
    except (KeyError, IndexError, TypeError, ValueError):
        return MISSING


def verify(verifiers, output):
    """Return a list of failures, one per violated verifier. Never raises on malformed output."""
    failures = []
    for verifier in verifiers:
        message = check(verifier, output)
        if message:
            failures.append({"id": verifier.id, "kind": verifier.kind, "message": verifier.message or message})
    return failures


def check(verifier, output):
    value = _value(output, verifier.path)
    if verifier.kind == "required":
        if value is MISSING or value in (None, "", [], {}):
            return f"{verifier.path} is required"
    elif verifier.kind == "one_of":
        if value is MISSING or value not in verifier.values:
            return f"{verifier.path} must be one of the allowed values"
    elif verifier.kind == "range":
        if value is MISSING or isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{verifier.path} must be a number"
        if verifier.minimum is not None and value < verifier.minimum:
            return f"{verifier.path} is below {verifier.minimum}"
        if verifier.maximum is not None and value > verifier.maximum:
            return f"{verifier.path} is above {verifier.maximum}"
    elif verifier.kind == "sum_equals":
        total = _value(output, verifier.total_path)
        if value is MISSING or total is MISSING or not isinstance(value, list):
            return f"{verifier.path} and {verifier.total_path} must be present"
        try:
            parts = [row[verifier.field] for row in value]
            if any(isinstance(part, bool) or not isinstance(part, (int, float)) for part in parts):
                return f"{verifier.field} values must be numbers"
            if isinstance(total, bool) or not isinstance(total, (int, float)):
                return f"{verifier.total_path} must be a number"
            if abs(sum(parts) - total) > verifier.tolerance:
                return f"sum of {verifier.field} does not equal {verifier.total_path}"
        except (KeyError, TypeError):
            return f"every item in {verifier.path} needs {verifier.field}"
    elif verifier.kind == "schema":
        if value is MISSING:
            return f"{verifier.path} is missing"
        errors = list(Draft202012Validator(verifier.expected_schema).iter_errors(value))
        if errors:
            return errors[0].message[:200]
    return None
