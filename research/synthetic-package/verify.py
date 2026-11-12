"""Validate saved fixtures, including isolation, document facts and exact sums."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image
from pypdf import PdfReader

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FORBIDDEN = ("expected_status", "expected_amount", "available_subtotal", "duplicate_of", "reported_total_differs")


def xlsx_cells(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(t.itertext()) for t in ET.fromstring(z.read("xl/sharedStrings.xml"))]
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
        text = " ".join(v[0] or "" for v in result.values())
        return result, text


def verify(directory: Path) -> dict:
    public = json.loads((directory / "inputs.json").read_text())
    manifest = json.loads((directory / "expectations/manifest.json").read_text())
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
            cells, content = xlsx_cells(path)
            amounts = [Decimal(cells[f"D{r}"][0]) for r in range(9, 12)]
            assert amounts == [Decimal(x["amount"]) for x in doc["items"]]
            assert sum(amounts) == Decimal(doc["amount"]) == Decimal(cells["D13"][0])
            assert cells["D13"][1] == "ROUND(SUM(D9:D11),2)"
            assert cells["C9"][2] in (None, "n", "d")
            actual_date = (date.fromisoformat(cells["C9"][0][:10]) if cells["C9"][2] == "d" else
                           date(1899, 12, 30) + timedelta(days=int(Decimal(cells["C9"][0]))))
            assert actual_date == date.fromisoformat(doc["date"])
            assert "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in content and doc["contract"] in content
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
    for doc in documents.values():
        assert sum(Decimal(x["amount"]) for x in doc["items"]) == Decimal(doc["amount"])
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
