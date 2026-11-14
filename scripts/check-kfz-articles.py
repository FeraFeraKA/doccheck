"""Exercise articles 0400–0700 through the upload API and the local v3.2 worker."""

import argparse
import csv
import json
import random
import sys
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import doccheck_bench_client as client
from docx import Document
from openpyxl import Workbook, load_workbook
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research/synthetic-package"))
from render import raster, scan_pdf, setup_font

# Fixture labels and expected assignments are independent of the production catalogue.
PURPOSES = {
    "0400": (
        "Подготовка и освоение производства",
        "Назначение: пусконаладка новой производственной линии.",
    ),
    "0500": (
        "Специальная технологическая оснастка",
        "Изготовлена специальная технологическая оснастка для выпуска деталей.",
    ),
    "0600": (
        "Специальное оборудование для научных работ",
        "Приобретено специальное оборудование для экспериментальных исследований.",
    ),
    "0700": (
        "Специальные затраты",
        "Учтены специальные затраты на программу разовых испытаний.",
    ),
}
OLD_LABELS = {
    "0200": "Оплата труда",
    "0300": "Страховые взносы",
    "0800": "Общепроизводственные расходы",
    "0900": "Общехозяйственные расходы",
}


def money(cents: int) -> str:
    return f"{Decimal(cents).scaleb(-2):.2f}"


def source_file(
    path: Path, number: str, contract: str, purpose: str, cents: int, *, date: str = "12.02.2026"
) -> None:
    lines = [
        f"Акт № {number}",
        f"Договор № {contract}",
        f"Дата: {date}",
        purpose,
    ]
    total = f"Итого: {money(cents).replace('.', ',')} руб."
    if path.suffix == ".docx":
        document = Document()
        for line in [*lines, total]:
            document.add_paragraph(line)
        document.save(path)
    elif path.suffix == ".xlsx":
        workbook = Workbook()
        sheet = workbook.active
        for line in lines[:3]:
            sheet.append([line])
        if purpose.startswith("Код статьи: ") and purpose[-4:].isdigit():
            sheet.append(["Код статьи", int(purpose[-4:])])
        else:
            sheet.append([purpose])
        sheet.append(["Позиция", "Сумма, руб."])
        sheet.append(["Исполнено", money(cents)])
        sheet.append(["Итого", Decimal(money(cents))])
        workbook.save(path)
    else:
        data = BytesIO()
        pdf = canvas.Canvas(data, invariant=1, pagesize=(595.28, 841.89))
        pdf.setFont("Synthetic", 13)
        y = 770
        for line in [*lines, total]:
            for part in simpleSplit(line, "Synthetic", 13, 500):
                pdf.drawString(43, y, part)
                y -= 19
            y -= 12
        pdf.save()
        if path.suffix == ".png":
            raster(data.getvalue()).save(path)
        else:
            path.write_bytes(data.getvalue())


def report_xlsx(path: Path, contract: str, reported: dict[str, int], seed: int) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = f"Договор № {contract}"
    sheet["A4"] = "Период: 2026-02-01 — 2026-02-28. Этап 3."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    for row, (code, cents) in enumerate(reported.items(), 7):
        label = OLD_LABELS[code] if code in OLD_LABELS else PURPOSES[code][0]
        if seed % 2:
            sheet.cell(row, 1, int(code))
        elif code in PURPOSES:
            label = f"{code} — {label}"
        sheet.cell(row, 2, label)
        sheet.cell(row, 3, Decimal(money(cents)))
    last = 6 + len(reported)
    sheet.cell(last + 1, 1, "Всего по отчету")
    sheet.cell(last + 1, 3, f"=SUM(C7:C{last})")
    book.save(path)


def report_scan(path: Path, contract: str, reported: dict[str, int]) -> None:
    data = BytesIO()
    pdf = canvas.Canvas(data, invariant=1, pagesize=(595.28, 841.89))
    pdf.setFont("Synthetic", 15)
    pdf.drawString(45, 795, "Карточка учета фактических затрат")
    pdf.drawString(45, 755, f"Договор № {contract}")
    pdf.drawString(45, 715, "Отчетный период: 01.02.2026 - 28.02.2026")
    pdf.setFont("Synthetic", 12)
    for index, (code, cents) in enumerate(reported.items()):
        label = OLD_LABELS[code] if code in OLD_LABELS else f"{code} {PURPOSES[code][0]}"
        y = 654 - index * 38
        pdf.drawString(45, y, label)
        pdf.drawRightString(550, y, money(cents).replace(".", ","))
    y = 654 - len(reported) * 38
    pdf.drawString(45, y, "Итого")
    pdf.drawRightString(550, y, money(sum(reported.values())).replace(".", ","))
    pdf.save()
    scan_pdf(raster(data.getvalue()), path)


def report_ruled_scan(path: Path, contract: str, reported: dict[str, int]) -> None:
    """One selected stage with wide columns and a merged 0400 summary heading."""
    from PIL import Image, ImageDraw, ImageFont
    from render import pdfmetrics

    font_file = pdfmetrics.getFont("Synthetic").face.filename
    if isinstance(font_file, bytes):
        font_file = font_file.decode()
    regular = ImageFont.truetype(font_file, 25)
    title = ImageFont.truetype(font_file, 37)
    image = Image.new("RGB", (3600, 1250), "white")
    draw = ImageDraw.Draw(image)
    draw.text((120, 95), f"Договор № {contract}", fill="black", font=title)
    draw.text((120, 180), "Отчетный период: 01.02.2026 - 28.02.2026", fill="black", font=title)
    xs = [80, 350, 685, 1020, 1350, 1660, 1960, 2240, 2585, 2905, 3225, 3510]
    ys = [290, 480, 620, 755, 890]
    for y in ys:
        draw.line((xs[0], y, xs[-1], y), fill="black", width=5)
    for index, x in enumerate(xs):
        draw.line((x, ys[1] if index == 4 else ys[0], x, ys[-1]), fill="black", width=5)
    columns = ["0200", "0300", "0400", "0401", "0500", "0600", "0700", "0800", "0900", None]
    labels = [
        ("Оплата труда", "0200"),
        ("Страховые взносы", "0300"),
        ("Подготовка и освоение производства", "0400"),
        (),
        ("Специальная", "технологическая", "оснастка 0500"),
        ("Специальное", "оборудование для", "научных работ 0600"),
        ("Специальные затраты", "0700"),
        ("Общепроизводственные", "затраты 0800"),
        ("Общехозяйственные", "затраты 0900"),
        ("Итого",),
    ]
    for index, label in enumerate(labels, 1):
        for line, value in enumerate(label):
            draw.text((xs[index] + 13, ys[0] + 20 + line * 39), value, fill="black", font=regular)
    draw.text((xs[3] + 13, ys[1] + 38), "Всего", fill="black", font=regular)
    draw.text((xs[4] + 13, ys[1] + 38), "Пусковые затраты", fill="black", font=regular)
    for row, stage in ((2, 2), (3, 3)):
        draw.text((xs[0] + 15, ys[row] + 40), f"{stage} этап, 2026", fill="black", font=regular)
        for index, code in enumerate(columns, 1):
            if stage == 2 or code == "0401":
                cents = 1234
            else:
                cents = sum(reported.values()) if code is None else reported[code]
            draw.text(
                (xs[index] + 20, ys[row] + 40), money(cents).replace(".", ","),
                fill="black", font=regular,
            )
    with BytesIO() as buffer:
        pdf = canvas.Canvas(buffer, pagesize=(900, 312.5), invariant=1)
        from reportlab.lib.utils import ImageReader

        pdf.drawImage(ImageReader(image), 0, 0, width=900, height=312.5)
        pdf.save()
        path.write_bytes(buffer.getvalue())


def package(folder: Path, seed: int):
    rng = random.Random(seed)
    contract = f"74/{seed}/26-47"
    folder.mkdir(parents=True, exist_ok=True)
    support = []
    expected = {}
    reported = dict.fromkeys(OLD_LABELS, 0)
    codes = list(PURPOSES)
    rng.shuffle(codes)
    for code in codes:
        index = list(PURPOSES).index(code)
        items = {}
        for variant in range(2):
            # Each article has coded and text-only evidence, with formats rotating per package.
            ext = ("docx", "xlsx", "pdf", "xlsx")[(seed + index + 2 * variant) % 4]
            if variant == 0 and index == seed % 4:
                ext = "png"  # One scan per package exercises the real LoRA reader.
            name = f"source-{rng.randrange(100000, 999999)}.{ext}"
            path = folder / name
            purpose = f"Код статьи: {code}" if variant == 0 else PURPOSES[code][1]
            amount = rng.randrange(10001, 95000)
            source_file(path, f"{seed}-{index + 1}{variant + 1}", contract, purpose, amount)
            support.append(path)
            items[name] = amount
        subtotal = sum(items.values())
        delta = (0, 1, -1, 745)[(seed + index) % 4]
        reported[code] = subtotal + delta
        expected[code] = {"items": items, "observed": subtotal, "reported": subtotal + delta}
    report_kind = seed % 4
    report = folder / ("kfz.pdf" if report_kind in {1, 3} else "kfz.xlsx")
    if report_kind == 1:
        report_scan(report, contract, reported)
    elif report_kind == 3:
        report_ruled_scan(report, contract, reported)
    else:
        report_xlsx(report, contract, reported, seed)

    duplicate = folder / ("duplicate" + support[0].suffix)
    duplicate.write_bytes(support[0].read_bytes())
    excluded = {
        "different-contract.docx": ("99/88/26-98", "Код статьи: 0400", "12.02.2026"),
        "outside-period.docx": (contract, "Код статьи: 0500", "12.03.2026"),
        "conflicting-purpose.docx": (
            contract,
            "Код статьи: 0500. Назначение: специальное оборудование для научных работ.",
            "12.02.2026",
        ),
        "two-codes.docx": (contract, "Код статьи: 0400 и 0700", "12.02.2026"),
        "unclear-purpose.docx": (contract, "Назначение: расходы по проекту.", "12.02.2026"),
    }
    for index, (name, (contract_id, purpose, date)) in enumerate(excluded.items()):
        path = folder / name
        source_file(path, f"{seed}-9{index}", contract_id, purpose, 999900 + index, date=date)
        support.append(path)
    path = folder / "mixed-items.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([f"Договор № {contract}"])
    sheet.append(["Дата: 12.02.2026"])
    sheet.append(["Код статьи", "Операция", "Сумма, руб."])
    sheet.append([400, "Первый вид работ", Decimal("999.90")])
    sheet.append([])
    sheet.append([700 if seed % 2 else None, "Второй вид работ", Decimal("999.11")])
    sheet.append(["Итого", None, "=SUM(C4:C6)"])
    workbook.save(path)
    support.append(path)
    rng.shuffle(support)
    support.append(duplicate)
    fields = {}
    if report_kind == 3:
        fields = {
            "contract_number": contract,
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "report_row_locator": json.dumps(
                {"kind": "page", "page": 1, "fragment_id": "kfz-stage-3-2026"}
            ),
        }
    return [("report", report), *(("documents", path) for path in support)], fields, expected


def verify(output: Path, expected: dict, seed: int) -> list[dict]:
    state = json.loads((output / "state.json").read_text())
    if state["status"] not in {"completed", "completed_with_issues"}:
        raise AssertionError(state)
    result = json.loads((output / "findings.json").read_text())
    documents = {item["id"]: item for item in result["documents"]}
    by_name = {item["name"]: item for item in documents.values()}
    duplicate = next(item for item in documents.values() if item["name"].startswith("duplicate."))
    same_bytes = [item for item in documents.values() if item["sha256"] == duplicate["sha256"]]
    assert len(same_bytes) == 2
    included = [item for item in same_bytes if item["decision"]["state"] == "include"]
    omitted = [item for item in same_bytes if item["decision"]["reason_code"] == "byte_duplicate"]
    assert len(included) == len(omitted) == 1 and omitted[0]["duplicate_of"] == included[0]["id"]
    original_name = next(item["name"] for item in same_bytes if item["id"] != duplicate["id"])
    for name in ("different-contract.docx", "outside-period.docx"):
        assert by_name[name]["decision"]["state"] == "exclude", by_name[name]
    for name in (
        "conflicting-purpose.docx", "two-codes.docx", "unclear-purpose.docx", "mixed-items.xlsx",
    ):
        assert by_name[name]["decision"]["state"] == "needs_review", by_name[name]
    evidence = {item["id"]: item for item in result["evidence"]}
    rows = {row["indicator_code"]: row for row in result["rows"]}
    observations = []
    for code, target in expected.items():
        row = rows[code]
        assert row["reported_value"] == money(target["reported"]), (code, row)
        assert row["observed_evidence_sum"] == money(target["observed"]), (code, row)
        assert row["reported_evidence_refs"] and all(
            documents[evidence[ref]["document_id"]]["role"] == "report"
            for ref in row["reported_evidence_refs"]
        )
        difference = target["reported"] - target["observed"]
        reason = next(
            reason for reason in row["reasons"]
            if reason["code"] == ("observed_difference" if difference else "observed_match")
        )
        if difference:
            relation = "больше" if difference > 0 else "меньше"
            assert f"{money(abs(difference))} ₽ {relation}" in reason["message"], reason
        assert row["status"] == "unverified" and row["delta"] is None
        items = {}
        for component in row["calculation"]["components"]:
            sources = {evidence[ref]["document_id"] for ref in component["amount_refs"]}
            assert len(sources) == 1
            source = sources.pop()
            name = documents[source]["name"]
            if source == duplicate["id"]:
                name = original_name
            assert name not in items
            items[name] = component["amount"]
            for kind in ("article", "contract", "period", "amount"):
                assert component[f"{kind}_refs"]
                for ref in component[f"{kind}_refs"]:
                    value = evidence[ref]
                    assert value["document_id"] == source and value["kind"] == kind
                    assert value["locator"]
                    if kind == "article":
                        assert value["normalized_value"] == code
        assert items == {name: money(cents) for name, cents in target["items"].items()}, items
        observations.append({
            "seed": seed,
            "code": code,
            "kfz": row["reported_value"],
            "primary_sum": row["observed_evidence_sum"],
            "difference": money(difference),
            "documents": len(items),
            "comparison": reason["code"],
            "status": row["status"],
            "lora": bool(result["versions"]["model_revision"]),
        })
    with (output / "findings.xlsx").open("rb") as stream:
        workbook = load_workbook(stream, read_only=True)
        try:
            table = next(
                sheet for sheet in workbook if "Сумма по доступным источникам" in [
                    item.value for row in sheet.iter_rows(max_row=12) for item in row
                ]
            )
            exported = {
                str(values[2]): (values[4], values[6], values[11])
                for values in table.values if len(values) > 11 and str(values[2]) in expected
            }
            for item in observations:
                kfz, primary_sum, message = exported[item["code"]]
                assert Decimal(str(kfz)) == Decimal(item["kfz"])
                assert Decimal(str(primary_sum)) == Decimal(item["primary_sum"])
                if item["comparison"] == "observed_difference":
                    assert f"{abs(Decimal(item['difference'])):.2f} ₽" in message
                else:
                    assert "совпадает" in message
        finally:
            workbook.close()
    return observations


def loopback(port: int):
    opener = build_opener(ProxyHandler({}))

    def request(path, data=None, headers=None, *, binary=False):
        req = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers or {})
        with opener.open(req, timeout=45) as response:
            body = response.read()
            return response.status, body if binary else json.loads(body)

    return request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--seed", type=int, default=84010)
    parser.add_argument("--count", type=int, default=12)
    options = parser.parse_args()
    setup_font()
    options.output.mkdir(parents=True, exist_ok=True)
    observations = []
    for seed in range(options.seed, options.seed + options.count):
        folder = options.output / str(seed)
        files, fields, expected = package(folder / "inputs", seed)
        result_path = folder / "result"
        client.run(loopback(options.port), files, fields, result_path)
        observations.extend(verify(result_path, expected, seed))
        print(f"Verified package {seed}, {len(observations)} article rows so far", flush=True)
    with (options.output / "articles.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(observations[0]))
        writer.writeheader()
        writer.writerows(observations)
    print(Counter(item["comparison"] for item in observations), flush=True)


if __name__ == "__main__":
    main()
