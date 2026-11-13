from decimal import Decimal
from pathlib import Path
from struct import pack_into
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document

from doccheck_backend.contracts.locators import PageLocator, ParagraphLocator, TableCellLocator
from doccheck_backend.native_reader import _text_amount, read_native_document
from doccheck_backend.native_xlsx import _Cell, _sum_candidate

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def _workbook(path: Path, rows: str, *, external_link: bool = False) -> Path:
    external_ref = (
        '<externalReferences><externalReference r:id="rId2"/></externalReferences>'
        if external_link
        else ""
    )
    external_relation = (
        f'<Relationship Id="rId2" Type="{_REL}/externalLink" '
        'Target="externalLinks/externalLink1.xml"/>'
        if external_link
        else ""
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}">'
            '<sheets><sheet name="Синтетика" sheetId="1" r:id="rId1"/></sheets>'
            f"{external_ref}</workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{_PACKAGE}"><Relationship Id="rId1" '
            f'Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            f"{external_relation}</Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{_MAIN}"><sheetData>{rows}</sheetData></worksheet>',
        )
    return path


def _text(address: str, text: str) -> str:
    return f'<c r="{address}" t="inlineStr"><is><t>{text}</t></is></c>'


def _payroll(tmp_path: Path, first: str, second: str, formula: str = "SUM(C6:C7)", cache: str = ""):
    heading = _text("A5", "Код статьи") + _text("B5", "Вид начисления") + _text("C5", "Сумма, руб.")
    return _workbook(
        tmp_path / "upload",
        f'<row r="1">{_text("A1", "Расчётная ведомость по оплате труда")}</row>'
        f'<row r="5">{heading}</row>'
        f'<row r="6"><c r="C6"><v>{first}</v></c></row>'
        f'<row r="7"><c r="C7"><v>{second}</v></c></row>'
        f'<row r="8">{_text("B8", "ИТОГО")}<c r="C8"><f>{formula}</f>'
        f"<v>{cache}</v></c></row>",
    )


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("1523.09", "21.11", "1544.20"), ("9007199254740993.01", "-0.01", "9007199254740993.00")],
)
def test_uncached_payroll_sum_is_exact_and_retains_component_addresses(
    tmp_path, first, second, expected
):
    result = read_native_document(_payroll(tmp_path, first, second), "xlsx")
    assert result.issues == ()
    (total,) = tuple(item for item in result.observations if item.amount_role == "total")
    assert total.raw_text == "=SUM(C6:C7)"
    assert total.amount == Decimal(expected)
    assert total.locator.range == "C8"
    assert total.cached_value is None
    assert [item.range for item in total.component_locators] == ["C6", "C7"]
    assert [item.amount for item in result.observations if item.amount_role == "component"] == [
        Decimal(first),
        Decimal(second),
    ]


def test_cache_mismatch_is_diagnostic_and_recalculated_amount_is_kept(tmp_path):
    path = _payroll(tmp_path, "10.01", "2.01", formula=" sum($C$6:$C$7) ", cache="12.01")
    result = read_native_document(path, "xlsx")
    (total,) = tuple(item for item in result.observations if item.amount_role == "total")
    assert total.amount == Decimal("12.02")
    assert total.cached_value == Decimal("12.01")
    assert {item.code for item in result.issues} == {"formula_cache_mismatch"}


def test_invalid_cache_does_not_replace_recalculated_amount(tmp_path):
    result = read_native_document(_payroll(tmp_path, "10.01", "2.01", cache="invalid"), "xlsx")
    (total,) = tuple(item for item in result.observations if item.amount_role == "total")
    assert total.amount == Decimal("12.02")
    assert total.cached_value is None
    assert {item.code for item in result.issues} == {"invalid_formula_cache"}


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("C6+C7", "unsupported_formula"),
        ("SUM([other.xlsx]S!A1:A2)", "external_formula_reference"),
        ("SUM(Items[Amount])", "unsupported_formula"),
        ('WEBSERVICE("https://example.invalid/value")', "unsupported_formula"),
        ("SUM(C6:C6)", "unexpected_total_components"),
        ("SUM(C6:C8)", "unsupported_sum_input"),
    ],
)
def test_untrusted_and_incomplete_formulas_do_not_promote_cached_values(
    tmp_path, formula, expected
):
    result = read_native_document(_payroll(tmp_path, "3.13", "2.22", formula, cache="99"), "xlsx")
    assert {item.code for item in result.issues} == {expected, "missing_template_total"}
    formula_value = next(item for item in result.observations if item.locator.range == "C8")
    assert formula_value.raw_text == "=" + formula
    assert formula_value.amount is None
    assert formula_value.cached_value == Decimal("99")


def test_contributions_selects_assessed_amount_instead_of_base(tmp_path):
    heading = (
        _text("A5", "База начислений, руб.")
        + _text("B5", "Начислено взносов, руб.")
        + _text("C5", "Код статьи")
    )
    path = _workbook(
        tmp_path / "upload",
        f'<row r="1">{_text("A1", "Расчёт страховых взносов")}</row>'
        f'<row r="5">{heading}</row>'
        '<row r="6"><c r="A6"><f>SUM(A7:A8)</f></c><c r="B6"><v>2813.08</v></c>'
        '<c r="D6"><f>SUM(B6:B6)</f></c></row>'
        '<row r="7"><c r="A7"><v>875.50</v></c></row>'
        '<row r="8"><c r="A8"><v>11124.50</v></c></row>',
    )
    result = read_native_document(path, "xlsx")
    assert result.issues == ()
    assert {
        item.locator.range: (item.amount, item.amount_role)
        for item in result.observations
        if item.amount is not None
    } == {
        "A6": (Decimal("12000.00"), "basis"),
        "B6": (Decimal("2813.08"), "total"),
        "D6": (Decimal("2813.08"), "candidate"),
        "A7": (Decimal("875.50"), "candidate"),
        "A8": (Decimal("11124.50"), "candidate"),
    }


def test_detects_workbook_external_link_without_reading_its_target(tmp_path):
    path = _workbook(
        tmp_path / "upload",
        '<row r="1"><c r="A1"><v>42</v></c></row>',
        external_link=True,
    )
    result = read_native_document(path, "xlsx")
    assert [item.code for item in result.issues] == ["external_workbook_reference"]
    assert result.observations[0].amount == Decimal(42)
    assert result.observations[0].amount_role == "candidate"


def _minimal_pdf(path: Path, lines: list[str], *, page_attrs: bytes = b"", left: int = 30) -> Path:
    stream = "\n".join(
        f"BT /F1 12 Tf {left} {150 - count * 20} Td ({line}) Tj ET"
        for count, line in enumerate(lines)
    ).encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        + page_attrs
        + b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    )
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{start}\n%%EOF".encode()
    )
    path.write_bytes(output)
    return path


def test_pdf_native_text_has_normalized_address_and_leaves_nonamount_text(tmp_path):
    path = _minimal_pdf(tmp_path / "upload", ["Contract 31-001", "Paid: 1 200,17 RUB"])
    result = read_native_document(path, "pdf")
    assert result.issues == ()
    identification, amount = result.observations
    assert identification.amount is None
    assert amount.raw_text == "Paid: 1 200,17 RUB"
    assert amount.amount == Decimal("1200.17")
    assert isinstance(amount.locator, PageLocator)
    assert amount.locator.page == 1 and amount.locator.line == 2
    left, top, right, bottom = amount.locator.bbox
    assert 0 <= left < right <= 1 and 0 <= top < bottom <= 1


def test_pdf_without_text_is_not_an_empty_success(tmp_path):
    path = _minimal_pdf(tmp_path / "upload", [])
    result = read_native_document(path, "pdf")
    assert result.observations == ()
    assert [(issue.code, issue.page) for issue in result.issues] == [("no_native_text", 1)]


@pytest.mark.parametrize(
    ("rotation", "expected_box"),
    [
        (0, (0.093, 0.157, 0.561, 0.500)),
        (90, (0.500, 0.093, 0.843, 0.561)),
        (180, (0.439, 0.500, 0.907, 0.843)),
        (270, (0.157, 0.439, 0.500, 0.907)),
    ],
)
def test_pdf_cropbox_excludes_hidden_text_and_normalizes_rotated_box(
    tmp_path, rotation, expected_box
):
    path = _minimal_pdf(
        tmp_path / "upload",
        ["Hidden: 20,10 RUB", "Visible: 30,15 RUB"],
        page_attrs=f"/CropBox [10 110 225 145] /Rotate {rotation}".encode(),
    )
    result = read_native_document(path, "pdf")
    assert result.issues == ()
    (amount,) = result.observations
    assert amount.raw_text == "Visible: 30,15 RUB"
    assert amount.amount == Decimal("30.15")
    assert amount.locator.page == 1 and amount.locator.line == 1
    assert amount.locator.bbox == pytest.approx(expected_box, abs=0.002)


def test_pdf_cropbox_partial_glyph_does_not_become_a_different_amount(tmp_path):
    path = _minimal_pdf(
        tmp_path / "upload", ["-120,35 RUB"], page_attrs=b"/CropBox [32 125 225 170]"
    )
    result = read_native_document(path, "pdf")
    (observation,) = result.observations
    assert observation.amount is None
    assert [item.code for item in result.issues] == ["clipped_pdf_text"]


@pytest.mark.parametrize("attrs", [b"", b"/CropBox [0 0 300 200]"])
def test_default_pdf_boundary_also_checks_hidden_sign(tmp_path, attrs):
    path = _minimal_pdf(tmp_path / "upload", ["-120,35 RUB"], page_attrs=attrs, left=-4)
    result = read_native_document(path, "pdf")
    (observation,) = result.observations
    assert observation.amount is None
    assert observation.raw_text.startswith("�")
    assert [item.code for item in result.issues] == ["clipped_pdf_text"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_cropbox_hides_whole_minus_without_observing_positive_value(tmp_path, rotation):
    path = _minimal_pdf(
        tmp_path / "upload",
        ["-120,35 RUB"],
        page_attrs=f"/CropBox [34 125 225 170] /Rotate {rotation}".encode(),
    )
    result = read_native_document(path, "pdf")
    (observation,) = result.observations
    assert observation.raw_text.startswith("�")
    assert "-" not in observation.raw_text
    assert observation.amount is None
    assert [item.code for item in result.issues] == ["clipped_pdf_text"]


def test_docx_paragraph_table_and_nonamount_numbers_keep_real_addresses(tmp_path):
    path = tmp_path / "upload"
    doc = Document()
    doc.add_paragraph("Договор 41-777")
    doc.add_paragraph("В том числе: 34,07 руб.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Основание"
    table.cell(0, 1).text = "Сумма, руб."
    table.cell(1, 0).text = "912901"
    table.cell(1, 1).text = "9 012,34"
    doc.save(path)
    result = read_native_document(path, "docx")
    assert result.issues == ()
    paragraph, table_cell = [item for item in result.observations if item.amount is not None]
    assert paragraph.amount == Decimal("34.07") and paragraph.raw_text == "В том числе: 34,07 руб."
    assert paragraph.locator == ParagraphLocator(kind="paragraph", paragraph=2)
    assert table_cell.amount == Decimal("9012.34") and table_cell.raw_text == "9 012,34"
    assert table_cell.locator == TableCellLocator(kind="table_cell", table=1, row=2, cell=2)


def test_docx_monetary_tokens_preserve_sign_and_kopecks_or_report_ambiguity(tmp_path):
    path = tmp_path / "upload"
    doc = Document()
    texts = (
        "Сумма: −1 234,56 руб.",
        "Удержано: - 9,75 руб.",
        "Итого: 1 руб. 25 коп.",
        "Сумма: − 1 рубль 5 копеек.",
        "Сумма: 12 34,56 руб.",
        "Сумма: 1 руб. 125 коп.",
        "Сумма: 1,23 руб. 25 коп.",
        "Сумма: −\u20099,75 руб.",
        "Сумма: 1 руб.25 коп.",
    )
    for text in texts:
        doc.add_paragraph(text)
    doc.save(path)
    result = read_native_document(path, "docx")
    assert [item.raw_text for item in result.observations] == list(texts)
    assert [item.amount for item in result.observations] == [
        Decimal("-1234.56"),
        Decimal("-9.75"),
        Decimal("1.25"),
        Decimal("-1.05"),
        None,
        None,
        None,
        Decimal("-9.75"),
        Decimal("1.25"),
    ]
    assert [(issue.code, issue.locator.paragraph) for issue in result.issues] == [
        ("ambiguous_rub_amount", 5),
        ("ambiguous_rub_amount", 6),
        ("ambiguous_rub_amount", 7),
    ]


def test_long_numeric_text_without_currency_does_not_produce_an_amount():
    assert _text_amount("1 " * 40_000) == (None, False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Удержано: −\t123,45 руб.", "-123.45"),
        ("Удержано: -\u2007123,45\u200aруб.", "-123.45"),
        ("Удержано: −\u30001\u202f123,45 руб.", "-1123.45"),
        ("Сумма: –123,45 руб.", None),
        ("Сумма: ‑123,45 руб.", None),
        ("Сумма: –\t123,45 руб.", None),
        ("Сумма:\n−\n123,45 руб.", None),
        ("Сумма – 123,45 руб.", "123.45"),
        ("Сумма\u2002—\t123,45 руб.", "123.45"),
        ("Сумма: – 123,45 руб.", None),
    ],
)
def test_docx_keeps_explicit_signs_and_distinguishes_label_dashes(tmp_path, text, expected):
    path = tmp_path / "upload"
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    result = read_native_document(path, "docx")
    (observation,) = result.observations
    assert observation.raw_text == text
    assert observation.amount == (Decimal(expected) if expected is not None else None)
    if expected is None:
        assert [issue.code for issue in result.issues] == ["ambiguous_rub_amount"]
    else:
        assert result.issues == ()


@pytest.mark.parametrize(
    "text",
    [
        "Удержано: −\u200b123,45 RUB",
        "Удержано: −\u2060123,45 RUB",
        "Удержано: −\u200e123,45 RUB",
        "Удержано: \u200e−123,45 RUB",
        "Удержано: −\n\u200e123,45 RUB",
        "Сумма: 123,45\nруб.",
        "Сумма: 1 руб.\n25 коп.",
        "Сумма: 1 руб. 25\nкоп.",
        "Сумма: 1\n234,56 RUB",
        "Сумма: 1 руб.\u200b25 коп.",
        "Сумма: 1 руб. 25\u2060коп.",
    ],
)
def test_docx_does_not_accept_a_partial_monetary_token(tmp_path, text):
    path = tmp_path / "upload"
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    result = read_native_document(path, "docx")
    (observation,) = result.observations

    assert observation.raw_text == text
    assert observation.amount is None
    assert [(issue.code, issue.locator) for issue in result.issues] == [
        ("ambiguous_rub_amount", observation.locator)
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Сумма — 123,45 руб.", "123.45"),
        ("Сумма: 1 руб.\t25 коп.", "1.25"),
        ("Сумма:\n123,45 руб.", "123.45"),
        ("Сумма\n123,45 руб.", "123.45"),
    ],
)
def test_docx_keeps_complete_tokens_with_safe_separators(tmp_path, text, expected):
    path = tmp_path / "upload"
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    result = read_native_document(path, "docx")
    (observation,) = result.observations
    assert observation.amount == Decimal(expected)
    assert result.issues == ()


@pytest.mark.parametrize("separator", ["\n", "\u200b", "\u2060", "\u200e"])
def test_docx_rejects_all_interruption_positions_in_monetary_parts(tmp_path, separator):
    parts = (
        ("Удержано: ", "−1 234,56", " RUB"),
        ("Сумма: ", "1,25", " RUB"),
        ("Итого: 1 руб.", " 25 ", "коп."),
    )
    mutated = [
        prefix + token[:index] + separator + token[index:] + suffix
        for prefix, token, suffix in parts
        for index in range(1, len(token))
    ]
    path = tmp_path / "upload"
    document = Document()
    for text in mutated:
        document.add_paragraph(text)
    document.save(path)
    result = read_native_document(path, "docx")

    assert [item.raw_text for item in result.observations] == mutated
    assert all(item.amount is None for item in result.observations)
    assert [(item.code, item.locator) for item in result.issues] == [
        ("ambiguous_rub_amount", item.locator) for item in result.observations
    ]


@pytest.mark.parametrize(
    ("text", "amount", "ambiguous"),
    [
        ("Итого. 123,45 руб.", "123.45", False),
        ("Сумма, 123,45 руб.", "123.45", False),
        ("Сумма, −\u20091 234,56 руб.", "-1234.56", False),
        ("Итого. 1\u202f234,56 руб.", "1234.56", False),
        ("Сумма, 12 34,56 руб.", None, True),
        ("Сумма, 12. 34,56 руб.", None, True),
    ],
)
def test_label_punctuation_is_distinct_from_malformed_grouping(text, amount, ambiguous):
    assert _text_amount(text) == (Decimal(amount) if amount is not None else None, ambiguous)


def test_sum_reads_only_cells_in_the_referenced_rectangle():
    class Sheet(dict):
        def items(self):
            pytest.fail("SUM should not scan all populated cells")

        def get(self, key, default=None):
            cells_read.append(key)
            return super().get(key, default)

    cells_read = []
    value = _Cell("1.25", "n", Decimal("1.25"))
    sheet = Sheet({"Z1": value, "AA2": value, "ZZ100": value})
    assert _sum_candidate("A1", "=SUM(Z1:AA2)", sheet) == (Decimal("2.50"), ("Z1", "AA2"), None)
    assert cells_read == ["Z1", "AA1", "Z2", "AA2"]


@pytest.mark.parametrize("file_format", ["pdf", "docx", "xlsx"])
def test_corrupt_and_missing_files_return_structured_error(tmp_path, file_format):
    broken = tmp_path / "broken"
    broken.write_bytes(b"not a document")
    for path in (tmp_path / "missing", broken):
        result = read_native_document(path, file_format)
        assert not result.observations
        assert [issue.code for issue in result.issues] == ["native_read_error"]


@pytest.mark.parametrize("file_format", ["docx", "xlsx"])
def test_invalid_deflate_in_ooxml_returns_file_diagnostic(tmp_path, file_format):
    path = tmp_path / "upload"
    first_member = "xl/workbook.xml" if file_format == "xlsx" else "[Content_Types].xml"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(first_member, "Compressed file contents")
    payload = bytearray(path.read_bytes())
    # Leave the central directory and local header intact, invalidate the deflate stream.
    pack_into("B", payload, 30 + len(first_member.encode()), 0x07)
    path.write_bytes(payload)

    result = read_native_document(path, file_format)
    assert result.observations == ()
    assert [item.code for item in result.issues] == ["native_read_error"]
