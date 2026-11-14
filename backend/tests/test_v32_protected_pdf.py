import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openpyxl import Workbook
from pypdf import PdfWriter

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Issue
from doccheck_backend.run_worker import StoredRun, _process, run_document_worker
from doccheck_backend.v32_processor import V32Processor


def _no_model(*_args, **_kwargs):
    pytest.fail("These synthetic files do not require model inference")


def _locked_pdf(password: str, algorithm: str = "RC4-128") -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password, algorithm=algorithm)
    writer.write(output)
    return output.getvalue()


def _native_inputs(contract: str, amount: str) -> tuple[bytes, bytes]:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "КФЗ"
    sheet["A3"] = f"Договор № {contract}"
    sheet["A4"] = "Период: 2031-02-01 — 2031-02-28. Этап 1."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    sheet["B7"], sheet["C7"] = "Общехозяйственные расходы", float(amount)
    sheet["A8"], sheet["C8"] = "Всего по отчету", "=SUM(C7:C7)"
    report = BytesIO()
    workbook.save(report)

    document = Document()
    document.add_paragraph("Акт № SYN-41")
    document.add_paragraph(f"Договор № {contract}")
    document.add_paragraph("Период: 2031-02-01 — 2031-02-28")
    document.add_paragraph("Общехозяйственные расходы.")
    document.add_paragraph(f"Итого: {amount} руб.")
    primary = BytesIO()
    document.save(primary)
    return report.getvalue(), primary.getvalue()


def _run(
    root: Path,
    report: tuple[str, bytes],
    primary: list[tuple[str, bytes]],
    *,
    explicit_scope: bool = False,
    fixed_ids: dict[str, str] | None = None,
):
    run_id = uuid4()
    run_dir = root / str(run_id)
    run_dir.mkdir(parents=True)
    documents = []
    for role, (name, contents) in [
        ("report", report),
        *(("supporting", item) for item in primary),
    ]:
        document_id = (fixed_ids or {}).get(name, uuid4().hex)
        (run_dir / document_id).write_bytes(contents)
        documents.append(
            {
                "id": document_id,
                "name": name,
                "format": Path(name).suffix.removeprefix("."),
                "role": role,
                "sha256": sha256(contents).hexdigest(),
                "size": len(contents),
            }
        )
    scope = None
    if explicit_scope:
        scope = {
            "report_document_id": documents[0]["id"],
            "contract_number": "TST-62",
            "period_start": "2031-02-01",
            "period_end": "2031-02-28",
            "report_row_locator": {"kind": "page", "page": 1, "fragment_id": "synthetic-row"},
        }
    return _process(StoredRun(run_id, scope, documents), root, V32Processor(_no_model, _no_model))


@pytest.mark.parametrize(
    ("contract", "amount", "protected_first", "algorithm"),
    [("TST-21", "93.15", True, "RC4-128"), ("TST-62", "128.60", False, "AES-256")],
)
def test_protected_primary_preserves_other_sources_and_unverified_rows(
    tmp_path, contract, amount, protected_first, algorithm
):
    report, readable = _native_inputs(contract, amount)
    source = ("act.docx", readable)
    locked = ("protected.pdf", _locked_pdf("synthetic-password-" + contract, algorithm))
    control = _run(tmp_path, ("report.xlsx", report), [source])
    primary = [locked, source] if protected_first else [source, locked]
    outcome = _run(tmp_path, ("report.xlsx", report), primary)

    assert control.status == "completed" and control.result is not None
    reference = next(row for row in control.result.rows if row.id == "general_admin")
    assert reference.status == "verified" and reference.observed_evidence_sum == amount
    assert outcome.status == "completed_with_issues" and outcome.result is not None
    document = next(item for item in outcome.result.documents if item.name == "protected.pdf")
    assert document.parse_status == "error" and document.decision.state == "parse_error"
    assert [error.code for error in document.errors] == ["encrypted_pdf"]
    assert "парол" in document.errors[0].message.lower()
    for row in outcome.result.rows:
        assert row.status == "unverified"
        assert row.expected_value is None and row.delta is None
        assert any(reason.code == "support_unreadable" for reason in row.reasons)
    row = next(row for row in outcome.result.rows if row.id == "general_admin")
    assert row.reported_value == amount and row.observed_evidence_sum == amount
    assert row.calculation is not None and len(row.calculation.components) == 1
    assert row.calculation.components[0].amount == amount
    readable_id = next(item.id for item in outcome.result.documents if item.name == "act.docx")
    assert any(
        item.document_id == readable_id and item.kind == "amount"
        for item in outcome.result.evidence
    )


@pytest.mark.parametrize("duplicate_first", [False, True])
def test_duplicate_protected_primary_is_excluded_and_marked_unreadable(tmp_path, duplicate_first):
    report, readable = _native_inputs("TST-62", "128.60")
    locked = _locked_pdf("synthetic-password-only", "AES-256")
    original = ("protected-a.pdf", locked)
    duplicate = ("protected-b.pdf", locked)
    primary = (
        [duplicate, ("act.docx", readable), original]
        if duplicate_first
        else [original, ("act.docx", readable), duplicate]
    )
    outcome = _run(
        tmp_path,
        ("report.xlsx", report),
        primary,
        fixed_ids={"protected-a.pdf": "a" * 32, "protected-b.pdf": "b" * 32},
    )

    assert outcome.status == "completed_with_issues" and outcome.result is not None
    originals = {doc.name: doc for doc in outcome.result.documents}
    representative = originals["protected-a.pdf"]
    copy = originals["protected-b.pdf"]
    assert representative.parse_status == copy.parse_status == "error"
    assert [error.code for error in representative.errors] == ["encrypted_pdf"]
    assert [error.code for error in copy.errors] == ["encrypted_pdf"]
    assert "парол" in copy.errors[0].message.lower()
    assert representative.errors[0].id != copy.errors[0].id
    assert copy.duplicate_of == representative.id
    assert copy.decision.state == "exclude" and copy.decision.reason_code == "byte_duplicate"
    row = next(row for row in outcome.result.rows if row.id == "general_admin")
    assert row.status == "unverified" and row.expected_value is None and row.delta is None
    assert row.observed_evidence_sum == "128.60"
    assert row.calculation is not None and len(row.calculation.components) == 1

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/check-result.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(outcome.model_dump(mode="json"))


@pytest.mark.parametrize(("explicit_scope", "algorithm"), [(False, "RC4-128"), (True, "AES-256")])
def test_protected_report_fails_with_safe_specific_error(tmp_path, explicit_scope, algorithm):
    password = "synthetic-password-TST-62"
    _, readable = _native_inputs("TST-62", "128.60")
    outcome = _run(
        tmp_path,
        ("report.pdf", _locked_pdf(password, algorithm)),
        [("act.docx", readable)],
        explicit_scope=explicit_scope,
    )

    assert outcome.status == "failed" and outcome.result is None
    assert outcome.error is not None and outcome.error.code == "encrypted_pdf"
    assert "парол" in outcome.error.message.lower()
    assert password not in outcome.error.message


def test_worker_sanitizes_protected_report_error_details(tmp_path):
    run_id = uuid4()
    run = StoredRun(
        run_id,
        None,
        [{"id": uuid4().hex, "role": "report", "format": "pdf", "sha256": "0" * 64}],
    )
    sensitive_detail = "synthetic-exception-detail"

    def processor(stored, _directory):
        return CheckJob(
            run_id=str(stored.id),
            status="failed",
            result=None,
            error=Issue(code="encrypted_pdf", message=sensitive_detail),
        )

    outcome = _process(run, tmp_path, processor)
    assert outcome.error is not None and outcome.error.code == "encrypted_pdf"
    assert "парол" in outcome.error.message.lower()
    assert sensitive_detail not in outcome.model_dump_json()


@pytest.mark.parametrize("protected_report", [False, True])
def test_worker_persists_protected_pdf_outcome_and_readable_original(
    database_url, tmp_path, protected_report
):
    password = "synthetic-password-only"
    report, readable = _native_inputs("TST-62", "128.60")
    locked = _locked_pdf(password, "AES-256")
    report_file = ("report.pdf", locked) if protected_report else ("report.xlsx", report)
    documents = [("act.docx", readable)]
    if not protected_report:
        documents.extend([("protected-a.pdf", locked), ("protected-b.pdf", locked)])
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(uuid4())},
            files=[
                ("report", report_file),
                *(("documents", item) for item in documents),
            ],
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
        assert password not in state.text and password not in findings.text
        if protected_report:
            assert state.json()["status"] == "failed"
            assert state.json()["error"]["code"] == "encrypted_pdf"
            assert "парол" in state.json()["error"]["message"].lower()
            assert findings.status_code == 409 and findings.json()["code"] == "run_failed"
        else:
            assert state.json()["status"] == "completed_with_issues"
            assert findings.status_code == 200
            result = findings.json()
            protected = [
                item for item in result["documents"] if item["name"].startswith("protected-")
            ]
            assert len(protected) == 2
            assert all(item["parse_status"] == "error" for item in protected)
            assert all(item["errors"][0]["code"] == "encrypted_pdf" for item in protected)
            copy = next(item for item in protected if item["duplicate_of"] is not None)
            representative = next(item for item in protected if item["duplicate_of"] is None)
            assert copy["duplicate_of"] == representative["id"]
            assert copy["decision"]["state"] == "exclude"
            assert copy["decision"]["reason_code"] == "byte_duplicate"
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            assert row["status"] == "unverified" and row["delta"] is None
            assert row["observed_evidence_sum"] == "128.60"
            source = next(item for item in result["documents"] if item["name"] == "act.docx")
            original = client.get(f"/api/v0/runs/{run_id}/documents/{source['id']}")
            assert original.status_code == 200 and original.content == readable
