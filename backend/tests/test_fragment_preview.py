from io import BytesIO

import pytest
from docx import Document
from openpyxl import Workbook
from test_native_pdf import _write_pdf

from doccheck_backend.contracts.result import Evidence
from doccheck_backend.fragment_preview import render_preview
from doccheck_backend.native_pdf import read_pdf


def _preview(content: bytes, file_format: str, locator: dict, raw: str) -> dict:
    evidence = Evidence.model_validate(
        {
            "id": "evidence",
            "document_id": "document",
            "kind": "amount",
            "raw_value": raw,
            "normalized_value": "25.00",
            "unit": "RUB",
            "method": "test",
            "locator": locator,
        }
    )
    return render_preview(BytesIO(content), file_format, evidence).model_dump()


def test_xlsx_reads_only_exact_cell(tmp_path):
    path = tmp_path / "report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "КФЗ"
    sheet["B7"] = "Посторонний текст"
    sheet["C7"] = 25
    workbook.save(path)
    locator = {"kind": "sheet", "sheet": "КФЗ", "range": "C7"}
    assert _preview(path.read_bytes(), "xlsx", locator, "25") == {
        "text": "25",
        "highlight": {"start_byte": 0, "end_byte": 2},
    }
    spanning = {**locator, "range": "B7:C7"}
    assert _preview(path.read_bytes(), "xlsx", spanning, "25") == {
        "text": None,
        "highlight": None,
    }


@pytest.mark.parametrize(
    ("text", "highlight"),
    [
        ("Сумма: 25 руб.", {"start_byte": 12, "end_byte": 14}),
        ("Суммы: 25 и 25 руб.", None),
        ("Сумма: −25 руб.", None),
        ("Сумма: 1 25 руб.", None),
        ("Сумма: 25,99 руб.", None),
    ],
)
def test_docx_exact_cell_suppresses_ambiguous_matches(text, highlight):
    docx = Document()
    table = docx.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Посторонний текст"
    table.cell(0, 1).text = text
    content = BytesIO()
    docx.save(content)
    address = {"kind": "table_cell", "table": 1, "row": 1, "cell": 2}
    assert _preview(content.getvalue(), "docx", address, "25") == {
        "text": text,
        "highlight": highlight,
    }


def test_pdf_preview_uses_exact_recorded_fragment_on_selected_page(tmp_path):
    path = tmp_path / "source.pdf"
    _write_pdf(
        path,
        [
            b"BT /F1 12 Tf 20 140 Td (Other page 25) Tj ET",
            b"BT /F1 12 Tf 50 140 Td (Amount: 25 RUB) Tj ET",
        ],
    )
    *_, observed = read_pdf(path).observations
    locator = observed.locator.model_dump()
    assert locator["page"] == 2
    assert _preview(path.read_bytes(), "pdf", locator, "25") == {
        "text": "Amount: 25 RUB",
        "highlight": {"start_byte": 8, "end_byte": 10},
    }
    locator["bbox"] = [0.1, 0.2, 0.3, 0.4]
    assert _preview(path.read_bytes(), "pdf", locator, "25") == {
        "text": None,
        "highlight": None,
    }


def test_unavailable_text_and_response_size_limit():
    address = {"kind": "page", "page": 1, "bbox": [0.1, 0.2, 0.3, 0.4]}
    assert _preview(b"unneeded", "png", address, "25") == {"text": None, "highlight": None}
    docx = Document()
    docx.add_paragraph("Я" * 2049)
    content = BytesIO()
    docx.save(content)
    address = {"kind": "paragraph", "paragraph": 1}
    assert _preview(content.getvalue(), "docx", address, "Я") == {
        "text": None,
        "highlight": None,
    }
