import pytest

from doccheck_backend.native_reader import read_native_document


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


def _write_pdf(path, streams, *, attrs=b"", form=None):
    page_part = b" ".join(f"{index} 0 R".encode() for index in range(4, 4 + len(streams)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + page_part + b"] /Count " + str(len(streams)).encode() + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    first_stream = 4 + len(streams)
    resources = b"/Font << /F1 3 0 R >>"
    if form is not None:
        resources += f" /XObject << /FormA {first_stream + len(streams)} 0 R >>".encode()
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
    if form is not None:
        objects.append(form)

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
def test_pdf_cropbox_omits_full_show_when_it_hides_sign(tmp_path, rotation):
    pdf = _write_pdf(
        tmp_path / "crop.pdf",
        [b"BT /F1 12 Tf 12 140 Td (-120 RUB) Tj 25 -20 Td (Visible) Tj ET"],
        attrs=f"/Rotate {rotation} /CropBox [19.2 0 290 190]".encode(),
    )
    result = read_native_document(pdf, "pdf")

    assert [item.raw_text for item in result.observations] == ["Visible"]
    assert [issue.code for issue in result.issues] == ["clipped_pdf_text"]
    assert result.issues[0].locator.bbox is None


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


@pytest.mark.parametrize("mode", [3, 4, 5, 6, 7])
def test_pdf_unsupported_text_paint_modes_suppress_page(tmp_path, mode):
    pdf = _write_pdf(
        tmp_path / "text.pdf",
        [f"BT /F1 12 Tf {mode} Tr 20 140 Td (Uncertain) Tj ET".encode()],
    )
    result = read_native_document(pdf, "pdf")
    assert result.observations == ()
    assert [issue.code for issue in result.issues] == ["unsupported_pdf_visibility"]


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
