from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document

from doccheck_backend.contracts.locators import PageLocator, ParagraphLocator, TableCellLocator
from doccheck_backend.native_reader import read_native_document

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def _workbook(path: Path, rows: str, *, extras: dict[str, str] | None = None) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}">'
            '<sheets><sheet name="Синтетика" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{_PACKAGE}"><Relationship Id="rId1" '
            f'Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{_MAIN}"><sheetData>{rows}</sheetData></worksheet>',
        )
        for member, content in (extras or {}).items():
            archive.writestr(member, content)
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
        '<row r="6"><c r="A6"><v>12000.00</v></c><c r="B6"><v>2813.08</v></c></row>',
    )
    result = read_native_document(path, "xlsx")
    assert result.issues == ()
    assert [
        (item.locator.range, item.amount, item.amount_role)
        for item in result.observations
        if item.amount is not None
    ] == [("A6", Decimal("12000.00"), "basis"), ("B6", Decimal("2813.08"), "total")]


def _minimal_pdf(path: Path, lines: list[str]) -> Path:
    stream = "\n".join(
        f"BT /F1 12 Tf 30 {150 - count * 20} Td ({line}) Tj ET" for count, line in enumerate(lines)
    ).encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
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


@pytest.mark.parametrize("file_format", ["pdf", "docx", "xlsx"])
def test_corrupt_and_missing_files_return_structured_error(tmp_path, file_format):
    broken = tmp_path / "broken"
    broken.write_bytes(b"not a document")
    for path in (tmp_path / "missing", broken):
        result = read_native_document(path, file_format)
        assert not result.observations
        assert [issue.code for issue in result.issues] == ["native_read_error"]
