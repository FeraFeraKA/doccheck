"""Validate saved fixtures, including isolation, document facts and exact sums."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image
from pypdf import PdfReader

from model import spreadsheet_period

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FORBIDDEN = ("expected_status", "expected_amount", "available_subtotal", "duplicate_of", "reported_total_differs")


def xlsx_cells(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(t.itertext()) for t in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = workbook.findall("s:sheets/s:sheet", NS)
        assert len(sheets) == 1, f"{path.name}: expected one worksheet"
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        result = {}
        for cell in root.findall(".//s:c", NS):
            v = cell.find("s:v", NS)
            value = v.text if v is not None else None
            if cell.get("t") == "s":
                value = shared[int(value)]
            elif cell.get("t") == "inlineStr":
                value = "".join(cell.find("s:is", NS).itertext())
            f = cell.find("s:f", NS)
            result[cell.get("r")] = (value, f.text if f is not None else None, cell.get("t"))
        merges = {cell.attrib["ref"] for cell in root.findall("s:mergeCells/s:mergeCell", NS)}
        return sheets[0].attrib["name"], result, merges


def verify_xlsx(path: Path, doc: dict) -> str:
    sheet, cells, merges = xlsx_cells(path)
    payroll = doc["category"] == "payroll"
    assert payroll or doc["category"] == "insurance"
    expected_sheet = "Ведомость" if payroll else "Расчет взносов"
    assert sheet == expected_sheet, f"{path.name}: expected worksheet {expected_sheet}"
    assert merges == {"A1:D1"}, f"{path.name}: unexpected merged cells"

    data_rows = (6, 7) if payroll else (6,)
    populated = {"A1", "A2", "A3"}
    populated.update(f"{column}{row}" for row in (5, *data_rows) for column in "ABCD")
    if payroll:
        populated.update(("B8", "C8"))
    assert {cell for cell, (value, formula, _) in cells.items() if value or formula} == populated, (
        f"{path.name}: unexpected populated cell addresses"
    )

    def cell_text(address: str) -> str:
        value, formula, kind = cells[address]
        assert value is not None and formula is None and kind in ("s", "inlineStr", "str"), (
            f"{path.name}:{address}: expected text"
        )
        return value

    def cell_money(address: str, formula: str | None = None) -> Decimal:
        value, stored_formula, kind = cells[address]
        assert value is not None and kind in (None, "n") and stored_formula == formula, (
            f"{path.name}:{address}: unexpected amount or formula"
        )
        return Decimal(value)

    assert "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in cell_text("A1")
    assert cell_text("A2") == f"Документ: {doc['number']}"
    assert cell_text("A3") == (
        f"Проект: {doc['contract']} | Период: {spreadsheet_period(doc['period_start'])}"
    )
    if payroll:
        headers = ("Код статьи", "Вид начисления", "Сумма, руб.", "Основание")
        for row, entry in zip(data_rows, doc["items"], strict=True):
            assert cell_text(f"A{row}") == entry["article_code"]
            assert cell_text(f"B{row}") == entry["label"]
            assert cell_money(f"C{row}") == Decimal(entry["amount"])
            assert cell_text(f"D{row}") == entry["basis"]
        assert cell_text("B8") == "ИТОГО"
        cached_total = cell_money("C8", "SUM(C6:C7)")
        # Excel stores the SUM cache in floating point.
        assert cached_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal(doc["amount"])
    else:
        headers = ("База начислений, руб.", "Начислено взносов, руб.", "Код статьи", "Комментарий")
        assert cell_money("A6") == Decimal(doc["accrual_base"])
        assert cell_money("B6") == Decimal(doc["amount"])
        assert cell_text("C6") == doc["article_code"]
        assert cell_text("D6") == doc["comment"]
    assert tuple(cell_text(f"{column}5") for column in "ABCD") == headers, (
        f"{path.name}: unexpected field labels"
    )
    return " ".join(value or "" for value, _, _ in cells.values())


def verify(directory: Path) -> dict:
    public = json.loads((directory / "inputs.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "expectations/manifest.json").read_text(encoding="utf-8"))
    assert public["synthetic"] is True and manifest["synthetic"] is True
    assert set(public) == {"synthetic", "files"}
    inputs = public["files"]
    assert len(inputs) == 23
    assert len({d["id"] for d in inputs}) == len(inputs)
    assert Counter(d["format"] for d in inputs) == {"pdf": 10, "xlsx": 10, "docx": 2, "png": 1}
    assert {p.relative_to(directory).as_posix() for p in (directory / "inputs").iterdir()} == {d["file"] for d in inputs}
    documents = {d["id"]: d for d in manifest["documents"]}
    assert set(documents) == {d["id"] for d in inputs if d["role"] == "supporting"}
    hashes = {}
    for item in inputs:
        assert set(item) == {"id", "file", "role", "format", "acquisition", "sha256"}
        path = directory / item["file"]
        assert path.resolve().parent == (directory / "inputs").resolve()
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], f"Hash mismatch: {path.name}"
        hashes[item["id"]] = item["sha256"]
        doc = documents.get(item["id"])
        content = ""
        if item["format"] == "xlsx":
            content = verify_xlsx(path, doc)
        elif item["format"] == "docx":
            with zipfile.ZipFile(path) as z:
                content = " ".join(" ".join(ET.fromstring(z.read(n)).itertext()) for n in z.namelist()
                                   if re.fullmatch(r"word/(document|header\d+)\.xml", n))
            assert "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in content and doc["contract"] in content
            assert doc["amount"].replace(".", ",") in content.replace(" ", "")
        elif item["format"] == "pdf":
            reader = PdfReader(path)
            assert len(reader.pages) == 1
            content = reader.pages[0].extract_text()
            if item["acquisition"] == "scan":
                assert not content.strip(), "Scan unexpectedly has a text layer"
                assert len(reader.pages[0].images) == 1
            else:
                assert "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in content and doc["contract"] in content
                assert doc["amount"].replace(".", ",") in content.replace(" ", "")
        else:
            with Image.open(path) as img:
                assert img.width >= 1000 and img.height >= 1500
                img.verify()
        assert not any(key in content for key in FORBIDDEN), f"Expectation leaked: {path.name}"
    payroll_amounts = {(doc["contract"], doc["period_start"]): doc["amount"]
                       for doc in documents.values() if doc["category"] == "payroll"}
    for doc in documents.values():
        assert sum(Decimal(x["amount"]) for x in doc["items"]) == Decimal(doc["amount"])
        if doc["category"] == "insurance":
            assert doc["accrual_base"] == payroll_amounts[(doc["contract"], doc["period_start"])]
        if doc.get("duplicate_of"):
            assert hashes[doc["id"]] == hashes[doc["duplicate_of"]]
    for row in manifest["rows"]:
        included = [documents[x] for x in row["included_documents"]]
        expected_members = {d["id"] for d in documents.values()
                            if d["category"] == row["id"] and not d.get("duplicate_of")
                            and d["contract"] == manifest["contract"]
                            and manifest["period_start"] <= d["period_start"] <= d["period_end"] <= manifest["period_end"]}
        assert {d["id"] for d in included} == expected_members
        subtotal = sum((Decimal(d["amount"]) for d in included), Decimal(0))
        if row["available_subtotal"] is not None:
            assert subtotal == Decimal(row["available_subtotal"])
        if row["expected_status"] == "unverified":
            assert row["expected_amount"] is None and row["delta"] is None
            assert not included or any(d["partial"] for d in included)
        else:
            assert row["completeness"] == "complete" and included and not any(d["partial"] for d in included)
            assert subtotal == Decimal(row["expected_amount"])
            delta = Decimal(row["reported_amount"]) - subtotal
            assert delta == Decimal(row["delta"])
            assert (delta == 0) == (row["expected_status"] == "verified")
    return {"files": len(inputs), "formats": dict(Counter(d["format"] for d in inputs)),
            "rows": dict(Counter(d["expected_status"] for d in manifest["rows"])),
            "structural_comparison_with_original": "pending_local_human_review", "ocr_and_pipeline": "not_run"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), ensure_ascii=False, indent=2))
