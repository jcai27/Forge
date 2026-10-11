"""Build inputs: what a build is given besides the request.

Two kinds, with different jobs. Business context documents say how the customer operates and are
read by the builder only. A dataset is the source of truth: real examples with known correct
answers, turned into evaluation cases. The split is decided here, in code, and the builder is only
ever shown the development part.
"""

import asyncio
import csv
import hashlib
import io
import json
import re
from urllib.parse import urljoin, urlparse

from sqlalchemy import func, select

from factory.connectors import bounded_bytes
from factory.http_transport import pinned_client
from factory.models import ContextDocument, Dataset, EvaluationCase, EvaluationSuite
from factory.schemas import AgentSpec
from factory.security import redact_tenant

MAX_DATASET_BYTES = 5_000_000
MAX_ROWS = 50_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 20_000
MAX_SPLIT = 2_000
MAX_LABELS = 200
MAX_TABLE_ROWS = 500
MAX_TABLE_FIELDS = 20
MAX_TABLE_CELL_CHARS = 500
FETCH_TIMEOUT = 30
MAX_HOPS = 4
FETCH_TYPES = ("text/", "application/json", "application/x-ndjson", "application/csv", "application/octet-stream")

MAX_DOCUMENTS = 20
MAX_DOCUMENT_CHARS = 200_000
# What one model request may carry of the documents; the rest is reachable through read_context.
CONTEXT_BUDGET_CHARS = 40_000
CONTEXT_PAGE_CHARS = 8_000

# development: the builder reads these. selection: each change is scored on these and the builder never
# reads them. regression: must never break again. validation: held back for the final judgement.
SPLITS = ("development", "selection", "regression", "validation")
ANSWER_COLUMNS = ("label", "labels", "category", "intent", "class", "target", "answer", "expected", "output")
ANSWER_PREFIX = "expected_"
IDENTIFIER_COLUMNS = ("id", "idx", "index", "uuid", "row", "row_id")


class IntakeError(ValueError):
    """The supplied data cannot be used as it is. The message says what to change."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _digest(*parts):
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _scalar(value, column):
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
            raise IntakeError(f"A value in column {column!r} is longer than {MAX_CELL_CHARS} characters")
        return value
    if isinstance(value, list):
        return _table(value, column)
    raise IntakeError(
        f"Column {column!r} holds nested values; a value is one thing, or a list of rows of single values"
    )


def _table(rows, column):
    """A table as a value: a list of rows, each a flat object. The one nested shape that is accepted,
    for answers such as the line items of an invoice."""
    if len(rows) > MAX_TABLE_ROWS:
        raise IntakeError(f"A table in column {column!r} has more than {MAX_TABLE_ROWS} rows")
    for row in rows:
        if not isinstance(row, dict) or not row or len(row) > MAX_TABLE_FIELDS:
            raise IntakeError(
                f"Column {column!r}: each row of a table must be an object of up to {MAX_TABLE_FIELDS} fields"
            )
        for field, item in row.items():
            if not isinstance(field, str) or not field.isidentifier():
                raise IntakeError(f"Column {column!r}: {field!r} is not a usable field name")
            if not (item is None or isinstance(item, (str, int, float, bool))) or len(str(item)) > MAX_TABLE_CELL_CHARS:
                raise IntakeError(f"Column {column!r}: a table cell must be one short value")
    return rows


def parse_records(text, format=None):
    """Rows as dictionaries from CSV, TSV, JSON or JSON Lines. Bounded; never guesses past a clear error."""
    if len(text.encode()) > MAX_DATASET_BYTES:
        raise IntakeError(f"The dataset is larger than {MAX_DATASET_BYTES // 1_000_000} MB")
    text = text.lstrip("﻿")
    stripped = text.lstrip()
    if not stripped:
        raise IntakeError("The dataset is empty")
    format = (format or "").lower() or ("json" if stripped[0] in "[{" else "csv")
    if format in ("json", "jsonl", "ndjson"):
        try:
            data = json.loads(stripped)
        except ValueError:
            try:
                data = [json.loads(line) for line in stripped.splitlines() if line.strip()]
            except ValueError:
                raise IntakeError("The dataset is not valid JSON or JSON Lines") from None
        if isinstance(data, dict):
            # Common wrappers: {"data": [...]} and the row-server shape {"rows": [{"row": {...}}]}.
            data = next(
                (data[key] for key in ("rows", "data", "records", "items") if isinstance(data.get(key), list)), None
            )
        if not isinstance(data, list):
            raise IntakeError("JSON datasets must be a list of objects")
        rows = [row["row"] if isinstance(row, dict) and isinstance(row.get("row"), dict) else row for row in data]
        if any(not isinstance(row, dict) for row in rows):
            raise IntakeError("Every dataset row must be an object of column to value")
    elif format in ("csv", "tsv"):
        first = stripped.splitlines()[0]
        delimiter = "\t" if format == "tsv" or (first.count("\t") > first.count(",")) else ","
        reader = csv.reader(io.StringIO(stripped), delimiter=delimiter)
        try:
            header = [name.strip() for name in next(reader)]
            if len(set(header)) != len(header) or any(not name for name in header):
                raise IntakeError("The first line must name every column, each name once")
            rows = []
            for line in reader:
                if not any(cell.strip() for cell in line):
                    continue
                if len(line) != len(header):
                    raise IntakeError(f"Row {reader.line_num} has {len(line)} values for {len(header)} columns")
                rows.append(dict(zip(header, line, strict=True)))
        except csv.Error:
            raise IntakeError("The dataset is not valid CSV") from None
        _type_numbers(rows, header)
    else:
        raise IntakeError("Supported formats are csv, tsv, json and jsonl")
    if not rows:
        raise IntakeError("The dataset has no rows")
    if len(rows) > MAX_ROWS:
        raise IntakeError(f"The dataset has more than {MAX_ROWS} rows; send a sample")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if len(columns) > MAX_COLUMNS:
        raise IntakeError(f"The dataset has more than {MAX_COLUMNS} columns")
    return [{column: _scalar(row.get(column), column) for column in columns} for row in rows]


def _type_numbers(rows, columns):
    """A delimited file holds only text. A column in which every value is a whole number written the
    plain way becomes integers, so an amount is compared and returned as a number. Anything else stays
    text: 02134 is a postcode and 1.50 would not survive the round trip."""
    for column in columns:
        values = [row[column].strip() for row in rows if row[column].strip()]
        if values and all(re.fullmatch(r"0|-?[1-9]\d{0,17}", value) for value in values):
            for row in rows:
                row[column] = int(row[column]) if row[column].strip() else None


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def guess_mapping(records):
    """Which column is the correct answer and which are the input. Refuses rather than guessing wrongly."""
    columns = list(records[0])
    # A file that marks its answers says so in the column names: expected_decision, expected_amount.
    # That is the only way to give several answer fields without naming the mapping by hand.
    marked = {column[len(ANSWER_PREFIX) :]: column for column in columns if column.lower().startswith(ANSWER_PREFIX)}
    if marked and all(field.isidentifier() for field in marked):
        inputs = [c for c in columns if c not in marked.values() and c.lower() not in IDENTIFIER_COLUMNS]
        if not inputs:
            raise IntakeError("Every column is marked as an answer; at least one must be the request")
        fields = {"text": inputs[0]} if len(inputs) == 1 else {column: column for column in inputs}
        return {"input": fields, "expected": marked}
    lowered = {column.lower(): column for column in columns}
    answer = next((lowered[name] for name in ANSWER_COLUMNS if name in lowered), None)
    inputs = [column for column in columns if column != answer and column.lower() not in IDENTIFIER_COLUMNS]
    if answer is None and len(inputs) == 2:
        # With two columns and no telling name, the answer is the one that repeats.
        distinct = {column: len({canonical(row[column]) for row in records}) for column in inputs}
        low, high = sorted(inputs, key=distinct.get)
        if distinct[low] * 2 <= distinct[high]:
            answer, inputs = low, [high]
    if answer is None or not inputs:
        raise IntakeError(
            "Could not tell which column holds the correct answer. Name it: columns are " + ", ".join(columns)
        )
    # A single input column is the request text, which is what a deployed agent is sent.
    fields = {"text": inputs[0]} if len(inputs) == 1 else {column: column for column in inputs}
    return {"input": fields, "expected": {answer: answer}}


def check_mapping(mapping, records):
    columns = set(records[0])
    for side in ("input", "expected"):
        fields = mapping.get(side) or {}
        if not fields:
            raise IntakeError(f"The mapping needs at least one {side} field")
        for field, column in fields.items():
            if not field.isidentifier() or field.startswith("_"):
                raise IntakeError(f"{field!r} is not a usable field name")
            if column not in columns:
                raise IntakeError(f"The dataset has no column {column!r}")
    if set(mapping["input"].values()) & set(mapping["expected"].values()):
        raise IntakeError("A column cannot be both input and correct answer")
    for column in mapping["input"].values():
        if any(isinstance(row.get(column), list) for row in records):
            raise IntakeError(
                f"Column {column!r} holds a table; a table can be a correct answer but not part of the request"
            )
    return {"input": dict(mapping["input"]), "expected": dict(mapping["expected"])}


def to_examples(records, mapping):
    """(input, expected) pairs, with unusable and contradictory rows left out and counted."""
    dropped = {"missing_answer": 0, "empty_input": 0, "duplicate_input": 0, "contradictory_answer": 0}
    by_input = {}
    for row in records:
        item_input = {field: row[column] for field, column in mapping["input"].items()}
        expected = {field: row[column] for field, column in mapping["expected"].items()}
        if any(_blank(value) for value in expected.values()):
            dropped["missing_answer"] += 1
        elif all(_blank(value) for value in item_input.values()):
            dropped["empty_input"] += 1
        else:
            by_input.setdefault(canonical(item_input), []).append((item_input, expected))
    examples = []
    for group in by_input.values():
        if len({canonical(expected) for _, expected in group}) > 1:
            # The same request with two different right answers teaches and measures nothing.
            dropped["contradictory_answer"] += len(group)
            continue
        dropped["duplicate_input"] += len(group) - 1
        examples.append(group[0])
    return examples, dropped


def split_examples(examples, sizes, seed):
    """Assign examples to splits: deterministic, balanced over answers, exact in size.

    Order depends only on the seed and each row's content, so the same data always splits the same way
    and adding rows does not reshuffle the rest. Answers are interleaved so a small sample still covers
    as many of them as it can.
    """
    wanted = {split: min(max(0, int(sizes.get(split, 0))), MAX_SPLIT) for split in SPLITS}
    if not wanted["development"] or not wanted["validation"]:
        raise IntakeError("A dataset needs development examples to build from and held-out examples to judge by")
    total = sum(wanted.values())
    if len(examples) < total:
        # Too little data for the request: keep the proportions.
        scale = len(examples) / total
        wanted = {split: int(size * scale) for split, size in wanted.items()}
        if not wanted["development"] or not wanted["validation"]:
            raise IntakeError("There are too few usable rows to hold some back for judging")
        total = sum(wanted.values())
    by_answer = {}
    for item in examples:
        by_answer.setdefault(canonical(item[1]), []).append(item)
    for rows in by_answer.values():
        rows.sort(key=lambda item: _digest(seed, canonical(item[0])))
    order, depth = [], 0
    while len(order) < total:
        # One of each answer per round, the answers in a different order each round.
        layer = [(answer, rows[depth]) for answer, rows in by_answer.items() if depth < len(rows)]
        layer.sort(key=lambda pair: _digest(seed, str(depth), pair[0]))
        order.extend(item for _, item in layer)
        depth += 1
    chosen = order[:total]
    per_answer = {}
    for _, expected in chosen:
        per_answer[canonical(expected)] = per_answer.get(canonical(expected), 0) + 1
    assigned = {split: [] for split in wanted}
    placed = {}
    for item_input, expected in chosen:
        answer = canonical(expected)
        # Each answer is shared out in the same proportions as the whole; among equals, the split
        # with the most room left takes the next example. Sizes stay exact because a full split is skipped.
        split = max(
            (name for name in wanted if len(assigned[name]) < wanted[name]),
            key=lambda name: (
                per_answer[answer] * wanted[name] / total - placed.get((answer, name), 0),
                1 - len(assigned[name]) / wanted[name],
                wanted[name],
            ),
        )
        placed[answer, split] = placed.get((answer, split), 0) + 1
        assigned[split].append((item_input, expected))
    return assigned


def _table_schema(tables):
    """The shape of a table answer: the fields its rows have, and which of them every row has."""
    rows = [row for table in tables for row in table]
    fields = list(dict.fromkeys(field for row in rows for field in row))
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {field: {"type": _json_type([row.get(field) for row in rows])} for field in fields},
            "required": [field for field in fields if all(not _blank(row.get(field)) for row in rows)],
        },
    }


def _json_type(values):
    kinds = {type(value) for value in values if value is not None}
    if kinds <= {bool}:
        return "boolean"
    if kinds <= {int}:
        return "integer"
    if kinds <= {int, float} and bool not in kinds:
        return "number"
    return "string"


def derive_schemas(examples):
    """The agent's input and output shape, read off the data."""
    inputs, outputs = {}, {}
    for item_input, expected in examples:
        for field, value in item_input.items():
            inputs.setdefault(field, []).append(value)
        for field, value in expected.items():
            outputs.setdefault(field, []).append(value)
    input_schema = {
        "type": "object",
        "properties": {field: {"type": _json_type(values)} for field, values in inputs.items()},
        "required": [field for field, values in inputs.items() if all(not _blank(value) for value in values)],
        "additionalProperties": False,
    }
    properties, labels = {}, {}
    for field, values in outputs.items():
        if all(isinstance(value, list) for value in values):
            properties[field] = _table_schema(values)
            continue
        kind = _json_type(values)
        properties[field] = {"type": kind}
        distinct = sorted({value for value in values}, key=str)
        # A text answer that repeats is a fixed vocabulary: the agent must choose from it, not invent.
        # A number is never one: a count or an amount not seen in the examples is still a valid answer.
        if kind == "string" and len(distinct) <= MAX_LABELS and len(distinct) * 2 <= len(values):
            properties[field]["enum"] = distinct
            labels[field] = distinct
    output_schema = {"type": "object", "properties": properties, "required": list(outputs)}
    return input_schema, output_schema, labels


def answer_checks(examples, labels):
    """How each answer field is judged. A table is judged row by row. Free text of several words is
    judged as a reading, nearly the same being the same. Anything else must be exactly right: a label
    from a fixed vocabulary, a number, a date, a code."""
    ops = {}
    for field in examples[0][1]:
        values = [expected[field] for _, expected in examples]
        if all(isinstance(value, list) for value in values):
            ops[field] = "rows_match"
        elif field not in labels and sum(isinstance(value, str) and " " in value.strip() for value in values) * 2 > len(
            values
        ):
            ops[field] = "similar"
        else:
            ops[field] = "equals"
    return ops


def agent_suite(db, agent):
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    if suite is None:
        suite = EvaluationSuite(org_id=agent.org_id, agent_id=agent.id, name=f"{agent.name} evaluation suite")
        db.add(suite)
        db.flush()
    return suite


def truth_source(db, agent):
    """What a build of this agent would be judged against, or None when there is nothing.

    Cases to build from and cases held back are the source of truth. Without them a build may start
    only when someone has stated that the task needs no data, and then every drafted case still waits
    for a person to accept it.
    """
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    counts = {}
    if suite is not None:
        counts = dict(
            db.execute(
                select(EvaluationCase.split, func.count())
                .where(EvaluationCase.suite_id == suite.id)
                .group_by(EvaluationCase.split)
            ).all()
        )
    if counts.get("development") and counts.get("validation"):
        return "cases"
    if agent.no_data_reason:
        return "rules"
    return None


def attach_dataset(db, agent, name, records, mapping=None, sizes=None, origin="upload", source_url="", pages=None):
    """Turn rows into evaluation cases and pin the agent's input and output shape to the data.

    Returns the dataset and the new version. The caller owns authorization, the active-build check and
    the commit. pages maps a document's text to its stored pages, for documents with scanned pages.
    """
    from factory.builder import persist_version
    from factory.models import AgentVersion

    records = redact_tenant(db, agent.org_id, records)
    mapping = check_mapping(mapping, records) if mapping else guess_mapping(records)
    examples, dropped = to_examples(records, mapping)
    suite = agent_suite(db, agent)
    existing = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == suite.id)))
    seen = {canonical(case.input) for case in existing}
    fresh = [item for item in examples if canonical(item[0]) not in seen]
    # A row already in the suite must not come back in another split: that would leak a held-out answer.
    dropped["already_in_suite"] = len(examples) - len(fresh)
    if not fresh:
        raise IntakeError("No usable rows: every row was empty, contradictory or already imported")
    sizes = sizes or {"development": 60, "selection": 60, "regression": 0, "validation": 60}
    seed = _digest(agent.id, name)
    assigned = split_examples(fresh, sizes, seed)
    used = [item for rows in assigned.values() for item in rows]
    # The vocabulary comes from every usable row, so an answer that is rare in the sample is still allowed.
    input_schema, output_schema, labels = derive_schemas(fresh)
    latest = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
    )
    spec = AgentSpec.model_validate(latest.spec)
    previous = db.scalar(select(Dataset).where(Dataset.agent_id == agent.id).order_by(Dataset.created_at.desc()))
    if previous is not None and (
        set(previous.mapping["input"]) != set(mapping["input"])
        or set(previous.mapping["expected"]) != set(mapping["expected"])
    ):
        raise IntakeError("This agent already has data with different fields; a second dataset must use the same ones")
    if previous is not None:
        for field, values in labels.items():
            known = spec.output_schema.get("properties", {}).get(field, {}).get("enum")
            if known:
                labels[field] = sorted(set(values) | set(known), key=str)
                output_schema["properties"][field]["enum"] = labels[field]
    spec.input_schema, spec.output_schema = input_schema, output_schema
    ops = answer_checks(fresh, labels)
    content_hash = _digest(*sorted(canonical(item) for item in used))
    dataset = Dataset(
        org_id=agent.org_id,
        agent_id=agent.id,
        name=name,
        origin=origin,
        source_url=source_url,
        content_hash=content_hash,
        rows=len(records),
        mapping=mapping,
        profile={
            "rows": len(records),
            "usable_rows": len(fresh),
            "dropped": {key: count for key, count in dropped.items() if count},
            "splits": {split: len(rows) for split, rows in assigned.items()},
            "input_fields": list(mapping["input"]),
            "expected_fields": list(mapping["expected"]),
            "answers": labels,
            # Only development rows: this profile is shown to the builder.
            "examples": [{"input": item[0], "expected": item[1]} for item in assigned["development"][:5]],
        },
    )
    db.add(dataset)
    db.flush()
    start = len(existing)
    for split, rows in assigned.items():
        for item_input, expected in rows:
            start += 1
            db.add(
                EvaluationCase(
                    org_id=agent.org_id,
                    suite_id=suite.id,
                    name=f"{name} #{start}"[:200],
                    split=split,
                    source="dataset",
                    input=item_input,
                    assertions=[
                        {"op": ops[field], "path": field, "value": value, "category": "structured_accuracy"}
                        for field, value in expected.items()
                    ],
                    critical=False,
                    environment={},
                    dataset_id=dataset.id,
                    # A field whose text was read from scanned pages keeps the pages it was read from.
                    documents={
                        field: pages[value]
                        for field, value in item_input.items()
                        if pages and isinstance(value, str) and value in pages
                    },
                )
            )
    if not existing:
        suite.name = f"{name} examples"[:200]
    version = persist_version(db, agent, spec, f"Input and output shape taken from the dataset {name!r}"[:1000])
    # Earlier evidence was measured against a different suite.
    agent.best_version_id = None
    db.flush()
    return dataset, version


def remove_dataset(db, agent, dataset):
    """Take a dataset and everything measured on it out of the agent.

    Its cases go, and with them the results recorded against them, so no score that included those
    rows is left standing as evidence. Earlier versions must be evaluated again to be approved.
    """
    from factory.models import EvaluationResult

    case_ids = list(db.scalars(select(EvaluationCase.id).where(EvaluationCase.dataset_id == dataset.id)))
    results = 0
    for start in range(0, len(case_ids), 500):
        chunk = case_ids[start : start + 500]
        for result in db.scalars(select(EvaluationResult).where(EvaluationResult.case_id.in_(chunk))):
            db.delete(result)
            results += 1
    db.flush()
    for start in range(0, len(case_ids), 500):
        for case in db.scalars(select(EvaluationCase).where(EvaluationCase.id.in_(case_ids[start : start + 500]))):
            db.delete(case)
    db.delete(dataset)
    agent.best_version_id = None
    db.flush()
    return {"cases": len(case_ids), "results": results}


async def fetch_dataset(url):
    """Download a public file over the pinned transport: https, default port, no credentials, bounded."""
    async with asyncio.timeout(FETCH_TIMEOUT):
        for _ in range(MAX_HOPS + 1):
            url = url.split("#", 1)[0]
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise IntakeError("A dataset address must be a credential-free https URL")
            if parsed.port not in (None, 443):
                raise IntakeError("A dataset address must use the default https port")
            # A new origin-scoped client per hop: every redirect target is validated and pinned again.
            async with pinned_client(url, [parsed.hostname], timeout=FETCH_TIMEOUT) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": "text/csv,application/json,text/plain;q=0.9,*/*;q=0.1",
                        "Accept-Encoding": "gzip, deflate, identity",
                        "User-Agent": "AgentFactoryIntake/1.0",
                    },
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise IntakeError("The address redirects nowhere")
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        raise IntakeError(f"The address answered HTTP {response.status_code}")
                    kind = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if kind and not kind.startswith(FETCH_TYPES):
                        raise IntakeError("The address does not serve a text dataset")
                    try:
                        body = await bounded_bytes(response, MAX_DATASET_BYTES)
                    except ValueError:
                        raise IntakeError(f"The file is larger than {MAX_DATASET_BYTES // 1_000_000} MB") from None
            try:
                return body.decode("utf-8")
            except UnicodeDecodeError:
                raise IntakeError("The file is not UTF-8 text") from None
    raise IntakeError("The address redirects too many times")


def add_document(db, agent, name, text):
    count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(ContextDocument.chars), 0)).where(
            ContextDocument.agent_id == agent.id
        )
    ).one()
    if count >= MAX_DOCUMENTS:
        raise IntakeError(f"An agent holds at most {MAX_DOCUMENTS} context documents")
    if "\x00" in text:
        raise IntakeError("Context documents must be plain text")
    if len(text) > MAX_DOCUMENT_CHARS or total + len(text) > MAX_DOCUMENT_CHARS * 3:
        raise IntakeError("The context documents are too large; attach the parts that describe this task")
    if db.scalar(select(ContextDocument).where(ContextDocument.agent_id == agent.id, ContextDocument.name == name)):
        raise IntakeError("This agent already has a document with that name")
    # A credential pasted into a procedure document is removed before it is stored.
    text = redact_tenant(db, agent.org_id, text)
    document = ContextDocument(
        org_id=agent.org_id,
        agent_id=agent.id,
        name=name,
        text=text,
        chars=len(text),
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    db.add(document)
    db.flush()
    return document


def documents(db, agent):
    return list(
        db.scalars(
            select(ContextDocument)
            .where(ContextDocument.agent_id == agent.id, ContextDocument.org_id == agent.org_id)
            .order_by(ContextDocument.created_at, ContextDocument.id)
        )
    )


def context_payload(db, agent, budget=CONTEXT_BUDGET_CHARS):
    """The documents as a builder may be shown them in one request: whole if they fit, otherwise the
    opening of each with a note that the rest is there to be read."""
    rows = documents(db, agent)
    if not rows:
        return []
    share = max(1_000, budget // len(rows))
    payload = []
    for row in rows:
        text = redact_tenant(db, agent.org_id, row.text)
        payload.append(
            {"name": row.name, "characters": row.chars, "text": text[:share], "truncated": len(text) > share}
        )
    return payload


def data_payload(db, agent):
    """What the builder is told about the data: its shape, vocabulary and a few development rows."""
    rows = list(db.scalars(select(Dataset).where(Dataset.agent_id == agent.id).order_by(Dataset.created_at)))
    return [
        redact_tenant(
            db,
            agent.org_id,
            {
                "name": row.name,
                "input_fields": row.profile["input_fields"],
                "expected_fields": row.profile["expected_fields"],
                "answers": row.profile["answers"],
                "development_examples": row.profile["examples"],
                "development_cases": row.profile["splits"]["development"],
            },
        )
        for row in rows
    ]
