import hashlib
import io
import json
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from sqlalchemy import func, select

from factory.builder import apply_patch, mutable_view, optimizer_prompt
from factory.config import settings
from factory.documents import MAX_PDF_PAGES, pdf_pages, pdf_text, read_archive
from factory.intake import IntakeError
from factory.models import (
    AgentRecord,
    AgentVersion,
    AuditEvent,
    Dataset,
    Deployment,
    DocumentPage,
    DocumentReading,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    ExecutionRun,
    Organization,
    UsageRecord,
)
from factory.optimizer_tools import Investigation
from factory.reading import Reader, case_input
from factory.schemas import AgentSpec, Budget, SpecPatch
from factory.workflow import new_job
from tests.test_intake import client, direct_agent, member  # noqa: F401


def pdf(*pages):
    """A PDF whose pages each hold the given lines of text. An empty page is a scan: no text layer."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(
            "".join(
                f"BT /F1 12 Tf 1 0 0 1 50 {700 - 20 * row} Tm ({line}) Tj ET\n" for row, line in enumerate(lines)
            ).encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for name, data in files.items():
            handle.writestr(name, data)
    return buffer.getvalue()


def test_pdf_text_keeps_pages_in_order():
    text = pdf_text(pdf(["Invoice 17", "Total: $12.40"], ["Page two"]))
    assert text.index("Invoice 17") < text.index("Total: $12.40") < text.index("Page two")


def test_a_scan_is_refused_by_name_not_read_as_empty():
    with pytest.raises(IntakeError, match="page 2 has no text.*scan"):
        pdf_text(pdf(["Invoice 17"], []), "delivery.pdf")


@pytest.mark.parametrize(
    "data, message",
    [
        (b"PK\x03\x04 not a pdf", "not a PDF"),
        (b"%PDF-1.4\nnothing that parses", "could not be read"),
        (pdf(*[["x"]] * (MAX_PDF_PAGES + 1)), "more than"),
    ],
)
def test_unusable_pdfs_say_what_is_wrong(data, message):
    with pytest.raises(IntakeError, match=message):
        pdf_text(data)


def test_text_limit_is_enforced():
    with pytest.raises(IntakeError, match="more than 10 characters"):
        pdf_text(pdf(["A line that is longer than the limit"]), limit=10)


def test_archive_cells_naming_pdfs_become_their_text():
    data = archive(
        {
            "examples.csv": "invoice,order,expected_decision\ninvoices/a.pdf,a-order.pdf,pay\ninvoices/b.pdf,,hold\n",
            "invoices/a.pdf": pdf(["Invoice A"]),
            "invoices/b.pdf": pdf(["Invoice B"]),
            "orders/a-order.pdf": pdf(["Order A"]),
            "__MACOSX/._examples.csv": b"junk",
            "invoices/.DS_Store": b"junk",
        }
    )
    records, documents = read_archive(data)
    assert documents == 3
    assert [row["invoice"] for row in records] == ["Invoice A", "Invoice B"]
    # A bare file name finds the document wherever it sits, and an empty cell stays empty.
    assert records[0]["order"] == "Order A" and records[1]["order"] == ""
    assert [row["expected_decision"] for row in records] == ["pay", "hold"]


@pytest.mark.parametrize(
    "files, message",
    [
        ({"a.pdf": pdf(["A"])}, "exactly one examples file"),
        ({"one.csv": "a,b\n1,2\n", "two.csv": "a,b\n1,2\n"}, "exactly one examples file"),
        ({"examples.csv": "invoice,answer\nmissing.pdf,pay\n", "a.pdf": pdf(["A"])}, "not in the archive"),
        ({"examples.csv": "invoice,answer\nplain text,pay\n", "a.pdf": pdf(["A"])}, "names a PDF"),
        (
            {"examples.csv": "invoice,answer\na.pdf,pay\n", "x/a.pdf": pdf(["A"]), "y/a.pdf": pdf(["A"])},
            "several files",
        ),
        ({"examples.csv": "invoice,answer\na.pdf,pay\n", "a.pdf": pdf([])}, "scan"),
    ],
)
def test_unusable_archives_say_what_is_wrong(files, message):
    with pytest.raises(IntakeError, match=message):
        read_archive(archive(files))


def test_not_a_zip():
    with pytest.raises(IntakeError, match="not a zip"):
        read_archive(b"invoice,answer\n1,2\n")


def test_archive_that_unpacks_too_large_is_refused_before_reading(monkeypatch):
    monkeypatch.setattr("factory.documents.MAX_ARCHIVE_UNPACKED", 100)
    with pytest.raises(IntakeError, match="unpacks to more"):
        read_archive(archive({"examples.csv": "invoice,answer\na.pdf,pay\n", "a.pdf": pdf(["A" * 50])}))


# The endpoints. Fixtures are shared with the intake tests.


def packets(count=40):
    """Packets of two PDFs whose correct answer can be read off the invoice."""
    files, rows = {}, ["invoice,purchase_order,expected_decision"]
    for number in range(count):
        decision = "hold" if number % 2 else "pay"
        files[f"invoices/invoice_{number}.pdf"] = pdf([f"Invoice {number}", f"Total: ${number}.00 {decision}"])
        files[f"orders/order_{number}.pdf"] = pdf([f"Order {number}"])
        rows.append(f"invoices/invoice_{number}.pdf,orders/order_{number}.pdf,{decision}")
    return archive({"examples.csv": "\n".join(rows), **files})


def upload(data, name="packets.zip"):
    return {"file": (name, data, "application/zip")}


def test_an_archive_of_pdfs_becomes_cases_whose_requests_are_the_document_text(client, seeded, db):  # noqa: F811
    created = direct_agent(client, seeded, request="Check each purchase order invoice before it is paid")
    # A request that mentions orders, with nothing connected, is its own task and not the orders template.
    assert created["template"] == "custom"
    response = client.post(
        f"/agents/{created['id']}/datasets/archive",
        files=upload(packets()),
        data={"name": "Invoices", "development": "10", "selection": "10", "validation": "10"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rows"] == 40 and body["profile"]["splits"] == {
        "development": 10,
        "selection": 10,
        "regression": 0,
        "validation": 10,
    }
    assert body["mapping"] == {
        "input": {"invoice": "invoice", "purchase_order": "purchase_order"},
        "expected": {"decision": "expected_decision"},
    }
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == body["id"])))
    assert len(cases) == 30
    for case in cases:
        # The stored request is text read from the PDFs; no file name or PDF byte reaches a case.
        assert case.input["invoice"].startswith("Invoice ") and case.input["purchase_order"].startswith("Order ")
        assert ".pdf" not in str(case.input) and "%PDF" not in str(case.input)
        assert case.assertions[0]["value"] in case.input["invoice"]
    spec = db.scalar(select(AgentVersion).where(AgentVersion.id == body["version"]["id"])).spec
    assert spec["input_schema"]["required"] == ["invoice", "purchase_order"]
    assert spec["output_schema"]["properties"]["decision"]["enum"] == ["hold", "pay"]


def test_archive_and_pdf_uploads_are_tenant_scoped_need_write_access_and_report_bad_files(client, seeded, db):  # noqa: F811
    org, *_ = seeded
    created = direct_agent(client, seeded)
    url = f"/agents/{created['id']}/datasets/archive"
    viewer = member(db, org, "viewer")
    assert client.post(url, headers=viewer, files=upload(packets()), data={"name": "I"}).status_code == 403
    assert client.post("/documents/text", headers=viewer, files=upload(pdf(["A"]), "a.pdf")).status_code == 403
    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    assert client.post(url, headers=outsider, files=upload(packets()), data={"name": "I"}).status_code == 404
    refused = client.post(url, files=upload(b"not a zip"), data={"name": "I"})
    assert refused.status_code == 422 and "zip" in refused.json()["error"]["message"]
    scan = archive({"examples.csv": "invoice,expected_decision\na.pdf,pay\n", "a.pdf": pdf([])})
    refused = client.post(url, files=upload(scan), data={"name": "I"})
    assert refused.status_code == 422 and "scan" in refused.json()["error"]["message"]
    assert db.scalar(select(Dataset)) is None


def test_a_pdf_is_returned_as_text_for_a_context_document_and_nothing_is_stored(client, seeded, db):  # noqa: F811
    created = direct_agent(client, seeded)
    response = client.post("/documents/text", files=upload(pdf(["Hold any invoice above the order price."]), "p.pdf"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "name": "p.pdf",
        "text": "Hold any invoice above the order price.",
        "characters": 39,
        "reading": {"pages_read": 0, "pages_already_read": 0, "cost": 0},
        "pages_kept": 0,
    }
    added = client.post(f"/agents/{created['id']}/context", json={"name": body["name"], "text": body["text"]})
    assert added.status_code == 201
    scan = client.post("/documents/text", files=upload(pdf([]), "scan.pdf"))
    assert scan.status_code == 422 and "scan.pdf page 1 has no text" in scan.json()["error"]["message"]


# Scanned pages, read by a model. The model is a stand-in that says what it was shown.


class FakeUsage:
    def __init__(self, input_tokens=1000, output_tokens=500):
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.total_tokens = input_tokens + output_tokens
        self.input_tokens_details = None


class FakeModel:
    def __init__(self, fail_after=None, error=None):
        self.calls, self.fail_after, self.error, self.prompts = 0, fail_after, error, []

    async def __call__(self, prompt, images):
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail_after is not None and self.calls > self.fail_after:
            raise self.error
        for image, mime in images:
            assert mime in ("image/png", "image/jpeg") and image[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0")
        if prompt.startswith("These are the scanned pages"):
            return "1. stamped 639,066", FakeUsage()
        # Trailing space and blank lines, as a model leaves them; the reader tidies them away.
        return f"READ {hashlib.sha256(images[0][0]).hexdigest()[:16]}   \n\n", FakeUsage()


@pytest.fixture
def reading(monkeypatch):
    monkeypatch.setattr(settings(), "document_reading", True)
    monkeypatch.setattr(settings(), "reader_model", "gpt-5.5")


def stamped_scan():
    """A page as a court files it: a full-page image with one stamped line of text over it."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    image = DecodedStreamObject()
    image.set_data(b"\x80" * (800 * 600))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(800),
            NameObject("/Height"): NumberObject(600),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Im1 Do Q BT /F1 9 Tf 1 0 0 1 50 780 Tm (Case 1-23 Doc 4 Page 1 of 1) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
            NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)}),
        }
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_stamp_over_a_page_image_is_still_a_scan_and_a_rendered_scan_is_a_png():
    kinds = pdf_pages(stamped_scan())
    assert kinds == [("scan", None)]
    with pytest.raises(IntakeError, match="page 1 has no text.*turned off"):
        pdf_text(stamped_scan(), "filed.pdf")
    (kind, image), (text_kind, text) = pdf_pages(pdf([], ["Typed page"]), render=True)
    assert kind == "scan" and image[:8] == b"\x89PNG\r\n\x1a\n" and (text_kind, text) == ("text", "Typed page")


async def test_scanned_pages_are_read_once_charged_through_the_ledger_and_kept(db, seeded, reading):
    org, *_ = seeded
    model = FakeModel()
    reader = Reader(db, org.id, call=model)
    text = await reader.text(pdf(["Typed first page"], [], []), "mixed.pdf")
    # The typed page is taken as it is; only the two scanned pages went to the model. They are the same
    # blank image, so one request served both.
    assert text.startswith("Typed first page\n\nREAD ") and text.count("READ") == 2 and not text.endswith(" ")
    assert model.calls == 1 and reader.summary() == {"pages_read": 1, "pages_already_read": 0, "cost": 0.02}
    record = db.scalar(select(UsageRecord).where(UsageRecord.role == "document_reader"))
    assert (record.status, record.cost, record.reserved_cost) == ("recorded", 0.02, 0)
    assert (record.input_tokens, record.output_tokens, record.job_id, record.run_id) == (1000, 500, None, None)
    # A second upload of the same page costs nothing, for this tenant only.
    again = Reader(db, org.id, call=model)
    assert await again.text(pdf([]), "again.pdf") == text.split("\n\n", 1)[1].split("\n\n")[0]
    assert model.calls == 1 and again.summary() == {"pages_read": 0, "pages_already_read": 1, "cost": 0}
    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    await Reader(db, other.id, call=model).text(pdf([]), "theirs.pdf")
    assert model.calls == 2 and db.scalar(select(func.count()).select_from(DocumentReading)) == 2


async def test_reading_is_off_by_default_and_then_no_page_leaves(db, seeded):
    org, *_ = seeded
    model = FakeModel()
    with pytest.raises(IntakeError, match="scan.pdf page 1 has no text.*turned off"):
        await Reader(db, org.id, call=model).text(pdf([]), "scan.pdf")
    with pytest.raises(IntakeError, match="photo.jpg is a scan or a photo.*turned off"):
        await Reader(db, org.id, call=model).text(b"\xff\xd8\xff\xe0 a photo", "photo.jpg")
    assert model.calls == 0 and db.scalar(select(UsageRecord).where(UsageRecord.role == "document_reader")) is None


async def test_a_photo_is_read_and_the_reading_limit_stops_before_the_call(db, seeded, reading):
    org, *_ = seeded
    model = FakeModel()
    assert (await Reader(db, org.id, call=model).text(b"\xff\xd8\xff\xe0 a photo", "photo.jpg")).startswith("READ")
    # One page is set aside at the price of the largest request and reply allowed: 27 cents on this model.
    tight = Reader(db, org.id, max_cost=0.2, call=model)
    with pytest.raises(IntakeError, match=r"stopped at its \$0.2 limit after 0 pages.*kept"):
        await tight.text(b"\x89PNG\r\n\x1a\n another", "two.png")
    assert model.calls == 1


async def test_a_call_with_no_reply_keeps_its_reservation_and_is_not_retried(db, seeded, reading):
    import openai

    org, *_ = seeded
    model = FakeModel(fail_after=0, error=openai.APIConnectionError(request=None))
    with pytest.raises(IntakeError, match="did not answer while reading down.pdf page 1.*again"):
        await Reader(db, org.id, call=model).text(pdf([]), "down.pdf")
    record = db.scalar(select(UsageRecord).where(UsageRecord.role == "document_reader"))
    assert model.calls == 1 and record.status == "uncertain" and record.reserved_cost > 0 and record.cost == 0
    assert db.scalar(select(DocumentReading)) is None


def test_an_archive_with_scans_becomes_cases_and_reports_what_reading_cost(client, seeded, db, reading, monkeypatch):  # noqa: F811
    model = FakeModel()
    monkeypatch.setattr(Reader, "_provider", lambda self, prompt, images: model(prompt, images))
    monkeypatch.setattr(settings(), "openai_api_key", "test-key")
    created = direct_agent(client, seeded)
    files, rows = {}, ["invoice,expected_decision"]
    for number in range(40):
        decision = "hold" if number % 2 else "pay"
        # Half typed, half scanned. Each scan is a blank page of its own size, so each is its own image.
        files[f"i{number}.pdf"] = pdf([f"Invoice {number} {decision}"]) if number % 2 else blank(600 + number)
        rows.append(f"i{number}.pdf,{decision}")
    response = client.post(
        f"/agents/{created['id']}/datasets/archive",
        files=upload(archive({"examples.csv": "\n".join(rows), **files})),
        data={"name": "Scans", "development": "10", "selection": "0", "validation": "10"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["reading"] == {"pages_read": 20, "pages_already_read": 0, "cost": 0.4}
    assert model.calls == 20
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == response.json()["id"])))
    assert sum(case.input["text"].startswith("READ ") for case in cases) > 0
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "documents_read"))
    assert event.detail == {"pages_read": 20, "pages_already_read": 0, "cost": 0.4}
    # A reading limit below the first page refuses the upload and reads nothing more.
    refused = client.post(
        f"/agents/{created['id']}/datasets/archive",
        files=upload(archive({"examples.csv": "invoice,expected_decision\nnew.pdf,pay\n", "new.pdf": blank(900)})),
        data={"name": "More", "reading_max_cost": "0.01"},
    )
    assert refused.status_code == 422 and "limit" in refused.json()["error"]["message"] and model.calls == 20


def blank(width):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def test_a_rate_limit_is_waited_out_as_a_new_call_with_its_own_reservation(db, seeded, reading, monkeypatch):
    import httpx
    import openai

    org, *_ = seeded
    monkeypatch.setattr("factory.reading.RATE_LIMIT_WAITS", (0, 0))
    busy = openai.RateLimitError(
        "busy", response=httpx.Response(429, request=httpx.Request("POST", "https://x")), body=None
    )

    class Busy(FakeModel):
        async def __call__(self, prompt, images):
            self.calls += 1
            if self.calls <= 2:
                raise busy
            return "READ at last", FakeUsage()

    model = Busy()
    reader = Reader(db, org.id, call=model)
    assert await reader.text(pdf([]), "busy.pdf") == "READ at last"
    records = list(db.scalars(select(UsageRecord).where(UsageRecord.role == "document_reader")))
    assert model.calls == 3 and sorted(record.status for record in records) == ["recorded", "uncertain", "uncertain"]
    # Turned away more times than it waits for: the upload stops and says how to go on.
    with pytest.raises(IntakeError, match="did not answer"):
        await Reader(db, org.id, call=FakeModel(fail_after=0, error=busy)).text(blank(700), "still-busy.pdf")
    # An account with no credit answers 429 as well. Waiting cannot help, so it is said at once.
    broke = openai.RateLimitError(
        "none",
        response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
        body={"code": "insufficient_quota"},
    )
    spent = FakeModel(fail_after=0, error=broke)
    with pytest.raises(IntakeError, match="no credit left"):
        await Reader(db, org.id, call=spent).text(blank(710), "broke.pdf")
    assert spent.calls == 1


def test_pages_are_drawn_one_document_at_a_time_from_many_threads():
    # PDFium crashes the whole process when two threads draw at once; this would not fail, it would die.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda width: pdf_pages(blank(500 + width), render=True), range(40)))
    assert all(kind == "scan" and image[:4] == b"\x89PNG" for ((kind, image),) in results)


# Reading as part of the agent's design: a builder may change how pages are read.


def scanned_cases(client, seeded, db, monkeypatch, model):  # noqa: F811
    """An agent whose examples are scans, uploaded through the API. Returns (agent record, its cases)."""
    monkeypatch.setattr(Reader, "_provider", lambda self, prompt, images: model(prompt, images))
    monkeypatch.setattr(settings(), "openai_api_key", "test-key")
    created = direct_agent(client, seeded)
    files, rows = {"typed.pdf": pdf(["A typed invoice pay"])}, ["invoice,expected_decision", "typed.pdf,pay"]
    for number in range(39):
        files[f"i{number}.pdf"] = blank(600 + number)
        rows.append(f"i{number}.pdf,{'hold' if number % 2 else 'pay'}")
    response = client.post(
        f"/agents/{created['id']}/datasets/archive",
        files=upload(archive({"examples.csv": "\n".join(rows), **files})),
        data={"name": "Scans", "development": "20", "selection": "0", "validation": "20"},
    )
    assert response.status_code == 201, response.text
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == response.json()["id"])))
    return db.get(AgentRecord, created["id"]), cases


class Version:
    def __init__(self, org_id, reading=None):
        self.org_id, self.spec = org_id, {"reading": reading} if reading else {}


async def test_page_images_are_kept_with_the_case_and_read_again_only_when_a_version_asks(
    client,  # noqa: F811
    seeded,
    db,
    reading,
    monkeypatch,
):
    org, *_ = seeded
    model = FakeModel()
    _, cases = scanned_cases(client, seeded, db, monkeypatch, model)
    scans = [case for case in cases if case.documents]
    typed = next(case for case in cases if not case.documents)
    # A typed document keeps nothing: it never needs reading again. A scan keeps its page by hash.
    assert typed.input["text"] == "A typed invoice pay" and len(scans) == 39
    case = scans[0]
    (part,) = case.documents["text"]
    page = db.scalar(select(DocumentPage).where(DocumentPage.content_hash == part["page"]))
    assert page.org_id == org.id and page.mime == "image/png" and bytes(page.data)[:4] == b"\x89PNG"
    before = model.calls

    # No reading settings: the agent is given the text read at upload, and nothing is asked of the model.
    assert await case_input(db, Version(org.id), case) is case.input and model.calls == before

    noted = Version(org.id, {"notes": "The invoice number is stamped top right.", "questions": []})
    given = await case_input(db, noted, case)
    assert model.calls == before + 1 and "stamped top right" in model.prompts[-1] and given["text"].startswith("READ")
    # The same page under the same notes is not paid for twice.
    assert await case_input(db, noted, case) == given and model.calls == before + 1

    asked = Version(org.id, {"notes": "", "questions": ["What number is stamped top right?"]})
    given = await case_input(db, asked, case)
    assert "1. What number is stamped top right?" in model.prompts[-1]
    assert given["text"].endswith(
        "[Answers read directly from the page images]\nQuestions:\n1. What number is stamped top right?\n"
        "Answers:\n1. stamped 639,066"
    )
    # Reading that is switched off cannot quietly fall back to the old text for a version that asked for more.
    monkeypatch.setattr(settings(), "document_reading", False)
    with pytest.raises(IntakeError, match="turned off"):
        await case_input(db, Version(org.id, {"notes": "Different.", "questions": []}), case)


async def test_reading_in_a_build_is_charged_to_the_build_and_stops_at_its_budget(
    client,  # noqa: F811
    seeded,
    db,
    reading,
    monkeypatch,
):
    import openai

    from factory.evaluation import ProviderUnavailable
    from factory.runtime import BudgetExceeded

    org, *_ = seeded
    model = FakeModel()
    agent, cases = scanned_cases(client, seeded, db, monkeypatch, model)
    scans = [case for case in cases if case.documents]
    job = new_job(db, agent, Budget(max_cost=1))
    db.commit()
    version = Version(org.id, {"notes": "Read the stamp.", "questions": []})
    await case_input(db, version, scans[0], job)
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert (record.role, record.status, record.cost) == ("document_reader", "recorded", 0.02)
    assert job.spent == pytest.approx(0.02)
    # A provider failure says nothing about the agent: the trial is to be run again, and the call stays on the books.
    model.fail_after, model.error = model.calls, openai.APIConnectionError(request=None)
    with pytest.raises(ProviderUnavailable):
        await case_input(db, version, scans[1], job)
    assert job.spent == pytest.approx(0.02 + 0.27)
    model.fail_after = None
    job.budget = {**job.budget, "max_cost": 0.3}
    db.commit()
    with pytest.raises(BudgetExceeded):
        await case_input(db, version, scans[2], job)


async def test_a_builder_can_change_reading_and_question_only_pages_it_is_allowed_to_see(
    client,  # noqa: F811
    seeded,
    db,
    reading,
    monkeypatch,
):
    model = FakeModel()
    agent, cases = scanned_cases(client, seeded, db, monkeypatch, model)
    latest = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
    )
    spec = AgentSpec.model_validate(latest.spec)
    patched = apply_patch(spec, SpecPatch(reading={"notes": "Dates are stamped.", "questions": ["Which date?"]}))
    assert patched.reading.notes == "Dates are stamped." and mutable_view(patched) != mutable_view(spec)
    with pytest.raises(ValueError):
        SpecPatch(reading={"notes": "", "questions": ["q"] * 5})

    # What the builder is told: present only for an agent with scanned requests, and a description, not advice.
    assert "reading" not in optimizer_prompt(spec, investigating=True)
    told = optimizer_prompt(spec, investigating=True, scanned=["text"])
    assert "`reading.notes`" in told and "`ask_page`" in told and "charged to this build" in told
    for steer in ("prefer ", "usually", "tends to", "you should", "recommend", "leave empty", "set it to"):
        assert steer not in told.lower()

    job = new_job(db, agent, Budget(max_cost=5))
    evaluation = EvaluationRun(org_id=agent.org_id, version_id=latest.id, suite_id=cases[0].suite_id)
    db.add(evaluation)
    db.flush()
    scans = [case for case in cases if case.documents]
    seen = next(case for case in scans if case.split == "development")
    held = next(case for case in scans if case.split == "validation")
    for case in (seen, held):
        run = ExecutionRun(org_id=agent.org_id, version_id=latest.id, mode="live", input=case.input, output={})
        db.add(run)
        db.flush()
        db.add(
            EvaluationResult(
                org_id=agent.org_id,
                evaluation_run_id=evaluation.id,
                case_id=case.id,
                execution_id=run.id,
                trial=0,
                passed=False,
                checks=[],
                failures=[],
            )
        )
    db.commit()
    investigation = Investigation(db, job, spec, evaluation.id, [])
    assert investigation.scanned_fields() == ["text"]
    tools = {tool.name: tool for tool in investigation.tools()}
    arguments = {"case_id": seen.id, "field": "text", "question": "What number is stamped top right?"}
    answer = json.loads(await tools["ask_page"].on_invoke_tool(None, json.dumps(arguments)))
    assert answer["read_from_page"] == "1. stamped 639,066" and job.spent == pytest.approx(0.02)
    # A held-back case's page is as closed to the builder as its answer.
    refused = json.loads(await tools["ask_page"].on_invoke_tool(None, json.dumps({**arguments, "case_id": held.id})))
    assert "error" in refused and "read_from_page" not in refused and job.spent == pytest.approx(0.02)


def test_a_document_is_read_for_production_the_way_its_deployment_was_built(client, seeded, db, reading, monkeypatch):  # noqa: F811
    org, _, agent, version, *_ = seeded
    model = FakeModel()
    monkeypatch.setattr(Reader, "_provider", lambda self, prompt, images: model(prompt, images))
    monkeypatch.setattr(settings(), "openai_api_key", "test-key")
    version.spec = {**version.spec, "reading": {"notes": "The total is bottom right.", "questions": []}}
    deployment = Deployment(org_id=org.id, agent_id=agent.id, version_id=version.id, policy={})
    db.add(deployment)
    db.commit()
    plain = client.post("/documents/text", files=upload(blank(640), "scan.pdf"))
    assert plain.status_code == 200 and "bottom right" not in model.prompts[-1]
    built = client.post("/documents/text", files=upload(blank(640), "scan.pdf"), data={"deployment_id": deployment.id})
    assert built.status_code == 200 and "The total is bottom right." in model.prompts[-1] and model.calls == 2
    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    foreign = client.post(
        "/documents/text", headers=outsider, files=upload(blank(641), "s.pdf"), data={"deployment_id": deployment.id}
    )
    assert foreign.status_code == 404


def test_a_run_shows_its_scanned_pages_and_expected_answers_to_its_own_tenant_only(
    client,  # noqa: F811
    seeded,
    db,
    reading,
    monkeypatch,
):
    org, _, agent, version, *_ = seeded
    model = FakeModel()
    record, cases = scanned_cases(client, seeded, db, monkeypatch, model)
    case = next(case for case in cases if case.documents)
    (part,) = case.documents["text"]
    latest = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == record.id).order_by(AgentVersion.number.desc())
    )
    evaluation = EvaluationRun(org_id=org.id, version_id=latest.id, suite_id=case.suite_id)
    run = ExecutionRun(org_id=org.id, version_id=latest.id, mode="live", input=case.input, output={"decision": "pay"})
    db.add_all([evaluation, run])
    db.flush()
    checks = [
        {"category": "structured_accuracy", "path": "decision", "expected": "hold", "actual": "pay", "passed": False}
    ]
    db.add(
        EvaluationResult(
            org_id=org.id,
            evaluation_run_id=evaluation.id,
            case_id=case.id,
            execution_id=run.id,
            trial=0,
            passed=False,
            checks=checks,
            failures=["structured_accuracy"],
        )
    )
    db.commit()
    # A test run: the pages of its case, and what was expected beside what was answered.
    shown = client.get(f"/runs/{run.id}/documents").json()
    assert shown["pages"] == {"text": [part["page"]]} and shown["name"] == case.name
    assert shown["checks"] == [
        {
            "path": "decision",
            "expected": "hold",
            "actual": "pay",
            "passed": False,
            "table": None,
            "row": None,
            "wrong": None,
        }
    ]
    image = client.get(f"/document-pages/{part['page']}")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png" and image.content[:4] == b"\x89PNG"

    # A production run: pages are kept only when the caller asked, and found again by the text the run holds.
    dropped = client.post("/documents/text", files=upload(blank(701), "a.pdf")).json()
    kept = client.post("/documents/text", files=upload(blank(702), "b.pdf"), data={"keep_pages": "true"}).json()
    assert (dropped["pages_kept"], kept["pages_kept"]) == (0, 1)
    for text, expected in ((dropped["text"], 0), (kept["text"], 1)):
        production = ExecutionRun(org_id=org.id, version_id=latest.id, mode="live", input={"text": text}, output={})
        db.add(production)
        db.commit()
        found = client.get(f"/runs/{production.id}/documents").json()
        assert len(found["pages"].get("text", [])) == expected and found["checks"] == []

    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    assert client.get(f"/runs/{run.id}/documents", headers=outsider).status_code == 404
    assert client.get(f"/document-pages/{part['page']}", headers=outsider).status_code == 404
