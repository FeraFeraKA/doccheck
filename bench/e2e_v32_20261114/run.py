"""Isolated file-to-result v2: completeness and source-grounded category checks.

No reference labels enter runtime. Baseline preserves v1 behavior; quality and
compact variants use new rules. Every run has separate outputs and request caches.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
from . import runtime, report_benchmark
from .runtime import MODEL_DIGEST, ModelUnavailableError
from .decision_rules import reconcile, parse_amount, normalize_identifier, money_string
from .native_report import read_native_report
from .classification import apply_source_checks
from .document_identity import apply_document_number_checks
from .explanations import explain, render_text

VARIANT = "quality"
COMPACT_SUFFIX = "\nJSON запиши одной строкой без отступов и пробелов вне строк. Сохрани все поля и дословные значения."

def configure_variant(name):
    global VARIANT, runtime, report_benchmark, reconcile, read_native_report
    VARIANT = name
    if name == "baseline":
        from .baseline import runtime, report_benchmark
        from .baseline.decision_rules import reconcile
        from .baseline.native_report import read_native_report
    elif name == "compact":
        runtime.PROMPT += COMPACT_SUFFIX


MODEL = runtime.MODELS["4b"]
CATEGORY_CODES = {"0200": "payroll", "0300": "insurance", "0800": "production_overhead", "0900": "general_admin"}
CODE = Path(__file__).resolve().parent
SOURCE_FILES = [CODE / f for f in ("run.py", "runtime.py", "report_benchmark.py", "decision_rules.py", "native_report.py", "classification.py", "document_identity.py", "explanations.py")] + [CODE / "baseline" / f for f in ("runtime.py", "report_benchmark.py", "decision_rules.py", "native_report.py")]


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_source(entry):
    actual = sha(runtime.resolve_file(entry))
    if entry.get("sha256") and actual != entry["sha256"]:
        raise ValueError("Source changed after input freeze")
    return actual


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def source_hashes():
    return {str(p.relative_to(ROOT)): sha(p) for p in SOURCE_FILES}


def safe_manifest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    packages = data["packages"]
    allowed_package = {"id", "package_id", "report", "documents", "scope", "completeness"}
    allowed_document = {"id", "path", "format", "role", "sha256"}
    seen = set()
    for package in packages:
        if set(package) - allowed_package:
            raise ValueError("Unapproved package metadata in runtime manifest")
        package["package_id"] = package.get("package_id", package.get("id"))
        if not re.fullmatch(r"[A-Za-z0-9_-]+", package["package_id"] or "") or package["package_id"] in seen:
            raise ValueError("Invalid or repeated package ID")
        seen.add(package["package_id"])
        if set(package["scope"]) - {"contract_number", "period_start", "period_end", "stage", "year"}:
            raise ValueError("Unapproved scope fields")
        doc_ids = set()
        for doc in [package["report"], *package["documents"]]:
            if set(doc) - allowed_document or doc["id"] in doc_ids:
                raise ValueError("Unapproved document metadata or repeated ID")
            doc_ids.add(doc["id"])
            file = runtime.resolve_file(doc).resolve()
            allowed_roots = (ROOT / "data", ROOT / "artifacts", ROOT / "docs" / "case" / "examples")
            if not file.is_file() or not any(file.is_relative_to(root.resolve()) for root in allowed_roots):
                raise ValueError("Input must be an existing local file under data/, artifacts/ or docs/case/examples/")
            if {"reference", "groundtruth", "oracle"} & {part.casefold() for part in file.parts}:
                raise ValueError("Reference data cannot be a runtime input")
            actual = sha(file)
            if doc.get("sha256") and doc["sha256"] != actual:
                raise ValueError("Source hash mismatch")
            doc["sha256"] = actual
        if package["report"].get("role") != "report" or any(d.get("role") != "primary" for d in package["documents"]):
            raise ValueError("Explicit report and primary roles are required")
        if runtime.resolve_file(package["report"]).suffix.lower() != ".xlsx" and (
            str(package["scope"].get("stage", 3)) != "3" or str(package["scope"].get("year", 2026)) != "2026"):
            raise ValueError("Frozen raster report prompt supports only stage 3 / year 2026")
    return packages


def identity_issues(report, scope):
    if report.get("error"):
        return ["report_extraction_error"]
    p = report["prediction"]
    issues = []
    if normalize_identifier(p.get("contract_number")) != normalize_identifier(scope["contract_number"]):
        issues.append("report_contract_not_verified")
    if report["input_kind"] == "bounded_native_report":
        for key in ("period_start", "period_end"):
            if p.get(key) != scope[key]:
                issues.append("report_" + key + "_not_verified")
        if str(p.get("stage")) != str(scope.get("stage", 3)):
            issues.append("report_stage_not_verified")
    else:
        stage = re.sub(r"\s+|этап|[.№]", "", str(p.get("stage") or "").casefold())
        stage = re.sub(r"-?(й|ый)$", "", stage)
        if stage == "iii":
            stage = "3"
        year = re.sub(r"\s+|год|г\.?", "", str(p.get("year") or "").casefold())
        if stage != str(scope.get("stage", 3)):
            issues.append("report_stage_not_verified")
        if year != str(scope.get("year", 2026)):
            issues.append("report_year_not_verified")
    return issues


def extract_report(entry):
    start = time.perf_counter()
    record = {"id": entry["id"], "path": entry["path"], "error": None}
    try:
        record["source_hash"] = verify_source(entry)
        if runtime.resolve_file(entry).suffix.lower() == ".xlsx":
            prediction = read_native_report(runtime.resolve_file(entry))
            from openpyxl import load_workbook
            book = load_workbook(runtime.resolve_file(entry), read_only=True, data_only=False)
            try:
                stage_match = re.search(r"Этап\s+(\d+)\.", str(book["КФЗ"]["A4"].value))
                prediction["stage"] = stage_match.group(1) if stage_match else None
            finally:
                book.close()
            record.update(input_kind="bounded_native_report", prediction=prediction)
        else:
            prepared = report_benchmark.prepare_report(entry, "full")
            record["input_kind"] = prepared["kind"]
            record.update(report_benchmark.infer_report(prepared, MODEL, "direct"))
        verify_source(entry)
    except Exception as exc:
        record.update(error=f"{type(exc).__name__}: {exc}", prediction={})
    record["elapsed_s"] = time.perf_counter() - start
    return record


def extract_primary(entry, previous):
    start = time.perf_counter()
    record = {"id": entry["id"], "path": entry["path"], "error": None}
    try:
        record["source_hash"] = verify_source(entry)
        prior = previous.get(record["source_hash"])
        if prior and not prior.get("error"):
            record.update(prediction=copy.deepcopy(prior.get("raw_prediction", prior["prediction"])), source_native_text=prior.get("source_native_text"), input_kind=prior["input_kind"],
                          duplicate_of=prior["id"], byte_duplicate_reuse=True, reused_result=False)
            record["raster_pages"] = prior.get("raster_pages", ())
        else:
            prepared = runtime.prepare(entry) if VARIANT == "baseline" else runtime.prepare(
                entry, split_pdf=True
            )
            record["input_kind"] = prepared["kind"]
            record["raster_pages"] = tuple(
                page.number for page in prepared.get("pages", ()) if page.image is not None
            )
            if runtime.resolve_file(entry).suffix.lower() == ".png" and prepared["kind"] == "scan":
                record["raster_pages"] = (1,)
            # Partial native text cannot establish that a field is absent from
            # the whole document. Mixed records use model-only checks here.
            record["source_native_text"] = prepared.get("text") if prepared["kind"] == "native" else None
            record.update(runtime.infer(entry, prepared, MODEL, "direct"))
        verify_source(entry)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        record.update(error=f"{type(exc).__name__}: {exc}", prediction={})
    if not record.get("error") and VARIANT != "baseline":
        record = apply_source_checks(record, record.get("source_native_text"))
        record = apply_document_number_checks(record, record.get("source_native_text"))
    record["elapsed_s"] = time.perf_counter() - start
    if record.get("source_hash"):
        previous.setdefault(record["source_hash"], record)
    return record


def compare(package, report, documents):
    scope = package["scope"]
    p = report.get("prediction", {})
    if report.get("input_kind") == "bounded_native_report" and not report.get("error"):
        rows = p["rows"]
        reported_total = parse_amount(p["total"]["amount"])
    else:
        amounts = p.get("amounts") or {}
        rows = [{"category": category, "reported_amount": amounts.get(code)} for code, category in CATEGORY_CODES.items()]
        reported_total = parse_amount(amounts.get("total"))
    kwargs = {} if VARIANT == "baseline" else {"completeness": package.get("completeness")}
    result = reconcile(documents, rows, scope["contract_number"], scope["period_start"], scope["period_end"], **kwargs)
    issues = identity_issues(report, scope)
    result["report_identity_issues"] = issues
    if issues:
        for row in result["rows"]:
            row.update(status="unverified", expected_amount=None, delta=None)
            row["reasons"].extend({"id": report["id"], "reason": issue} for issue in issues)
    sufficient = bool(result["rows"]) and all(row["status"] != "unverified" for row in result["rows"])
    expected_total = sum((parse_amount(row["expected_amount"]) for row in result["rows"]), Decimal("0")) if sufficient else None
    delta = reported_total - expected_total if expected_total is not None and reported_total is not None else None
    result["total"] = {"category": "total", "reported_amount": money_string(reported_total),
        "expected_amount": money_string(expected_total), "delta": money_string(delta),
        "status": "unverified" if delta is None else ("correct" if delta == 0 else "incorrect"),
        "reasons": [] if delta is not None else [{"reason": "total_or_constituent_unverified"}],
        "source_ids": sorted({i for row in result["rows"] for i in row["source_ids"]})}
    return result


def manual_review(report, documents, result):
    uncertainty = set()
    reasons = []
    for doc in [report, *documents]:
        if doc.get("error"):
            uncertainty.add(doc["id"])
            reasons.append({"id": doc["id"], "reason": "extraction_error"})
    for issue in result["identity_warnings"]:
        if issue["reason"] in {"unresolved_document_identity_collision", "suspected_bare_tail_identity"}:
            uncertainty.add(issue["id"])
        reasons.append(issue)
    uncertain_rows, attention_rows = [], []
    attention = set()
    for row in [*result["rows"], result["total"]]:
        if row["status"] != "correct":
            attention_rows.append(row["category"])
            attention.update([report["id"], *row.get("source_ids", [])])
        if row["status"] == "unverified":
            uncertain_rows.append(row["category"])
            uncertainty.add(report["id"])
            for reason in row.get("reasons", []):
                if reason.get("id"):
                    uncertainty.add(reason["id"])
                reasons.append({"category": row["category"], **reason})
    attention.update(uncertainty)
    return {"document_ids": sorted(attention), "uncertainty_document_ids": sorted(uncertainty),
        "row_categories": attention_rows, "uncertainty_row_categories": uncertain_rows,
        "package_required": bool(attention_rows or attention),
        "uncertainty_package_required": bool(uncertain_rows or uncertainty), "reasons": reasons}


def process_package(package, run_id, output, timing_mode, split):
    folder = output / package["package_id"]
    folder.mkdir()
    runtime.ART = folder / "runtime"
    report_benchmark.ART = runtime.ART
    started_at = utc()
    start = time.perf_counter()
    progress = {"run_id": run_id, "package_id": package["package_id"], "stage": "report", "completed_files": 0,
                "total_files": 1 + len(package["documents"]), "started_at_utc": started_at}
    write_json(output / "progress.json", progress)
    report = extract_report(package["report"])
    write_json(folder / "report.json", report)
    progress.update(completed_files=1, stage="primary")
    write_json(output / "progress.json", progress)
    print(json.dumps({"run": run_id, "package": package["package_id"], "file": report["id"], "seconds": round(report["elapsed_s"], 2), "error": report["error"]}), flush=True)
    documents, previous = [], {}
    for entry in package["documents"]:
        doc = extract_primary(entry, previous)
        documents.append(doc)
        with (folder / "documents.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
        progress["completed_files"] += 1
        write_json(output / "progress.json", progress)
        print(json.dumps({"run": run_id, "package": package["package_id"], "file": doc["id"], "seconds": round(doc["elapsed_s"], 2), "error": doc["error"]}), flush=True)
    rules_start = time.perf_counter()
    result = compare(package, report, documents)
    review = manual_review(report, documents, result)
    explanations = explain(report, documents, result) if VARIANT != "baseline" else None
    rules_s = time.perf_counter() - rules_start
    model_load_s = sum((r.get("raw_response") or {}).get("load_duration", 0) / 1e9
        for r in [report, *documents] if not r.get("reused_result"))
    record = {"package_id": package["package_id"], "run_id": run_id, "split": split,
        "started_at_utc": started_at, "completed_at_utc": utc(), "elapsed_s": time.perf_counter() - start,
        "model_load_s": model_load_s, "timing_mode": timing_mode, "scope": package["scope"],
        "completeness": package.get("completeness"), "model": MODEL, "pipeline": "e2e-v32-20261114", "variant": VARIANT,
        "report": report, "documents": documents, "reconciliation": result, "manual_review": review,
        "stage_timing_s": {"report": report["elapsed_s"], "primaries": sum(r["elapsed_s"] for r in documents), "rules": rules_s},
        "errors": [{"id": r["id"], "error": r["error"]} for r in [report, *documents] if r.get("error")],
        "limitations": ["No browser upload, human review time, or UI rendering is measured.",
            "V10 number policy is not integrated into this financial prototype.",
            "Baseline ignores declared completeness; quality/compact use scoped completeness. Payroll exception rules remain unconfirmed.",
            "Raster KFZ coverage is four aggregate articles (0200/0300/0800/0900) and total; labor effort/internal subcolumns/other articles are not evaluated.",
            "OCR citation/coordinates are not independently validated by this run.",
            "Native report reader supports one bounded XLSX template."]}
    if explanations is not None:
        record["explanations"] = explanations
        (folder / "explanation.txt").write_text(render_text(explanations), encoding="utf-8")
    write_json(folder / "result.json", record)
    # Include completed JSON persistence in the full elapsed measurement.
    record["elapsed_s"] = time.perf_counter() - start
    record["completed_at_utc"] = utc()
    write_json(folder / "result.json", record)
    print(json.dumps({"package_complete": package["package_id"], "seconds": round(record["elapsed_s"], 2), "errors": len(record["errors"])}), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=["original", "fresh"], required=True)
    parser.add_argument("--timing-mode", choices=["cold", "warm"], required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--variant", choices=["baseline", "quality", "compact"], default="quality")
    args = parser.parse_args()
    configure_variant(args.variant)
    packages = safe_manifest(args.manifest)
    frozen = Path(args.freeze)
    current = source_hashes()
    if args.freeze_only:
        if frozen.exists():
            raise FileExistsError(frozen)
        write_json(frozen, {"created_at_utc": utc(), "source_hashes": current, "model": MODEL,
            "primary_prompt_sha256": hashlib.sha256(runtime.PROMPT.encode()).hexdigest(),
            "report_prompt_sha256": hashlib.sha256(report_benchmark.PROMPT.encode()).hexdigest(),
            "scope": "Isolated financial pipeline v2; not V10 and not deployed UI.", "variant": VARIANT,
            "report_identity_gate": "Mismatched report identity makes all rows unverified before scoring.",
            "repeat_policy": "No automatic retries or tuning after evaluation. Original repeated for cold/warm stability; new packages evaluated once.",
            "timing": "File hashes/read/render/inference/rules/result persistence; excludes corpus construction, evaluation, queue delay, UI and human review.",
            "manual_review": "Unresolved uncertainty and all human attention reported separately; total not an independent discrepancy.",
            "input_freeze": "Each run writes the sanitized manifest and hashes before inference; every input hash is checked before/after extraction.",
            "raster_report_coverage": "0200/0300/0800/0900 and total only; no labor effort/internal subcolumns/other articles.",
            "unresolved_domain_rules": ["IT certificate applicability", "salary explanations", "May30/31 period boundary", "tolerance/rounding"]})
        return
    protocol = json.loads(frozen.read_text(encoding="utf-8"))
    if protocol["variant"] != VARIANT:
        raise ValueError("Variant differs from frozen protocol")
    if protocol["source_hashes"] != current:
        raise ValueError("Code changed after freeze")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"version": runtime.api("/api/version"), "tags": runtime.api("/api/tags"), "loaded_before": runtime.api("/api/ps")}
    matches = [m for m in metadata["tags"].get("models", []) if m.get("name") == MODEL]
    if len(matches) != 1 or matches[0].get("digest") != MODEL_DIGEST:
        raise ValueError("Pinned local model is absent or changed; no download permitted")
    unrelated = [m for m in metadata["loaded_before"].get("models", []) if m.get("name") != MODEL]
    if unrelated:
        raise RuntimeError("Another loaded model is using the inference service")
    if args.timing_mode == "cold":
        runtime.api("/api/generate", {"model": MODEL, "keep_alive": 0}, timeout=60)
    elif not metadata["loaded_before"].get("models"):
        raise RuntimeError("Warm measurement requires the already-loaded model")
    metadata.update(created_at_utc=utc(), manifest_sha256=sha(args.manifest), source_hashes=current,
                    source_manifest=packages, endpoint="127.0.0.1:11438", external_inference=False)
    write_json(output / "run-metadata.json", metadata)
    all_start = time.perf_counter()
    for index, package in enumerate(packages):
        if source_hashes() != current:
            raise RuntimeError("Code mutation during inference")
        timing_mode = "cold" if args.timing_mode == "cold" and index == 0 else "warm"
        record = process_package(package, args.run_id, output, timing_mode, args.split)
        with (output / "results.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_json(output / "completion.json", {"completed_at_utc": utc(), "packages": len(packages),
        "elapsed_s": time.perf_counter() - all_start, "predictions_sha256": sha(output / "results.jsonl"), "source_hashes": current})
    write_json(output / "progress.json", {"run_id": args.run_id, "completed": True, "packages": len(packages)})


if __name__ == "__main__":
    main()
