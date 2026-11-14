from pathlib import Path
from uuid import uuid4

import pypdfium2
import pytest
from PIL import Image

from doccheck_backend import grounded_amounts
from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation
from doccheck_backend.native_reader import read_native_document
from doccheck_backend.page_ocr import OcrLine


def _stream(data, extra=b""):
    return (
        b"<< /Length "
        + str(len(data)).encode()
        + b" "
        + extra
        + b" >>\nstream\n"
        + data
        + b"\nendstream"
    )


def _write_pdf(path, streams, *, attrs=b"", form=None, font=b"Courier", cmap=None, image=None):
    page_part = b" ".join(f"{index} 0 R".encode() for index in range(4, 4 + len(streams)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + page_part + b"] /Count " + str(len(streams)).encode() + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /" + font + b" >>",
    ]
    first_stream = 4 + len(streams)
    if cmap is not None:
        cmap_index = first_stream + len(streams) + int(form is not None) + int(image is not None)
        objects[2] = objects[2][:-2] + f"/ToUnicode {cmap_index} 0 R >>".encode()
    resources = b"/Font << /F1 3 0 R >>"
    rendered = [
        (name, obj) for name, obj in (("FormA", form), ("ImageA", image)) if obj is not None
    ]
    if rendered:
        xobjects = b" ".join(
            f"/{name} {i} 0 R".encode()
            for i, (name, _) in enumerate(rendered, start=first_stream + len(streams))
        )
        resources += b" /XObject << " + xobjects + b" >>"
    for index in range(len(streams)):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            + attrs
            + b" /Resources << "
            + resources
            + b" >>"
            + f" /Contents {first_stream + index} 0 R >>".encode()
        )
    objects.extend(_stream(data) for data in streams)
    objects.extend(obj for _, obj in rendered)
    if cmap is not None:
        objects.append(_stream(cmap))

    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_preserves_written_glyphs_and_address_without_amount(tmp_path, rotation):
    pdf = _write_pdf(
        tmp_path / "native.pdf",
        [b"BT /F1 12 Tf 20 140 Td [(123 ) -516.666667 (456 RUB)] TJ ( evidence) Tj ET"],
        attrs=f"/Rotate {rotation}".encode(),
    )
    result = read_native_document(pdf, "pdf")

    assert result.issues == ()
    assert [item.raw_text for item in result.observations] == ["123 456 RUB", " evidence"]
    assert len({item.locator.fragment_id for item in result.observations}) == 2
    for item in result.observations:
        assert item.amount is None and item.amount_role is None
        assert item.cached_value is None and item.component_locators == ()
        assert item.locator.page == 1
        x0, y0, x1, y1 = item.locator.bbox
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_inward_crop_rejects_page_even_if_some_advances_fit(tmp_path, rotation):
    pdf = _write_pdf(
        tmp_path / "crop.pdf",
        [b"BT /F1 12 Tf 12 140 Td (-120 RUB) Tj 25 -20 Td (Visible) Tj ET"],
        attrs=f"/Rotate {rotation} /CropBox [19.2 0 290 190]".encode(),
    )
    result = read_native_document(pdf, "pdf")

    assert result.observations == ()
    assert [(issue.code, issue.page) for issue in result.issues] == [
        ("unsupported_pdf_visibility", 1),
    ]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(
    ("font", "show"),
    [
        (b"Helvetica-Oblique", b"BT /F1 24 Tf 20 140 Td (j) Tj ET"),
        (b"Helvetica", b"10 w BT /F1 12 Tf 2 Tr 20 140 Td (-120 RUB) Tj ET"),
    ],
)
def test_pdf_cropbox_rejects_paint_outside_glyph_advance(tmp_path, rotation, font, show):
    pdf = _write_pdf(
        tmp_path / "ink.pdf",
        [show],
        font=font,
        attrs=f"/Rotate {rotation} /CropBox [20 0 300 200]".encode(),
    )
    result = read_native_document(pdf, "pdf")
    assert result.observations == ()
    assert [issue.code for issue in result.issues] == ["unsupported_pdf_visibility"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", ["[0 0 300 200]", "[-5 -5 305 205]"])
def test_pdf_cropbox_that_keeps_full_media_does_not_suppress_text(tmp_path, rotation, crop):
    pdf = _write_pdf(
        tmp_path / "full.pdf",
        [b"BT /F1 24 Tf 40 140 Td (j) Tj ET"],
        font=b"Helvetica-Oblique",
        attrs=f"/Rotate {rotation} /CropBox {crop}".encode(),
    )
    result = read_native_document(pdf, "pdf")
    assert [item.raw_text for item in result.observations] == ["j"]
    assert result.issues == ()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("inside", [True, False])
def test_pdf_text_showing_operators_use_the_same_next_line(tmp_path, rotation, inside):
    if inside:
        setup = b"BT /F1 24 Tf 60 TL 40 140 Td (Start) Tj "
    else:
        setup = b"BT /F1 24 Tf 100 TL 40 60 Td "
    attrs = f"/Rotate {rotation}".encode()
    endings = (
        b'3 1 (Evidence text) " ET',
        b"3 Tw 1 Tc (Evidence text) ' ET",
        b"3 Tw 1 Tc T* (Evidence text) Tj ET",
        (b"3 Tw 1 Tc 0 -60 Td " if inside else b"3 Tw 1 Tc 0 -100 Td ") + b"(Evidence text) Tj ET",
    )
    expected = None
    rendered = None
    for index, ending in enumerate(endings):
        pdf = _write_pdf(tmp_path / f"case-{index}.pdf", [setup + ending], attrs=attrs)
        result = read_native_document(pdf, "pdf")
        with pypdfium2.PdfDocument(pdf) as document:
            page = document[0]
            bitmap = page.render()
            pixels = bitmap.to_pil().tobytes()
            bitmap.close()
            page.close()
        if expected is None:
            expected = result
            rendered = pixels
        assert result == expected
        assert pixels == rendered

    if inside:
        assert [observation.raw_text for observation in expected.observations] == [
            "Start",
            "Evidence text",
        ]
        assert expected.issues == ()
        assert expected.observations[0].locator.bbox != expected.observations[1].locator.bbox
    else:
        assert expected.observations == ()
        assert [issue.code for issue in expected.issues] == ["clipped_pdf_text"]
        assert all(value == 255 for value in rendered)


@pytest.mark.parametrize("operator", [b"W", b"W*"])
def test_pdf_clip_operator_suppresses_page_but_not_the_next(tmp_path, operator):
    pdf = _write_pdf(
        tmp_path / "path.pdf",
        [
            b"BT /F1 12 Tf 20 160 Td (Earlier) Tj ET q 0 0 1 1 re "
            + operator
            + b" n BT /F1 12 Tf 20 140 Td (Hidden) Tj ET Q",
            b"BT /F1 12 Tf 20 140 Td (Next page) Tj ET",
        ],
    )
    result = read_native_document(pdf, "pdf")
    assert [(item.raw_text, item.locator.page) for item in result.observations] == [
        ("Next page", 2)
    ]
    assert [(issue.code, issue.page) for issue in result.issues] == [
        ("unsupported_pdf_visibility", 1),
    ]


@pytest.mark.parametrize("mode", [1, 2, 3, 4, 5, 6, 7])
def test_pdf_unsupported_text_paint_modes_suppress_page(tmp_path, mode):
    pdf = _write_pdf(
        tmp_path / "text.pdf",
        [f"BT /F1 12 Tf {mode} Tr 20 140 Td (Uncertain) Tj ET".encode()],
    )
    result = read_native_document(pdf, "pdf")
    assert result.observations == ()
    assert [issue.code for issue in result.issues] == ["unsupported_pdf_visibility"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(
    ("text_setup", "supported"),
    [
        (b"100 Tz 1 1 -1 1 40 100 Tm", True),
        (b"0 Tz 1 1 -1 1 40 100 Tm", False),
        (b"100 Tz 1 1 2 2 40 100 Tm", False),
    ],
)
def test_pdf_rejects_degenerate_transformed_glyphs(tmp_path, rotation, text_setup, supported):
    pdf = _write_pdf(
        tmp_path / "transform.pdf",
        [b"BT /F1 24 Tf " + text_setup + b" (Zero) Tj ET"],
        attrs=f"/Rotate {rotation}".encode(),
    )
    result = read_native_document(pdf, "pdf")
    assert [item.raw_text for item in result.observations] == (["Zero"] if supported else [])
    assert [issue.code for issue in result.issues] == (
        [] if supported else ["unsupported_pdf_visibility"]
    )


@pytest.mark.parametrize("command", [b"/GS1 gs", b"/OC /LayerA BDC", b"/OC BMC"])
def test_pdf_unmodeled_graphics_state_or_layer_suppresses_page(tmp_path, command):
    pdf = _write_pdf(
        tmp_path / "visibility.pdf",
        [command + b" BT /F1 12 Tf 20 140 Td (Uncertain) Tj ET"],
    )
    result = read_native_document(pdf, "pdf")
    assert result.observations == ()
    assert [issue.code for issue in result.issues] == ["unsupported_pdf_visibility"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_form_is_unsupported_before_nested_content_is_used(tmp_path, rotation):
    form = _stream(
        b"BT /F1 12 Tf 12 140 Td (-120 RUB) Tj ET",
        b"/Type /XObject /Subtype /Form /BBox [19.2 0 150 200] "
        b"/Resources << /Font << /F1 3 0 R >> >>",
    )
    pdf = _write_pdf(
        tmp_path / "form.pdf", [b"/FormA Do"], form=form, attrs=f"/Rotate {rotation}".encode()
    )
    result = read_native_document(pdf, "pdf")
    assert result.observations == ()
    assert [issue.code for issue in result.issues] == ["unsupported_pdf_visibility"]


def test_pdf_without_native_text_and_invalid_pdf_have_distinct_diagnostics(tmp_path):
    empty = _write_pdf(tmp_path / "empty.pdf", [b""])
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"Not a PDF")
    assert [i.code for i in read_native_document(empty, "pdf").issues] == ["no_native_text"]
    assert [i.code for i in read_native_document(broken, "pdf").issues] == ["native_read_error"]


def test_pdf_with_visible_image_uses_visual_reading_even_with_native_text(monkeypatch, tmp_path):
    raster = _stream(
        b"\x80",
        b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
        b"/BitsPerComponent 8 /ColorSpace /DeviceGray",
    )
    pdf = _write_pdf(
        tmp_path / "hybrid.pdf",
        [
            b"BT /F1 12 Tf 20 140 Td (Intermediate total: 100.00) Tj ET "
            b"q 160 0 0 30 20 50 cm /ImageA Do Q"
        ],
        image=raster,
    )
    native = read_native_document(pdf, "pdf")
    assert [issue.code for issue in native.issues] == ["raster_pdf_content"]
    assert len(native.observations) == 1

    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _: [
            OcrLine("Сумма: 100,00 руб.", (20, 30, 220, 46), 98),
            OcrLine("Итого к оплате: 120,00 руб.", (20, 90, 260, 105), 98),
        ],
    )
    result = grounded_amounts.ground_document(uuid4(), "a" * 32, pdf, "pdf", "b" * 64)
    assert result.amount == "120.00"
    assert [(item.method, item.normalized_value) for item in result.assertions] == [
        ("ocr", "120.00")
    ]


def test_ambiguous_visual_purpose_cannot_revert_to_partial_text(monkeypatch, tmp_path):
    address = PageLocator(kind="page", page=1, bbox=(0.1, 0.1, 0.8, 0.2))
    native = NativeDocument(
        (Observation("Работы отнесены к общепроизводственным расходам.", address),),
        (NativeIssue("clipped_pdf_text", locator=address),),
    )
    monkeypatch.setattr(grounded_amounts, "read_native_document", lambda *_: native)
    monkeypatch.setattr(
        grounded_amounts, "render_pages", lambda *_: iter([Image.new("L", (500, 500))])
    )
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _: [
            OcrLine("Работы отнесены к общепроизводственным расходам.", (20, 30, 300, 46), 98),
            OcrLine("Оказаны общехозяйственные услуги.", (20, 90, 300, 105), 98),
            OcrLine("Итого: 120,00 руб.", (20, 150, 180, 164), 98),
        ],
    )
    result = grounded_amounts.ground_document(
        uuid4(), "a" * 32, tmp_path / "mixed.pdf", "pdf", "b" * 64
    )
    assert result.amount == "120.00"
    assert result.category is None
    assert not any(item.kind == "article" for item in result.assertions)


def test_pdf_that_requires_password_has_a_distinct_file_diagnostic():
    path = Path(__file__).with_name("fixtures") / "encrypted-empty.pdf"
    result = read_native_document(path, "pdf")
    assert result.observations == ()
    assert [(issue.code, issue.page, issue.locator) for issue in result.issues] == [
        ("encrypted_pdf", None, None),
    ]
