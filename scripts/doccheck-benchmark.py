"""Generate and run reproducible synthetic DocCheck packages through the pilot API."""

import argparse
import csv
import json
import os
import random
import shutil
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from openpyxl import Workbook

import doccheck_bench_client as pilot

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "research/synthetic-package"
sys.path.insert(0, str(GEN))
from generate import canonical_zip, write_json
from model import make_package, public_document, public_report
from render import setup_font, write_docx, write_pdf_or_image, write_report


def write_xlsx(record, path):
    payroll = record["category"] == "payroll"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ведомость" if payroll else "Расчет взносов"
    title = (
        "РАСЧЕТНАЯ ВЕДОМОСТЬ ПО ОПЛАТЕ ТРУДА" if payroll else "РАСЧЕТ СТРАХОВЫХ ВЗНОСОВ"
    )
    sheet.merge_cells("A1:D1")
    sheet["A1"] = title + " — СИНТЕТИЧЕСКИЙ ДОКУМЕНТ"
    sheet["A2"] = "Документ: " + record["number"]
    sheet["A3"] = f"Проект: {record['contract']} | Период: {record['period_label']}"
    if payroll:
        rows = [
            ("Код статьи", "Вид начисления", "Сумма, руб.", "Основание"),
            *(
                (
                    item["article_code"],
                    item["label"],
                    Decimal(item["amount"]),
                    item["basis"],
                )
                for item in record["items"]
            ),
            (None, "ИТОГО", "=SUM(C6:C7)", None),
        ]
    else:
        rows = [
            (
                "База начислений, руб.",
                "Начислено взносов, руб.",
                "Код статьи",
                "Комментарий",
            ),
            (
                Decimal(record["accrual_base"]),
                Decimal(record["amount"]),
                record["article_code"],
                record["comment"],
            ),
        ]
    for y, row in enumerate(rows, 5):
        for x, value in enumerate(row, 1):
            sheet.cell(y, x, value)
    for col in ("A", "B", "C", "D"):
        sheet.column_dimensions[col].width = 34
    workbook.save(path)
    canonical_zip(path)


def generate(seed, root):
    target = root / str(seed)
    inputs = target / "inputs"
    inputs.mkdir(parents=True)
    (target / "expectations").mkdir()
    package = make_package(seed)
    # Contract tokens use digits and visible separators in these benchmark
    # fixtures. Mixed-script identifiers are covered by a separate regression.
    package["contract"] = f"74/{seed}/26-47"
    for document in package["documents"]:
        suffix = "93" if document["scope"] == "other_contract" else "47"
        document["contract"] = f"74/{seed}/26-{suffix}"
    write_report(public_report(package), inputs / "01_kfz.pdf")
    files = [
        {"id": "01_kfz", "file": "inputs/01_kfz.pdf", "role": "report", "format": "pdf"}
    ]
    for doc in package["documents"]:
        path = target / doc["file"]
        if doc.get("duplicate_of"):
            parent = next(
                other
                for other in package["documents"]
                if other["id"] == doc["duplicate_of"]
            )
            shutil.copyfile(target / parent["file"], path)
        elif doc["format"] == "xlsx":
            write_xlsx(public_document(doc), path)
        elif doc["format"] == "docx":
            write_docx(public_document(doc), path)
            canonical_zip(path)
        else:
            write_pdf_or_image(public_document(doc), path)
        files.append(
            {
                **{field: doc[field] for field in ("id", "file", "format")},
                "role": "supporting",
            }
        )
    for entry in files:
        entry["sha256"] = sha256((target / entry["file"]).read_bytes()).hexdigest()
    write_json(
        target / "inputs.json", {"synthetic": True, "seed": seed, "files": files}
    )
    write_json(target / "expectations/manifest.json", package)
    return seed


def measure(root, chosen):
    request = pilot.client(8443)
    for seed in chosen:
        folder = root / str(seed)
        output = folder / "result"
        if (output / "timing.json").exists():
            continue
        manifest = json.loads((folder / "inputs.json").read_text())["files"]
        files = []
        for item in manifest:
            path = folder / item["file"]
            assert sha256(path.read_bytes()).hexdigest() == item["sha256"]
            files.append(("report" if item["role"] == "report" else "documents", path))
        # Shuffle supporting files to exercise order-independent matching.
        support = files[1:]
        random.Random(seed).shuffle(support)
        pilot.run(request, files[:1] + support, {}, output)
        summarize(root)
        print("Completed seed", seed, flush=True)


def summarize(root):
    rows, per_package = [], []
    outcomes = Counter()
    files = []
    for folder in sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.isdecimal()
    ):
        result = folder / "result"
        if not (result / "timing.json").exists():
            continue
        baseline = json.loads((folder / "expectations/manifest.json").read_text())
        timing = json.loads((result / "timing.json").read_text())
        state = json.loads((result / "state.json").read_text())
        findings = (
            json.loads((result / "findings.json").read_text())
            if (result / "findings.json").exists()
            else {}
        )
        outcomes[state["status"]] += 1
        measured = {row["id"]: row for row in findings.get("rows", [])}
        per_package.append(
            {
                "seed": int(folder.name),
                **timing,
                "outcome": state["status"],
                "observed_rows": len(measured),
                "revision": findings.get("versions", {}).get("code_revision"),
                "rules_version": findings.get("versions", {}).get("rules_version"),
                "lora_used": "+lora:"
                in (findings.get("versions", {}).get("model_revision") or ""),
            }
        )
        evid = {entry["id"]: entry for entry in findings.get("evidence", [])}
        for source in findings.get("documents", []):
            files.append(
                {
                    "seed": int(folder.name),
                    "file": source["name"],
                    "format": source["format"],
                    "role": source["role"],
                    "parse_status": source["parse_status"],
                    "decision": source["decision"]["reason_code"],
                    "errors": ";".join(item["code"] for item in source["errors"]),
                }
            )
        for expected in baseline["rows"]:
            observed = measured.get(expected["id"], {})
            components = observed.get("calculation", {}).get("components", [])
            rows.append(
                {
                    "seed": int(folder.name),
                    "article": expected["id"],
                    "expected_status": expected["expected_status"],
                    "status": observed.get("status", "missing"),
                    "expected_report": expected["reported_amount"],
                    "observed_report": observed.get("reported_value"),
                    "expected_subtotal": expected["available_subtotal"],
                    "observed_subtotal": observed.get("observed_evidence_sum"),
                    "report_address": bool(observed.get("reported_evidence_refs")),
                    "components": len(components),
                    "components_with_all_refs": sum(
                        all(
                            item[name] and all(ref in evid for ref in item[name])
                            for name in (
                                "amount_refs",
                                "contract_refs",
                                "period_refs",
                                "article_refs",
                            )
                        )
                        for item in components
                    ),
                }
            )
    for filename, data in (
        ("packages.csv", per_package),
        ("rows.csv", rows),
        ("files.csv", files),
    ):
        if data:
            with (root / filename).open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    durations = sorted(item["seconds"] for item in per_package)
    matrix = Counter((r["expected_status"], r["status"]) for r in rows)
    summary = {
        "generated": sum(
            (folder / "inputs.json").is_file()
            for folder in root.iterdir()
            if folder.is_dir()
        ),
        "processed": len(per_package),
        "files_submitted": sum(item["files"] for item in per_package),
        "outcomes": dict(outcomes),
        "lora_used": sum(item["lora_used"] for item in per_package),
        "revisions": dict(
            Counter(item["revision"] or "unknown" for item in per_package)
        ),
        "rules_versions": dict(
            Counter(item["rules_version"] or "unknown" for item in per_package)
        ),
        "rows_expected": len(rows),
        "rows_found": sum(r["status"] != "missing" for r in rows),
        "exact_report": sum(
            r["expected_report"] is not None
            and r["observed_report"] == r["expected_report"]
            for r in rows
        ),
        "report_address": sum(r["report_address"] for r in rows),
        "exact_nonempty_subtotal": sum(
            r["expected_subtotal"] is not None
            and r["observed_subtotal"] == r["expected_subtotal"]
            for r in rows
        ),
        "nonempty_subtotals_expected": sum(
            r["expected_subtotal"] is not None for r in rows
        ),
        "components": sum(r["components"] for r in rows),
        "components_with_all_refs": sum(r["components_with_all_refs"] for r in rows),
        "status_matrix": {f"{a} -> {b}": n for (a, b), n in matrix.items()},
        "files_by_format": dict(Counter(f["format"] for f in files)),
        "decisions": dict(Counter(f["decision"] for f in files)),
        "seconds": {
            "min": min(durations),
            "median": statistics.median(durations),
            "p95_nearest_rank": durations[(len(durations) * 95 + 99) // 100 - 1],
            "max": max(durations),
            "mean": round(statistics.mean(durations), 2),
        }
        if durations
        else None,
    }
    temporary_summary = root / "summary.tmp"
    write_json(temporary_summary, summary)
    temporary_summary.replace(root / "summary.json")
    return summary


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("generate", "run", "summary"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--first", type=int, default=890100)
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    chosen = range(args.first, args.first + args.count)
    if args.mode == "generate":
        setup_font()
        started = time.monotonic()
        for seed in chosen:
            if not (args.output / str(seed) / "inputs.json").exists():
                generate(seed, args.output)
        print(
            "Generated",
            args.count,
            "packages in",
            round(time.monotonic() - started, 1),
            "seconds",
            flush=True,
        )
    if args.mode == "run":
        measure(args.output, chosen)
    print(json.dumps(summarize(args.output), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
