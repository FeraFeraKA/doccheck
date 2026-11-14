"""Local Tesseract OCR and rendered pages with original-page coordinates."""

import csv
import io
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from doccheck_backend.contracts.locators import PageLocator

type PixelBox = tuple[int, int, int, int]


class OcrError(ValueError):
    """The source could not be rendered or recognized by the local OCR engine."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: PixelBox
    confidence: float


def render_pages(path: Path, *, max_pages: int = 12, max_side: int = 3800) -> Iterator[Image.Image]:
    """Render the visible PDF page or original PNG without changing its aspect ratio."""
    if path.suffix == ".png":
        with Image.open(path) as source:
            if source.format != "PNG" or source.n_frames != 1:
                raise OcrError("Expected a single PNG")
            image = source.convert("RGB")
        image.thumbnail((max_side, max_side))
        yield image
        return
    if path.suffix != ".pdf":
        raise OcrError("Expected PDF or PNG")
    try:
        with pdfium.PdfDocument(path) as document:
            if not 0 < len(document) <= max_pages:
                raise OcrError("PDF exceeds the allowed page count")
            for index in range(len(document)):
                page = document[index]
                try:
                    size = page.get_size()
                    if min(size) <= 0:
                        raise OcrError("Invalid PDF geometry")
                    bitmap = page.render(scale=min(6, max_side / max(size)))
                    try:
                        yield bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
    except pdfium.PdfiumError as exc:
        raise OcrError("PDF could not be rendered") from exc


def page_locator(page: int, image: Image.Image, box: PixelBox) -> PageLocator:
    left, top, right, bottom = box
    return PageLocator(
        kind="page",
        page=page,
        bbox=(left / image.width, top / image.height, right / image.width, bottom / image.height),
    )


def _ocr(image: Image.Image, *args: str) -> str:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--dpi", "300", *args],
            input=stream.getvalue(),
            capture_output=True,
            check=True,
            timeout=35,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
        return result.stdout.decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise OcrError("Local Tesseract OCR stopped") from exc


def recognize_crop(
    image: Image.Image, box: PixelBox, *, mode: int = 7, numeric: bool = False
) -> str:
    crop = image.crop(box).convert("L")
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC)
    crop = ImageOps.expand(crop, border=10, fill=255)
    options = ["-l", "eng" if numeric else "rus+eng", "--psm", str(mode)]
    if numeric:
        options += ["-c", "tessedit_char_whitelist=0123456789.,- "]
    return _ocr(crop, *options).strip()


def recognize_lines(image: Image.Image, *, mode: int = 3) -> list[OcrLine]:
    groups = defaultdict(list)
    tsv = _ocr(image, "-l", "rus+eng", "--psm", str(mode), "tsv")
    for entry in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        raw = entry.get("text")
        if entry["level"] != "5" or not raw or not raw.strip():
            continue
        key = tuple(entry[field] for field in ("block_num", "par_num", "line_num"))
        x, y, w, h = (int(entry[field]) for field in ("left", "top", "width", "height"))
        if 0 <= x < x + w <= image.width and 0 <= y < y + h <= image.height:
            groups[key].append((raw.strip(), (x, y, x + w, y + h), float(entry["conf"])))
    lines = []
    for group in groups.values():
        boxes = [word[1] for word in group]
        box = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        text = re.sub(r"\s+", " ", " ".join(word[0] for word in group)).strip()
        lines.append(OcrLine(text, box, min(word[2] for word in group)))
    return lines
