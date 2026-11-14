import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pypdfium2 as pdfium
import pytest
import test_v32_protected_pdf as protected_helpers
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image
from pypdf import PdfWriter
from test_native_pdf import _write_pdf
from test_v32_protected_pdf import _native_inputs, _no_model, _run

from doccheck_backend import grounded_amounts
from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.page_ocr import OcrLine
from doccheck_backend.run_worker import run_document_worker
from doccheck_backend.v32_processor import V32Processor, _model_input, _pdf_issue


def _pdf(variant: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    output = BytesIO()
    writer.write(output)
    raw = output.getvalue()
    if variant == "header-only":
        return b"%PDF-1.7\n%%EOF\n"
    if variant == "half":
        return raw[: len(raw) // 2]
    if variant == "tail":
        return raw[:-40]
    if variant == "xref":
        return raw.replace(b"xref\n", b"xxxx\n", 1)
    if variant == "root":
        broken = raw.replace(b"/Root 3 0 R", b"/Root 9 0 R", 1)
        assert broken != raw
        return broken
    raise ValueError("unknown synthetic PDF variant")


def _validate_schema(job):
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/check-result.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(job.model_dump(mode="json"))


@pytest.mark.parametrize("variant", ["header-only", "half", "tail", "xref", "root"])
def test_unreadable_primary_preserves_other_sources_and_partial_value(tmp_path, variant):
    report, readable = _native_inputs("TST-62", "128.60")
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        [("act.docx", readable), ("broken.pdf", _pdf(variant))],
    )

    assert outcome.status == "completed_with_issues" and outcome.result is not None
    broken = next(item for item in outcome.result.documents if item.name == "broken.pdf")
    assert broken.parse_status == "error" and broken.decision.state == "parse_error"
    assert [error.code for error in broken.errors] == ["pdf_unreadable"]
    assert "PDF" in broken.errors[0].message
    row = next(item for item in outcome.result.rows if item.id == "general_admin")
    assert row.status == "unverified" and row.expected_value is None and row.delta is None
    assert row.observed_evidence_sum == "128.60"
    assert row.calculation is not None and len(row.calculation.components) == 1
    readable_id = next(item.id for item in outcome.result.documents if item.name == "act.docx")
    assert any(item.document_id == readable_id for item in outcome.result.evidence)
    _validate_schema(outcome)


@pytest.mark.parametrize("duplicate_first", [False, True])
def test_duplicate_unreadable_pdf_keeps_exclusion_and_both_errors(tmp_path, duplicate_first):
    report, readable = _native_inputs("TST-62", "128.60")
    broken = _pdf("half")
    original = ("broken-a.pdf", broken)
    duplicate = ("broken-b.pdf", broken)
    primary = (
        [duplicate, ("act.docx", readable), original]
        if duplicate_first
        else [original, ("act.docx", readable), duplicate]
    )
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        primary,
        fixed_ids={"broken-a.pdf": "a" * 32, "broken-b.pdf": "b" * 32},
    )
    assert outcome.status == "completed_with_issues" and outcome.result is not None
    documents = {item.name: item for item in outcome.result.documents}
    representative, copy = documents["broken-a.pdf"], documents["broken-b.pdf"]
    assert representative.parse_status == copy.parse_status == "error"
    assert representative.errors[0].code == copy.errors[0].code == "pdf_unreadable"
    assert representative.errors[0].id != copy.errors[0].id
    assert copy.duplicate_of == representative.id
    assert copy.decision.state == "exclude" and copy.decision.reason_code == "byte_duplicate"
    row = next(item for item in outcome.result.rows if item.id == "general_admin")
    assert row.status == "unverified" and row.expected_value is None and row.delta is None
    assert row.observed_evidence_sum == "128.60"
    _validate_schema(outcome)


@pytest.mark.parametrize("variant", ["half", "xref", "root"])
@pytest.mark.parametrize("explicit_scope", [False, True])
def test_unreadable_report_fails_without_result(tmp_path, variant, explicit_scope):
    _, readable = _native_inputs("TST-62", "128.60")
    outcome = _run(
        tmp_path,
        ("report.pdf", _pdf(variant)),
        [("act.docx", readable)],
        explicit_scope=explicit_scope,
    )
    assert outcome.status == "failed" and outcome.result is None
    assert outcome.error is not None and outcome.error.code == "pdf_unreadable"
    assert "КФЗ" in outcome.error.message and "PDF" in outcome.error.message
    _validate_schema(outcome)


def test_valid_native_and_scanned_pdf_are_still_readable(tmp_path):
    native = _write_pdf(
        tmp_path / "native.pdf",
        [b"BT /F1 8 Tf 20 140 Td (Synthetic native document with fields for testing) Tj ET"],
    )
    assert _pdf_issue(native) is None
    text, images = _model_input(native)
    assert text is not None and "Synthetic native document" in text and images == []

    scan = tmp_path / "scan.pdf"
    Image.new("RGB", (200, 300), "white").save(scan, "PDF")
    assert _pdf_issue(scan) is None
    text, images = _model_input(scan)
    assert text is None and len(images) == 1 and images[0].is_file()


def test_unprotected_native_pdf_is_not_marked_unreadable(tmp_path):
    report, readable = _native_inputs("TST-62", "128.60")
    native = _write_pdf(
        tmp_path / "native.pdf",
        [b"BT /F1 8 Tf 20 140 Td (Synthetic native document with fields for testing) Tj ET"],
    )
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        [("act.docx", readable), ("native.pdf", native.read_bytes())],
    )
    assert outcome.result is not None
    document = next(item for item in outcome.result.documents if item.name == "native.pdf")
    assert document.parse_status == "parsed" and document.errors == []


def test_pdf_with_empty_user_password_remains_readable(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("", owner_password="synthetic-owner", algorithm="AES-256")
    path = tmp_path / "owner-protection.pdf"
    writer.write(path)
    assert _pdf_issue(path) is None


def test_valid_scanned_primary_reaches_processing_with_mocked_ocr_and_model(monkeypatch, tmp_path):
    report, readable = _native_inputs("TST-62", "128.60")
    buffer = BytesIO()
    Image.new("RGB", (200, 300), "white").save(buffer, "PDF")
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _image: [OcrLine("Синтетический документ", (10, 10, 100, 30), 99)],
    )
    seen = []

    def read_number(image):
        seen.append(image)
        return {
            "adapter_sha256": "a" * 64,
            "model_sha256": "b" * 64,
            "policy_sha256": "c" * 64,
            "prediction": {"doc_number": "SYN-99", "verbatim_line": "Акт № SYN-99"},
        }

    monkeypatch.setattr(protected_helpers, "_no_model", read_number)
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        [("act.docx", readable), ("scan.pdf", buffer.getvalue())],
    )
    assert outcome.result is not None and len(seen) == 1
    scan = next(item for item in outcome.result.documents if item.name == "scan.pdf")
    assert scan.parse_status == "parsed" and scan.errors == []


def test_unexpected_model_failure_remains_a_job_failure(monkeypatch, tmp_path):
    report, readable = _native_inputs("TST-62", "128.60")
    buffer = BytesIO()
    Image.new("RGB", (200, 300), "white").save(buffer, "PDF")
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _image: [OcrLine("Синтетический документ", (10, 10, 100, 30), 99)],
    )

    def model_failure(*_args, **_kwargs):
        raise RuntimeError("synthetic model detail")

    monkeypatch.setattr(protected_helpers, "_no_model", model_failure)
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        [("act.docx", readable), ("scan.pdf", buffer.getvalue())],
    )
    assert outcome.status == "failed" and outcome.result is None
    assert outcome.error is not None and outcome.error.code == "processing_failed"
    assert "synthetic model detail" not in outcome.error.message


@pytest.mark.parametrize("failure", ["pdfium_unknown", "program_error"])
def test_unexpected_pdf_probe_failure_is_not_reported_as_bad_file(monkeypatch, tmp_path, failure):
    report, readable = _native_inputs("TST-62", "128.60")
    valid = _pdf("root").replace(b"/Root 9 0 R", b"/Root 3 0 R", 1)

    def unexpected(*_args, **_kwargs):
        if failure == "pdfium_unknown":
            raise pdfium.PdfiumError("synthetic internal detail", err_code=1)
        raise ValueError("synthetic internal detail")

    monkeypatch.setattr(pdfium, "PdfDocument", unexpected)
    outcome = _run(
        tmp_path, ("report.xlsx", report), [("act.docx", readable), ("valid.pdf", valid)]
    )
    assert outcome.status == "failed" and outcome.result is None
    assert outcome.error is not None and outcome.error.code == "processing_failed"
    assert "synthetic internal detail" not in outcome.error.message


def test_worker_accepts_valid_scanned_pdf_with_mocked_ocr_and_model(
    database_url, monkeypatch, tmp_path
):
    report, readable = _native_inputs("TST-62", "128.60")
    scan = BytesIO()
    Image.new("RGB", (200, 300), "white").save(scan, "PDF")
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _image: [OcrLine("Синтетический документ", (10, 10, 100, 30), 99)],
    )
    seen = []

    def read_number(image):
        seen.append(image)
        return {
            "adapter_sha256": "a" * 64,
            "model_sha256": "b" * 64,
            "policy_sha256": "c" * 64,
            "prediction": {"doc_number": "SYN-99", "verbatim_line": "Акт № SYN-99"},
        }

    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(uuid4())},
            files=[
                ("report", ("report.xlsx", report)),
                ("documents", ("act.docx", readable)),
                ("documents", ("scan.pdf", scan.getvalue())),
            ],
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(_no_model, read_number),
            once=True,
        )
        findings = client.get(f"/api/v0/runs/{run_id}/findings")
        assert findings.status_code == 200 and len(seen) == 1
        document = next(item for item in findings.json()["documents"] if item["name"] == "scan.pdf")
        assert document["parse_status"] == "parsed" and document["errors"] == []


@pytest.mark.parametrize("broken_report", [False, True])
def test_worker_and_api_preserve_corrupt_pdf_outcome(database_url, tmp_path, broken_report):
    report, readable = _native_inputs("TST-62", "128.60")
    broken = _pdf("half")
    report_file = ("broken-report.pdf", broken) if broken_report else ("report.xlsx", report)
    documents = [("act.docx", readable)]
    if not broken_report:
        documents.extend([("broken-a.pdf", broken), ("broken-b.pdf", broken)])
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(uuid4())},
            files=[("report", report_file), *(("documents", item) for item in documents)],
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(_no_model, _no_model),
            once=True,
        )
        state = client.get(f"/api/v0/runs/{run_id}")
        findings = client.get(f"/api/v0/runs/{run_id}/findings")
        if broken_report:
            assert state.json()["status"] == "failed"
            assert state.json()["error"]["code"] == "pdf_unreadable"
            assert findings.status_code == 409 and findings.json()["code"] == "run_failed"
        else:
            assert state.json()["status"] == "completed_with_issues"
            assert findings.status_code == 200
            result = findings.json()
            documents = [item for item in result["documents"] if item["name"].startswith("broken-")]
            assert len(documents) == 2
            assert all(item["parse_status"] == "error" for item in documents)
            assert all(item["errors"][0]["code"] == "pdf_unreadable" for item in documents)
            copy = next(item for item in documents if item["duplicate_of"] is not None)
            assert copy["decision"]["state"] == "exclude"
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            assert row["status"] == "unverified" and row["delta"] is None
            assert row["observed_evidence_sum"] == "128.60"
            source = next(item for item in result["documents"] if item["name"] == "act.docx")
            original = client.get(f"/api/v0/runs/{run_id}/documents/{source['id']}")
            assert original.status_code == 200 and original.content == readable
