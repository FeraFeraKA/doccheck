"""Read addressed PDF text in the supported visibility subset."""

from collections import defaultdict
from math import isfinite
from pathlib import Path
from typing import BinaryIO
from zlib import error as DecompressionError

import pdfplumber
from pdfminer.layout import LTChar, LTPage
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfexceptions import PDFException
from pdfminer.pdffont import PDFType3Font
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdftypes import stream_value
from pdfminer.psexceptions import PSException
from pdfminer.psparser import literal_name
from pdfminer.utils import mult_matrix
from pdfplumber.page import Page, PDFPageAggregatorWithMarkedContent
from pdfplumber.utils.exceptions import PdfminerException

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation


class _UnsupportedVisibility(Exception):
    """The interpreter cannot establish which glyphs this page displays."""


class _PDFTextInterpreter(PDFPageInterpreter):
    def do_W(self) -> None:
        raise _UnsupportedVisibility

    do_W_a = do_W

    def do_Tr(self, render) -> None:
        # Text advance boxes do not bound stroked contours, even without a crop.
        if render != 0:
            raise _UnsupportedVisibility
        super().do_Tr(render)

    def do__w(self, aw, ac, text) -> None:
        # ISO 32000-1, table 109: set spacing, then show on the next line.
        self.do_Tw(aw)
        self.do_Tc(ac)
        self.do__q(text)

    def do_TJ(self, seq) -> None:
        if isinstance(self.textstate.font, PDFType3Font):
            raise _UnsupportedVisibility
        if self.textstate.font is not None:
            a, b, c, d, x, y = mult_matrix(self.textstate.matrix, self.ctm)
            if (
                not all(
                    isfinite(value)
                    for value in (a, b, c, d, x, y, self.textstate.scaling, self.textstate.fontsize)
                )
                or self.textstate.scaling == 0
                or self.textstate.fontsize == 0
            ):
                raise _UnsupportedVisibility
            determinant = a * d - b * c
            if not isfinite(determinant) or determinant == 0:
                raise _UnsupportedVisibility
        super().do_TJ(seq)

    def do_gs(self, name) -> None:
        # PDFMiner does not model transparency, soft masks or other extended state.
        raise _UnsupportedVisibility

    def do_Do(self, name) -> None:
        stream = stream_value(self.xobjmap[literal_name(name)])
        if literal_name(stream.get("Subtype")) != "Image" or "OC" in stream:
            raise _UnsupportedVisibility
        super().do_Do(name)

    def do_BDC(self, tag, props) -> None:
        if literal_name(tag) == "OC":
            raise _UnsupportedVisibility
        super().do_BDC(tag, props)

    def do_BMC(self, tag) -> None:
        if literal_name(tag) == "OC":
            raise _UnsupportedVisibility
        super().do_BMC(tag)


class _PDFTextAggregator(PDFPageAggregatorWithMarkedContent):
    show_id = 0

    def render_string(self, *args, **kwargs) -> None:
        self.show_id += 1
        super().render_string(*args, **kwargs)

    def render_char(self, *args, **kwargs) -> float:
        advance = super().render_char(*args, **kwargs)
        self.cur_item._objs[-1].doccheck_show_id = self.show_id
        return advance


class _TextPage(Page):
    @property
    def layout(self) -> LTPage:
        if not hasattr(self, "_layout"):
            device = _PDFTextAggregator(self.pdf.rsrcmgr, pageno=self.page_number)
            _PDFTextInterpreter(self.pdf.rsrcmgr, device).process_page(self.page_obj)
            self._layout = device.get_result()
        return self._layout

    def process_object(self, obj) -> dict:
        fields = super().process_object(obj)
        if isinstance(obj, LTChar):
            fields["show_id"] = obj.doccheck_show_id
        return fields


def _visible_box(page: Page) -> tuple[float, float, float, float]:
    if page.rotation not in (0, 90, 180, 270):
        raise _UnsupportedVisibility
    left, top, right, bottom = page.mediabox
    x0, y0, x1, y1 = page.cropbox
    if page.rotation in (90, 180):
        y0, y1 = top + bottom - y1, top + bottom - y0
    if page.rotation in (180, 270):
        x0, x1 = left + right - x1, left + right - x0
    box = max(left, x0), max(top, y0), min(right, x1), min(bottom, y1)
    if not all(isfinite(value) for value in box) or box[0] >= box[2] or box[1] >= box[3]:
        raise _UnsupportedVisibility
    # PDFMiner uses advances and font metrics, not painted outlines. An inward
    # crop can cut an overhanging glyph even when its advance is inside the crop.
    if box != page.mediabox:
        raise _UnsupportedVisibility
    return box


def _read_page(page: _TextPage) -> NativeDocument:
    groups: dict[int, list[dict]] = defaultdict(list)
    left, top, right, bottom = _visible_box(page)
    for glyph in page.chars:
        if not all(isfinite(glyph[key]) for key in ("x0", "top", "x1", "bottom")):
            raise _UnsupportedVisibility
        groups[glyph["show_id"]].append(glyph)

    observations = []
    issues = []
    for show_id, glyphs in groups.items():
        text = "".join(glyph["text"] for glyph in glyphs)
        if not text.strip():
            continue
        box = (
            min(glyph["x0"] for glyph in glyphs),
            min(glyph["top"] for glyph in glyphs),
            max(glyph["x1"] for glyph in glyphs),
            max(glyph["bottom"] for glyph in glyphs),
        )
        x0, y0, x1, y1 = box
        locator = PageLocator(
            kind="page", page=page.page_number, fragment_id=f"text-show-{show_id}"
        )
        if not (left <= x0 < x1 <= right and top <= y0 < y1 <= bottom):
            issues.append(NativeIssue("clipped_pdf_text", locator=locator))
            continue
        bbox = (
            (x0 - left) / (right - left),
            (y0 - top) / (bottom - top),
            (x1 - left) / (right - left),
            (y1 - top) / (bottom - top),
        )
        locator = PageLocator(
            kind="page", page=page.page_number, fragment_id=locator.fragment_id, bbox=bbox
        )
        observations.append(Observation(text, locator))

    if not observations and not issues:
        issues.append(NativeIssue("no_native_text", page=page.page_number))
    return NativeDocument(tuple(observations), tuple(issues))


_PDF_ERRORS = (
    OSError,
    DecompressionError,
    PDFException,
    PSException,
    PdfminerException,
    TypeError,
    ValueError,
    KeyError,
    OverflowError,
    NotImplementedError,
)


def read_pdf(path: Path | BinaryIO, *, page_number: int | None = None) -> NativeDocument:
    observations = []
    issues = []
    try:
        with pdfplumber.open(
            path, pages=None if page_number is None else [page_number]
        ) as document:
            if not document.doc.is_extractable:
                return NativeDocument(issues=(NativeIssue("native_read_error"),))
            for original in document.pages:
                page = _TextPage(
                    document, original.page_obj, original.page_number, original.initial_doctop
                )
                try:
                    result = _read_page(page)
                except _UnsupportedVisibility:
                    issues.append(NativeIssue("unsupported_pdf_visibility", page=page.page_number))
                except _PDF_ERRORS:
                    issues.append(NativeIssue("native_read_error", page=page.page_number))
                else:
                    observations.extend(result.observations)
                    issues.extend(result.issues)
                finally:
                    page.close()
    except PdfminerException as error:
        # pdfplumber wraps its PDFDocument initialization error as its sole argument.
        code = (
            "encrypted_pdf"
            if len(error.args) == 1 and isinstance(error.args[0], PDFPasswordIncorrect)
            else "native_read_error"
        )
        issues.append(NativeIssue(code))
    except _PDF_ERRORS:
        issues.append(NativeIssue("native_read_error"))
    if not observations and not issues:
        issues.append(NativeIssue("no_native_text"))
    return NativeDocument(tuple(observations), tuple(issues))
