"""Text preview derived from an addressed fragment of a verified original."""

import re
from decimal import Decimal, InvalidOperation
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel

from doccheck_backend.contracts.locators import Locator, PageLocator
from doccheck_backend.contracts.result import Evidence
from doccheck_backend.native_pdf import read_pdf
from doccheck_backend.native_reader import read_native_document, rub_amount_span

MAX_INPUT_BYTES = 8 * 1024**2
_MAX_OFFICE_UNPACKED_BYTES = 32 * 1024**2
MAX_TEXT_BYTES = 4096
_BARE_NUMBER = re.compile(r"[+−-]?[0-9]+(?:[.,][0-9]+)?(?:[Ee][+-]?[0-9]+)?")


class Highlight(BaseModel):
    start_byte: int
    end_byte: int


class FragmentPreview(BaseModel):
    text: str | None
    highlight: Highlight | None


def render_preview(stream: BinaryIO, file_format: object, evidence: Evidence) -> FragmentPreview:
    empty = FragmentPreview(text=None, highlight=None)
    locator = evidence.locator
    if file_format == "pdf" and isinstance(locator, PageLocator):
        # A generated fragment ID or recorded rectangle can identify native PDF text.
        if locator.fragment_id is None and locator.bbox is None:
            return empty
        parsed = read_pdf(stream, page_number=locator.page)
    elif isinstance(file_format, str) and file_format in ("docx", "xlsx"):
        try:
            with ZipFile(stream) as archive:
                if sum(part.file_size for part in archive.infolist()) > _MAX_OFFICE_UNPACKED_BYTES:
                    return empty
        except (BadZipFile, UnicodeError, ValueError, NotImplementedError):
            return empty
        stream.seek(0)
        parsed = read_native_document(stream, file_format)
    else:
        return empty

    matches = [
        item.raw_text for item in parsed.observations if _same_locator(item.locator, locator)
    ]
    if len(matches) != 1 or not matches[0].strip():
        return empty
    text = matches[0]
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return empty
    if len(encoded) > MAX_TEXT_BYTES:
        return empty
    return FragmentPreview(text=text, highlight=_highlight(text, evidence))


def _same_locator(observed: Locator, saved: Locator) -> bool:
    if not isinstance(saved, PageLocator) or not isinstance(observed, PageLocator):
        return observed == saved
    if observed.page != saved.page:
        return False
    # When both identities were stored, require both. Do not infer a box from a line.
    return (saved.fragment_id is None or saved.fragment_id == observed.fragment_id) and (
        saved.bbox is None or saved.bbox == observed.bbox
    )


def _highlight(text: str, evidence: Evidence) -> Highlight | None:
    raw_value = evidence.raw_value
    if not raw_value.strip():
        return None
    start = text.find(raw_value)
    if start < 0 or text.find(raw_value, start + 1) >= 0:
        return None
    end = start + len(raw_value)
    if _joined_token(text, start, raw_value[0], -1) or _joined_token(
        text, end - 1, raw_value[-1], 1
    ):
        return None
    if evidence.kind in ("amount", "reported_value"):
        reading = _numeric_span(text, evidence.unit)
        if reading is None:
            return None
        value, (number_start, number_end) = reading
        if value != Decimal(evidence.normalized_value) or not (
            start <= number_start < number_end <= end
        ):
            return None
        start, end = number_start, number_end
    return Highlight(
        start_byte=len(text[:start].encode("utf-8")),
        end_byte=len(text[:end].encode("utf-8")),
    )


def _numeric_span(text: str, unit: str | None) -> tuple[Decimal, tuple[int, int]] | None:
    if unit == "RUB":
        reading = rub_amount_span(text)
        if reading is not None:
            return reading
    # Currency-less values are eligible only when they occupy the whole address.
    stripped = text.strip()
    if _BARE_NUMBER.fullmatch(stripped) is None:
        return None
    try:
        value = Decimal(stripped.replace("−", "-").replace(",", "."))
    except InvalidOperation:
        return None
    start = len(text) - len(text.lstrip())
    return value, (start, start + len(stripped))


def _joined_token(text: str, position: int, edge: str, direction: int) -> bool:
    neighbor = position + direction
    if not 0 <= neighbor < len(text) or not edge.isalnum():
        return False
    adjacent = text[neighbor]
    if adjacent.isalnum() or adjacent == "_":
        return True
    if not edge.isdigit():
        return False
    if direction == -1 and adjacent in "+-−":
        return True
    next_position = neighbor + direction
    return (
        adjacent in "., \u00a0\u2009\u202f"
        and 0 <= next_position < len(text)
        and text[next_position].isdigit()
    )
