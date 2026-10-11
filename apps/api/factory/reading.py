"""Scanned pages and photos, read by a model.

A scan has no text to extract, so the page image goes to the model provider and comes back as text.
That is a model call like any other: its spend is set aside in a usage record before the request
leaves and settled when the reply arrives, and a call with no reply keeps its reservation. A reading
is kept per tenant under a hash of what was asked, so the same page asked the same way is paid for
once. Off unless DOCUMENT_READING is enabled.

How pages are read is part of an agent's design (`spec.reading`), and a builder may change it: notes
added to the transcription instructions, and questions answered straight from the page images. The
page images of example documents are kept (DocumentPage) so a version with its own reading settings
can have them read again, in a build against the build's budget.

The transcription is untrusted data, and the image itself reaches the provider unfiltered: a
credential printed on a page cannot be removed from a picture.
"""

import asyncio
import base64
import hashlib
import time

import openai
from openai import AsyncOpenAI
from sqlalchemy import select

from factory.config import settings
from factory.documents import MAX_FIELD_CHARS, MAX_PDF_BYTES, SCANS_OFF, _render, pdf_pages
from factory.intake import IntakeError
from factory.models import BuildJob, DocumentPage, DocumentReading, UsageRecord
from factory.pricing import cached_tokens, provider_unavailable, reservation, usage_cost

OPENAI_API_URL = "https://api.openai.com/v1"
MAX_IMAGE_BYTES = 10_000_000
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
# What is set aside for one request before it is sent: each image and the instructions, and the reply.
PAGE_INPUT_TOKENS = 6_000
PAGE_OUTPUT_TOKENS = 8_000
# The most pages of one document shown together when a question is asked of it.
QUESTION_PAGES = 6
# Part of the cache key: change it when the instructions change, so old readings are not reused.
INSTRUCTIONS_VERSION = "2"
# How long to wait, in seconds, before asking again after the provider says it is over its rate limit.
RATE_LIMIT_WAITS = (10, 30, 60, 120)
INSTRUCTIONS = """Transcribe this scanned business document page to plain text, exactly as printed.
- Keep the reading order and keep each table row on one line, with columns separated by two or more \
spaces and every row's values under the same columns.
- Copy every number, code and name character for character. Do not correct, complete, total or \
reformat anything, even if it looks wrong.
- The page may be rotated; transcribe it the right way up.
- Write [illegible] for text you cannot read and [redacted] for blacked-out areas. Put handwriting and \
stamps in the place they appear as [handwritten: ...] or [stamp: ...].
- Reply with the transcription only."""
NOTES_HEADING = "\n\nAbout these documents, from the person who set this reading up:\n"
QUESTION_INSTRUCTIONS = """These are the scanned pages of one business document, in order. Answer each question \
below from what is printed on them. Copy numbers, codes and names character for character; do not correct or \
compute anything. If the answer cannot be read, say "not legible". Reply with one line per question: its number, \
a full stop, then the answer and nothing else."""
ANSWERS_HEADING = "[Answers read directly from the page images]"


def image_type(data):
    return next((kind for magic, kind in IMAGE_TYPES.items() if data.startswith(magic)), None)


def reader_model():
    return settings().reader_model or settings().openai_model


def reading_settings(reading):
    """(notes, questions) from a spec's reading field, a Reading model, or nothing."""
    if reading is None:
        return "", []
    data = reading if isinstance(reading, dict) else reading.model_dump()
    return (data.get("notes") or "").strip(), [item.strip() for item in data.get("questions") or [] if item.strip()]


class Reader:
    """The reading done for one upload, one trial or one question: its ceiling, ledger and cache.

    With a build job, spend is charged to the job under its row lock and bounded by the job's budget;
    a provider failure or an empty budget is then raised as the build's own exceptions, so the trial
    is run again later or the build stops. Without one, the reader has a ceiling of its own.
    """

    def __init__(self, db, org_id, max_cost=None, call=None, job=None):
        config = settings()
        self.db, self.org_id, self.job = db, org_id, job
        self.max_cost = config.reading_max_cost if max_cost is None else max_cost
        self.enabled = config.document_reading and (call is not None or bool(config.openai_api_key))
        self.model = reader_model()
        self.call = call or self._provider
        self.gate = asyncio.Semaphore(max(1, config.reading_concurrency))
        self.files = asyncio.Semaphore(4)
        self.pages_read = self.pages_kept = 0
        self.cost = self.reserved = 0.0
        self.running = {}
        self.client = None

    def summary(self):
        return {"pages_read": self.pages_read, "pages_already_read": self.pages_kept, "cost": round(self.cost, 6)}

    async def text(self, data, name="The document", limit=MAX_FIELD_CHARS, reading=None):
        """The text of a PDF or an image, scanned pages included."""
        return (await self.read(data, name, limit, reading))[0]

    async def read(self, data, name="The document", limit=MAX_FIELD_CHARS, reading=None, keep=False):
        """(text, parts) of a PDF or an image. With keep, scanned page images are stored and parts
        lists the pages in order as {"text": ...} or {"page": hash}; it is None for a document that
        has no scanned page, which never needs reading again. With keep="all" every page is stored
        as an image, a typed page as {"text": ..., "page": hash}."""
        kind = image_type(data)
        if kind:
            if len(data) > MAX_IMAGE_BYTES:
                raise IntakeError(f"{name} is larger than {MAX_IMAGE_BYTES // 1_000_000} MB")
            pages = [("scan", data, kind)]
        else:
            if len(data) > MAX_PDF_BYTES:
                raise IntakeError(f"{name} is larger than {MAX_PDF_BYTES // 1_000_000} MB")
            async with self.files:
                # Drawing pages is slow and holds their images: a few files at a time, off the event loop.
                drawn = await asyncio.to_thread(pdf_pages, data, name, limit, self.enabled)
            pages = [(page_kind, body, "image/png") for page_kind, body in drawn]
        scanned = [number for number, (page_kind, _, _) in enumerate(pages, 1) if page_kind == "scan"]
        if scanned and not self.enabled:
            where = f"{name} page {scanned[0]} has no text: it" if not kind else name
            raise IntakeError(f"{where} is a scan or a photo. {SCANS_OFF}")
        parts = None
        if keep == "all":
            # Every page as an image, typed pages too, so the whole document can be shown beside its answer.
            typed = [number for number, (page_kind, _, _) in enumerate(pages) if page_kind == "text"]
            drawn = await asyncio.to_thread(_render, data, typed, name) if typed else {}
            parts = [
                {"page": self._store(body, mime)}
                if page_kind == "scan"
                else {"text": body, "page": self._store(drawn[number], "image/png")}
                for number, (page_kind, body, mime) in enumerate(pages)
            ]
            self.db.commit()
        elif scanned and keep:
            parts = [
                {"page": self._store(body, mime)} if page_kind == "scan" else {"text": body}
                for page_kind, body, mime in pages
            ]
            self.db.commit()
        text = await self._compose([(page_kind, body, mime) for page_kind, body, mime in pages], reading, name, limit)
        return text, parts

    async def document(self, parts, reading=None, name="The document", limit=MAX_FIELD_CHARS):
        """The text of a stored example document, read with the given settings."""
        pages = []
        for part in parts:
            if "text" not in part:
                page = self.db.scalar(
                    select(DocumentPage).where(
                        DocumentPage.org_id == self.org_id, DocumentPage.content_hash == part["page"]
                    )
                )
                if page is None:
                    raise IntakeError(f"A page image of {name} is no longer stored")
                pages.append(("scan", bytes(page.data), page.mime))
            else:
                pages.append(("text", part["text"], ""))
        if not self.enabled:
            raise IntakeError(f"{name} is a scan or a photo. {SCANS_OFF}")
        return await self._compose(pages, reading, name, limit)

    async def ask(self, parts, question, name="The document"):
        """One question answered from a stored document's page images. For a builder's investigation."""
        images = []
        for part in parts:
            if "page" in part:
                page = self.db.scalar(
                    select(DocumentPage).where(
                        DocumentPage.org_id == self.org_id, DocumentPage.content_hash == part["page"]
                    )
                )
                if page is not None:
                    images.append((bytes(page.data), page.mime))
        if not images or not self.enabled:
            raise IntakeError(f"{name} has no page image to look at")
        prompt = QUESTION_INSTRUCTIONS + "\n\n1. " + question.strip()
        return await self._request(prompt, images[:QUESTION_PAGES], f"{name} (question)", count_page=False)

    async def _compose(self, pages, reading, name, limit):
        notes, questions = reading_settings(reading)
        prompt = INSTRUCTIONS + (NOTES_HEADING + notes if notes else "")
        texts = await asyncio.gather(
            *(
                self._request(prompt, [(body, mime)], f"{name} page {number}") if page_kind == "scan" else _done(body)
                for number, (page_kind, body, mime) in enumerate(pages, 1)
            )
        )
        text = "\n\n".join(texts)
        images = [(body, mime) for page_kind, body, mime in pages if page_kind == "scan"]
        if questions and images:
            asked = QUESTION_INSTRUCTIONS + "\n\n" + "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
            answers = await self._request(asked, images[:QUESTION_PAGES], f"{name} (questions)", count_page=False)
            listed = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
            text += f"\n\n{ANSWERS_HEADING}\nQuestions:\n{listed}\nAnswers:\n{answers}"
        if len(text) > limit:
            raise IntakeError(f"{name} holds more than {limit} characters of text")
        return text

    def _store(self, image, mime):
        digest = hashlib.sha256(image).hexdigest()
        known = self.db.scalar(
            select(DocumentPage.id).where(DocumentPage.org_id == self.org_id, DocumentPage.content_hash == digest)
        )
        if known is None:
            self.db.add(DocumentPage(org_id=self.org_id, content_hash=digest, mime=mime, data=image))
            self.db.flush()
        return digest

    async def _request(self, prompt, images, label, count_page=True):
        if not self.enabled:
            raise IntakeError(f"{label} is a scan or a photo. {SCANS_OFF}")
        digest = hashlib.sha256(
            b"\x1f".join(
                (
                    INSTRUCTIONS_VERSION.encode(),
                    self.model.encode(),
                    prompt.encode(),
                    *(part for image, mime in images for part in (mime.encode(), hashlib.sha256(image).digest())),
                )
            )
        ).hexdigest()
        if digest not in self.running:
            # The same request twice at once is made once.
            self.running[digest] = asyncio.ensure_future(self._read(digest, prompt, images, label, count_page))
        return await asyncio.shield(self.running[digest])

    def _lock(self):
        if self.job is not None:
            self.db.scalar(
                select(BuildJob)
                .where(BuildJob.id == self.job.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )

    def _reserve(self, images):
        reserve = reservation(self.model, PAGE_INPUT_TOKENS * len(images), PAGE_OUTPUT_TOKENS)
        if self.job is not None:
            from factory.runtime import BudgetExceeded

            self._lock()
            if self.job.spent + reserve > self.job.budget["max_cost"]:
                # Let the build row go before unwinding: other trials of this pass wait on it.
                self.db.commit()
                raise BudgetExceeded("Insufficient build budget to read a scanned page")
            self.job.spent += reserve
        elif self.cost + self.reserved + reserve > self.max_cost:
            raise IntakeError(
                f"Reading stopped at its ${self.max_cost:g} limit after {self.pages_read} pages. The pages "
                "read so far are kept: send the upload again to continue, with a higher limit if needed."
            )
        # Committed before the request leaves, so a call that never answers is still on the books.
        record = UsageRecord(
            org_id=self.org_id,
            job_id=self.job.id if self.job is not None else None,
            role="document_reader",
            status="pending",
            reserved_cost=reserve,
        )
        self.db.add(record)
        self.db.commit()
        self.reserved += reserve
        return record, reserve

    def _unanswered(self, record, error, label, final):
        # No reply: what was sent may still be charged. The reservation stays, marked uncertain.
        self._lock()
        record.status = "uncertain"
        self.db.commit()
        if not final:
            return
        unavailable = isinstance(error, TimeoutError) or provider_unavailable(error)
        if self.job is not None and unavailable:
            from factory.evaluation import ProviderUnavailable

            # Nothing was learned about the agent: the build retries the trial later.
            raise ProviderUnavailable(f"The model provider did not answer while reading {label}") from None
        if getattr(error, "code", None) == "insufficient_quota":
            raise IntakeError(
                "The model provider refused the request: its account has no credit left. "
                "The pages read so far are kept: add credit and send the upload again."
            ) from None
        if unavailable:
            raise IntakeError(
                f"The model provider did not answer while reading {label}. "
                "The pages read so far are kept: send the upload again to continue."
            ) from None
        raise IntakeError(f"{label} could not be read: {type(error).__name__}") from None

    async def _read(self, digest, prompt, images, label, count_page):
        kept = self.db.scalar(
            select(DocumentReading).where(DocumentReading.org_id == self.org_id, DocumentReading.content_hash == digest)
        )
        if kept is not None:
            self.pages_kept += count_page
            return kept.text
        async with self.gate:
            for wait in (*RATE_LIMIT_WAITS, None):
                record, reserve = self._reserve(images)
                try:
                    text, usage = await asyncio.wait_for(
                        self.call(prompt, images), timeout=settings().reading_timeout_seconds
                    )
                    break
                except Exception as error:
                    # An account with no credit also answers 429, but waiting will not help.
                    waitable = (
                        isinstance(error, openai.RateLimitError)
                        and getattr(error, "code", None) != "insufficient_quota"
                        and wait is not None
                    )
                    self._unanswered(record, error, label, final=not waitable)
                    # The provider turned the request away for now. Waiting and asking again is a new
                    # call with a reservation of its own.
                    await asyncio.sleep(wait)
            actual = usage_cost(usage, self.model)
            self._lock()
            if self.job is not None:
                self.job.spent = (self.job.spent - reserve) + actual
            record.cost, record.tokens, record.reserved_cost, record.status = actual, usage.total_tokens, 0, "recorded"
            record.input_tokens, record.output_tokens = usage.input_tokens, usage.output_tokens
            record.cached_tokens = cached_tokens(usage)
            self.reserved -= reserve
            self.cost += actual
            text = "\n".join(line.rstrip() for line in (text or "").replace("\x00", "").splitlines()).strip("\n")
            if not text:
                self.db.commit()
                raise IntakeError(f"Nothing could be read from {label}")
            self.db.add(DocumentReading(org_id=self.org_id, content_hash=digest, model=self.model, text=text))
            self.db.commit()
            self.pages_read += count_page
            return text

    async def _provider(self, prompt, images):
        config = settings()
        if self.client is None:
            # No hidden retries: a repeated request under one reservation could be charged twice.
            self.client = AsyncOpenAI(
                api_key=config.openai_api_key, base_url=config.openai_base_url or OPENAI_API_URL, max_retries=0
            )
        addresses = [f"data:{mime};base64," + base64.b64encode(image).decode() for image, mime in images]
        limit = config.output_token_limit or None
        if config.openai_api == "chat_completions":
            reply = await self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=limit,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            *({"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in addresses),
                        ],
                    }
                ],
            )
            usage = reply.usage
            usage.input_tokens, usage.output_tokens = usage.prompt_tokens, usage.completion_tokens
            return reply.choices[0].message.content, usage
        effort = config.reader_reasoning_effort
        reply = await self.client.responses.create(
            model=self.model,
            max_output_tokens=limit,
            # The gpt-4 family does not reason and rejects the setting.
            **({"reasoning": {"effort": effort}} if effort and not self.model.startswith("gpt-4") else {}),
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        *({"type": "input_image", "image_url": url, "detail": "high"} for url in addresses),
                    ],
                }
            ],
        )
        return reply.output_text, reply.usage

    async def close(self):
        if self.client is not None:
            await self.client.close()


async def _done(value):
    return value


async def read_archive(reader, data):
    """As documents.read_archive, with scanned pages read through the given reader.

    Returns (records, document count, seconds, pages): pages maps each document's text to its parts,
    for the documents that have scanned pages, so the cases made from these rows can be read again.
    """
    from factory.documents import fill_archive, unpack_archive

    started = time.monotonic()
    records, cells, files = await asyncio.to_thread(unpack_archive, data)
    paths = list(files)
    results = await asyncio.gather(
        *(reader.read(files[path], path, keep=True) for path in paths), return_exceptions=True
    )
    failed = next((result for result in results if isinstance(result, BaseException)), None)
    if failed is not None:
        # Every page that was read is already kept; report the first thing that went wrong.
        if isinstance(failed, IntakeError):
            raise failed
        raise IntakeError(f"The documents could not be read: {type(failed).__name__}")
    texts = {path: text for path, (text, _) in zip(paths, results, strict=True)}
    records, documents = fill_archive(records, cells, texts)
    pages = {text: parts for text, parts in results if parts}
    return records, documents, round(time.monotonic() - started, 1), pages


async def case_input(db, version, case, job=None):
    """What an agent version is given for a case: the case's input, with each scanned document read
    the way this version's reading settings say. Without such settings it is the input as stored."""
    notes, questions = reading_settings(version.spec.get("reading"))
    if not (notes or questions) or not case.documents:
        return case.input
    reader = Reader(db, version.org_id, job=job)
    try:
        data = dict(case.input)
        for field, parts in case.documents.items():
            data[field] = await reader.document(parts, version.spec["reading"], f"{case.name} {field}")
        return data
    finally:
        await reader.close()
