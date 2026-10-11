"""PDF documents as input: their text, read once at the boundary.

An agent is sent text. A PDF with a text layer is turned into that text here, with the page layout
kept so that table columns stay in line. A scanned page has no text layer: it is refused by name
here, never passed on as an empty document, and read by a model only through factory/reading.py.
Everything is bounded: the file, its pages, the text.
"""

import io
import re
import struct
import threading
import zipfile
import zlib

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from factory.intake import MAX_DATASET_BYTES, IntakeError, parse_records

MAX_PDF_BYTES = 5_000_000
MAX_PDF_PAGES = 30
MAX_ARCHIVE_BYTES = 25_000_000
MAX_ARCHIVE_FILES = 6_000
MAX_ARCHIVE_UNPACKED = 100_000_000
TABLE_FILES = (".csv", ".tsv", ".json", ".jsonl", ".ndjson")
# Under this much text, a page that also carries a page-sized image is a scan with a stamp on it.
SCAN_TEXT_CHARS = 400
SCAN_PIXELS = 2000
SCANS_OFF = "Reading scans is turned off in this workspace."
RENDERING = threading.Lock()
# The most text one document may hold as a request field. A five-page invoice read with its columns
# kept in line runs past twenty thousand characters.
MAX_FIELD_CHARS = 60_000


def pdf_pages(data, name="The PDF", limit=MAX_FIELD_CHARS, render=False):
    """Each page as ("text", str) or ("scan", image). Raises IntakeError saying what is wrong with the file.

    A page is a scan when it has no text, or when all it has is a line or two laid over a full-page
    image, as a court or a scanner stamps on. With render the scan is a PNG of the page; without, None.
    """
    if len(data) > MAX_PDF_BYTES:
        raise IntakeError(f"{name} is larger than {MAX_PDF_BYTES // 1_000_000} MB")
    if not data.lstrip()[:5] == b"%PDF-":
        raise IntakeError(f"{name} is not a PDF file")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IntakeError(f"{name} is password protected")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise IntakeError(f"{name} has more than {MAX_PDF_PAGES} pages")
        pages, size = [], 0
        for page in reader.pages:
            try:
                text = page.extract_text(extraction_mode="layout")
            except Exception:
                # The layout reader fails on some unusual fonts; the plain reader loses only the columns.
                text = page.extract_text()
            text = _tidy(text)
            if not text or (len(text) < SCAN_TEXT_CHARS and _page_image(page)):
                pages.append(("scan", None))
                continue
            size += len(text)
            if size > limit:
                raise IntakeError(f"{name} holds more than {limit} characters of text")
            pages.append(("text", text))
    except IntakeError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, OSError):
        raise IntakeError(f"{name} could not be read as a PDF") from None
    if not pages:
        raise IntakeError(f"{name} has no pages")
    if render and any(kind == "scan" for kind, _ in pages):
        images = _render(data, [number for number, (kind, _) in enumerate(pages) if kind == "scan"], name)
        pages = [
            ("scan", images[number]) if kind == "scan" else (kind, text) for number, (kind, text) in enumerate(pages)
        ]
    return pages


def pdf_text(data, name="The PDF", limit=MAX_FIELD_CHARS):
    """The text of a PDF that has a text layer, pages in order. A scanned page is refused by name."""
    pages = pdf_pages(data, name, limit)
    for number, (kind, _) in enumerate(pages, 1):
        if kind == "scan":
            raise IntakeError(f"{name} page {number} has no text: it is a scan or a photo. {SCANS_OFF}")
    return "\n\n".join(text for _, text in pages)


def _page_image(page):
    """Whether the page carries an image large enough to be the page itself. Nothing is decoded."""
    try:
        objects = (page.get("/Resources") or {}).get("/XObject") or {}
        for item in objects.values():
            item = item.get_object()
            if item.get("/Subtype") == "/Image" and int(item.get("/Width", 0)) * int(item.get("/Height", 0)) >= 400_000:
                return True
    except Exception:
        return False
    return False


def _render(data, numbers, name):
    """Grey PNG images of the given pages, the long side SCAN_PIXELS."""
    import pypdfium2

    images = {}
    try:
        # PDFium is not thread-safe: two documents drawn at once crash the process. One at a time.
        with RENDERING:
            document = pypdfium2.PdfDocument(data)
            try:
                for number in numbers:
                    page = document[number]
                    width, height = page.get_size()
                    bitmap = page.render(scale=SCAN_PIXELS / max(width, height, 1), grayscale=True)
                    images[number] = _png(bitmap.buffer, bitmap.width, bitmap.height, bitmap.stride)
            finally:
                document.close()
    except Exception:
        raise IntakeError(f"{name} could not be turned into page images") from None
    return images


def _png(buffer, width, height, stride):
    rows = b"".join(b"\x00" + bytes(buffer[row * stride : row * stride + width]) for row in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def _tidy(text):
    lines = [line.rstrip() for line in (text or "").replace("\x00", "").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def unpack_archive(data):
    """The rows of a zip's examples file, the cells that name a PDF, and those PDFs.

    Returns (records, cells, files): cells are (row index, column, path) and files maps path to bytes.
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise IntakeError(f"The archive is larger than {MAX_ARCHIVE_BYTES // 1_000_000} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise IntakeError("The file is not a zip archive") from None
    with archive:
        members = [
            item
            for item in archive.infolist()
            if not item.is_dir()
            and not item.filename.startswith("__MACOSX/")
            and not item.filename.rsplit("/", 1)[-1].startswith(".")
        ]
        if len(members) > MAX_ARCHIVE_FILES:
            raise IntakeError(f"The archive holds more than {MAX_ARCHIVE_FILES} files")
        # Declared sizes are checked first and every read is bounded again: a header can lie.
        if sum(item.file_size for item in members) > MAX_ARCHIVE_UNPACKED:
            raise IntakeError("The archive unpacks to more than 100 MB")
        tables = [item for item in members if item.filename.lower().endswith(TABLE_FILES)]
        if len(tables) != 1:
            raise IntakeError(
                "The archive must hold exactly one examples file (csv, tsv, json or jsonl) beside its PDFs; "
                f"it holds {len(tables)}"
            )
        pdfs = {item.filename: item for item in members if item.filename.lower().endswith(".pdf")}
        by_name = {}
        for path in pdfs:
            by_name.setdefault(path.rsplit("/", 1)[-1], []).append(path)

        def read(item, limit):
            try:
                with archive.open(item) as handle:
                    body = handle.read(limit + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, ValueError):
                raise IntakeError(f"{item.filename} could not be unpacked") from None
            if len(body) > limit:
                raise IntakeError(f"{item.filename} is too large")
            return body

        try:
            table = read(tables[0], MAX_DATASET_BYTES).decode("utf-8")
        except UnicodeDecodeError:
            raise IntakeError("The examples file is not UTF-8 text") from None
        extension = tables[0].filename.rsplit(".", 1)[-1].lower()
        records = parse_records(table, {"ndjson": "jsonl"}.get(extension, extension))
        cells, files = [], {}
        for index, row in enumerate(records):
            for column, value in row.items():
                if not isinstance(value, str) or not value.strip().lower().endswith(".pdf"):
                    continue
                named = value.strip().lstrip("./")
                paths = [named] if named in pdfs else by_name.get(named.rsplit("/", 1)[-1], [])
                if not paths:
                    raise IntakeError(f"Column {column!r} names {value.strip()!r}, which is not in the archive")
                if len(paths) > 1:
                    raise IntakeError(f"{value.strip()!r} matches several files in the archive; give its folder too")
                if paths[0] not in files:
                    files[paths[0]] = read(pdfs[paths[0]], MAX_PDF_BYTES)
                cells.append((index, column, paths[0]))
        if not cells:
            raise IntakeError("No cell in the examples file names a PDF in the archive")
    return records, cells, files


def fill_archive(records, cells, texts):
    """Put each document's text in the cells that named it."""
    if sum(len(text) for text in texts.values()) > MAX_ARCHIVE_UNPACKED:
        raise IntakeError("The documents hold too much text")
    for index, column, path in cells:
        records[index][column] = texts[path]
    return records, len(texts)


def read_archive(data):
    """Rows from a zip holding one table of examples and the PDFs its cells name.

    The table is an ordinary examples file. A cell that names a PDF in the archive, by its path or by
    its file name, is replaced by that document's text, so one row can hold a packet of documents.
    This form reads text layers only; factory/reading.py reads the scanned pages as well.
    """
    records, cells, files = unpack_archive(data)
    return fill_archive(records, cells, {path: pdf_text(body, path) for path, body in files.items()})
