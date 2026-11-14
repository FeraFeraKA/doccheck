"""Contract smoke tests for v3.2 using native files and a stub for Ollama HTTP."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from openpyxl import Workbook

from doccheck_backend.run_worker import StoredRun
from doccheck_backend.v32_adapter import process

_TEST_MODEL_DIGEST = "d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04"


@pytest.fixture
def uploaded_files(tmp_path):
    report_id, act_id = uuid4().hex, uuid4().hex
    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = "Договор № E2E-31"
    sheet["A4"] = "Период: 2027-02-01 — 2027-03-31. Этап 2."
    sheet["B6"] = "Статья затрат"
    sheet["C6"] = "Отчетная сумма, руб."
    sheet["B7"] = "Общехозяйственные расходы"
    sheet["C7"] = 1250.50
    sheet["A8"] = "Всего по отчету"
    sheet["C8"] = "=SUM(C7:C7)"
    book.save(tmp_path / report_id)

    act = Document()
    for text in [
        "Акт оказанных услуг № ACT-31 от 28.02.2027",
        "Расходы отнесены к общехозяйственным расходам.",
        "Период оказания услуг: с 01.02.2027 по 28.02.2027.",
        "Договор № E2E-31.",
        "Итого стоимость услуг: 1 172,70 руб.",
    ]:
        act.add_paragraph(text)
    act.save(tmp_path / act_id)

    def metadata(file_id, name, format_, role):
        return {
            "id": file_id,
            "name": name,
            "format": format_,
            "role": role,
            "sha256": sha256((tmp_path / file_id).read_bytes()).hexdigest(),
        }

    return [
        metadata(report_id, "report.xlsx", "xlsx", "report"),
        metadata(act_id, "act.docx", "docx", "supporting"),
    ]


def _stub_ollama(monkeypatch, amount):
    monkeypatch.syspath_prepend(Path(__file__).resolve().parents[2])
    from bench.e2e_v32_20261114 import run as v32

    calls = []

    def request(path, body=None, timeout=600):
        calls.append(path)
        if path == "/api/tags":
            return {
                "models": [
                    {
                        "name": v32.MODEL,
                        "digest": _TEST_MODEL_DIGEST,
                    }
                ]
            }
        if path == "/api/ps":
            return {"models": []}
        assert path == "/api/chat"
        assert "E2E-31" in body["messages"][0]["content"]
        response = {
            "doc_number": "ACT-31",
            "contract_number": "E2E-31",
            "date": "2027-02-28",
            "period_start": "2027-02-01",
            "period_end": "2027-02-28",
            "amount": amount,
            "category": "general_admin",
            "description": "Общехозяйственные услуги",
            "evidence_quote": "Итого стоимость услуг: 1 172,70 руб.",
        }
        return {"message": {"content": json.dumps(response, ensure_ascii=False)}}

    monkeypatch.setattr(v32.runtime, "api", request)
    return calls


def test_worker_adapter_infers_scope_and_anchors_partial_sum(uploaded_files, tmp_path, monkeypatch):
    calls = _stub_ollama(monkeypatch, "1172.70")
    run = StoredRun(uuid4(), None, uploaded_files)
    job = process(run, tmp_path)

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert job.status == "completed"
    result = job.result
    assert result.run_id == str(run.id)
    assert result.synthetic is False
    assert result.scope.contract_number == "E2E-31"
    assert result.scope.period_end == "2027-03-31"
    (row,) = result.rows
    assert (row.status, row.reported_value, row.observed_evidence_sum) == (
        "unverified",
        "1250.50",
        "1172.70",
    )
    assert row.expected_value is None and row.delta is None
    evidence = {item.kind: item for item in result.evidence}
    assert evidence["amount"].document_id == uploaded_files[1]["id"]
    assert evidence["amount"].locator.paragraph == 5
    assert evidence["contract"].locator.paragraph == 4
    assert evidence["period"].locator.paragraph == 3
    assert evidence["article"].locator.paragraph == 2
    assert evidence["reported_value"].locator.range == "C7"
    assert all((tmp_path / f["id"]).is_file() for f in uploaded_files)


def test_unsupported_model_amount_stays_unknown(uploaded_files, tmp_path, monkeypatch):
    _stub_ollama(monkeypatch, "1172.00")
    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result

    (row,) = result.rows
    assert row.observed_evidence_sum is None
    assert row.expected_value is None
    assert row.status == "unverified"
    assert result.documents[1].decision.state == "needs_review"


def test_corrupt_primary_reports_technical_issue(uploaded_files, tmp_path, monkeypatch):
    calls = _stub_ollama(monkeypatch, "1172.70")
    Path(tmp_path / uploaded_files[1]["id"]).write_bytes(b"malformed")
    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)
    assert calls == ["/api/tags"]
    assert job.status == "completed_with_issues"
    assert job.result.documents[1].errors
    assert job.result.rows[0].observed_evidence_sum is None


def test_multiple_document_totals_are_not_admitted(uploaded_files, tmp_path, monkeypatch):
    _stub_ollama(monkeypatch, "1172.70")
    primary = uploaded_files[1]
    path = tmp_path / primary["id"]
    act = Document(path)
    act.add_paragraph("Итого: 3 000,00 руб.")
    act.save(path)
    primary["sha256"] = sha256(path.read_bytes()).hexdigest()

    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result
    assert result.rows[0].observed_evidence_sum is None
    assert result.documents[1].decision.state == "needs_review"
