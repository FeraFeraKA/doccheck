"""Contract smoke tests for v3.2 using native files and a stub for Ollama HTTP."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook, load_workbook

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


def test_identity_conflict_removes_candidate_sum(uploaded_files, tmp_path, monkeypatch):
    path = tmp_path / uploaded_files[1]["id"]
    copy_id = uuid4().hex
    copy_path = tmp_path / copy_id
    act = Document(path)
    act.paragraphs[4].text = "Итого стоимость услуг: 1 050,70 руб."
    act.save(copy_path)
    uploaded_files.append(
        {
            **uploaded_files[1],
            "id": copy_id,
            "name": "changed-act.docx",
            "sha256": sha256(copy_path.read_bytes()).hexdigest(),
        }
    )
    calls = _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    request = v32.runtime.api

    def differing_totals(path, body=None, timeout=600):
        response = request(path, body, timeout)
        if path == "/api/chat" and "1 050,70" in body["messages"][0]["content"]:
            payload = json.loads(response["message"]["content"])
            payload["amount"] = "1050.70"
            response["message"]["content"] = json.dumps(payload)
        return response

    monkeypatch.setattr(v32.runtime, "api", differing_totals)
    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result

    assert calls.count("/api/chat") == 2
    assert result.rows[0].observed_evidence_sum is None
    assert any(reason.code == "source_identity_conflict" for reason in result.rows[0].reasons)
    assert all(
        file.decision.reason_code == "source_identity_conflict" for file in result.documents[1:]
    )


@pytest.mark.parametrize(
    ("cell", "formula", "invalid"),
    [
        ("C7", None, True),
        ("D7", "=D7", True),
        ("D7", "=SUM(D7:D7)", "#DIV/0!"),
        ("C7", None, date(2027, 2, 1)),
        ("D7", "=SUM(D7:D7)", date(2027, 2, 1)),
    ],
)
def test_xlsx_nonmoney_cells_are_rejected(
    uploaded_files, tmp_path, monkeypatch, cell, formula, invalid
):
    calls = _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    with path.open("rb") as source:
        book = load_workbook(source)
    book.active[cell] = invalid
    if formula:
        book.active["C7"] = formula
    book.save(path)
    report["sha256"] = sha256(path.read_bytes()).hexdigest()

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)
    assert calls == ["/api/tags"]
    assert job.status == "failed" and job.result is None


@pytest.mark.parametrize(
    ("line", "extra"),
    [
        (
            "Итого оплачено ранее: 1 172,70 руб.",
            "Стоимость оказанных в этом периоде услуг: 2 304,00 руб.",
        ),
        ("Итого стоимость услуг: 1 172,70 руб.", "Итого с НДС: 1 300,00 руб., НДС 127,30 руб."),
        ("Итого стоимость услуг: 1 172,70 руб.", "К оплате за оказанные услуги: 1 407,24 руб."),
        (
            "Всего без НДС: 1 172,70 руб.",
            "Итого с НДС: 1 300,00 руб., НДС 127,30 руб.",
        ),
    ],
)
def test_unbound_or_ambiguous_service_total_remains_unknown(
    uploaded_files, tmp_path, monkeypatch, line, extra
):
    _stub_ollama(monkeypatch, "1172.70")
    primary = uploaded_files[1]
    path = tmp_path / primary["id"]
    act = Document(path)
    act.paragraphs[4].text = line
    act.add_paragraph(extra)
    act.save(path)
    primary["sha256"] = sha256(path.read_bytes()).hexdigest()
    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result
    assert result.rows[0].observed_evidence_sum is None
    assert result.documents[1].decision.state == "needs_review"


@pytest.mark.parametrize(
    ("reverse", "different_totals"), [(False, False), (False, True), (True, True)]
)
def test_same_native_identity_is_quarantined_before_model_dedup(
    uploaded_files, tmp_path, monkeypatch, reverse, different_totals
):
    original = uploaded_files[1]
    clone_id = uuid4().hex
    path = tmp_path / clone_id
    act = Document(tmp_path / original["id"])
    act.add_paragraph("Изменённое примечание.")
    if different_totals:
        act.paragraphs[4].text = "Итого стоимость услуг: 1 050,70 руб."
    act.save(path)
    uploaded_files.append(
        {
            **original,
            "id": clone_id,
            "name": "other.docx",
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
    )
    if reverse:
        uploaded_files[1:] = uploaded_files[:0:-1]
    calls = _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    request = v32.runtime.api

    def model_disagrees_on_issuer(path, body=None, timeout=600):
        response = request(path, body, timeout)
        if path == "/api/chat" and not different_totals:
            payload = json.loads(response["message"]["content"])
            payload["counterparty"] = str(calls.count("/api/chat"))
            response["message"]["content"] = json.dumps(payload)
        return response

    monkeypatch.setattr(v32.runtime, "api", model_disagrees_on_issuer)
    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result
    assert calls.count("/api/chat") == 2
    assert result.rows[0].observed_evidence_sum is None
    assert all(
        file.decision.reason_code == "source_identity_conflict" for file in result.documents[1:]
    )


def test_partial_native_read_reports_file_error(uploaded_files, tmp_path, monkeypatch):
    calls = _stub_ollama(monkeypatch, "1172.70")
    primary = uploaded_files[1]
    path = tmp_path / primary["id"]
    act = Document(path)
    table = act.add_table(rows=1, cols=1)
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    grid_before = OxmlElement("w:gridBefore")
    grid_before.set(qn("w:val"), "malformed")
    tr_pr.append(grid_before)
    act.save(path)
    primary["sha256"] = sha256(path.read_bytes()).hexdigest()

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)
    assert calls == ["/api/tags"]
    assert job.status == "completed_with_issues"
    assert job.result.documents[1].decision.state == "parse_error"
    assert job.result.documents[1].errors
    assert job.result.rows[0].observed_evidence_sum is None


def test_xlsx_currency_style_preserves_money(uploaded_files, tmp_path, monkeypatch):
    _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    with path.open("rb") as source:
        book = load_workbook(source)
    book.active["C7"].number_format = '#,##0.00 "₽"'
    book.save(path)
    report["sha256"] = sha256(path.read_bytes()).hexdigest()

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)
    assert job.status == "completed"
    assert job.result.rows[0].reported_value == "1250.50"


@pytest.mark.parametrize("reverse", [False, True])
def test_native_collision_survives_one_model_timeout(
    uploaded_files, tmp_path, monkeypatch, reverse
):
    original = uploaded_files[1]
    clone_id = uuid4().hex
    path = tmp_path / clone_id
    act = Document(tmp_path / original["id"])
    act.paragraphs[4].text = "Итого стоимость услуг: 1 050,70 руб."
    act.save(path)
    uploaded_files.append(
        {
            **original,
            "id": clone_id,
            "name": "conflicting-act.docx",
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
    )
    if reverse:
        uploaded_files[1:] = uploaded_files[:0:-1]
    _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    request = v32.runtime.api

    def timeout_on_conflicting_act(path, body=None, timeout=600):
        if path == "/api/chat" and "1 050,70" in body["messages"][0]["content"]:
            raise TimeoutError("synthetic model timeout")
        return request(path, body, timeout)

    monkeypatch.setattr(v32.runtime, "api", timeout_on_conflicting_act)

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)
    assert job.status == "completed_with_issues"
    assert job.result.rows[0].observed_evidence_sum is None
    by_id = {document.id: document for document in job.result.documents}
    assert by_id[clone_id].errors
    assert by_id[original["id"]].decision.reason_code == "source_identity_conflict"


def _replace_primary(uploaded_files, tmp_path, format_):
    path = tmp_path / uploaded_files[1]["id"]
    uploaded_files[1].update(
        format=format_,
        name=f"support.{format_}",
        sha256=sha256(path.read_bytes()).hexdigest(),
    )


def test_xlsx_primary_anchors_known_total_and_month(uploaded_files, tmp_path, monkeypatch):
    calls = _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    report = uploaded_files[0]
    report_path = tmp_path / report["id"]
    with report_path.open("rb") as source:
        book = load_workbook(source)
    book.active["B7"] = "Оплата труда"
    book.save(report_path)
    report["sha256"] = sha256(report_path.read_bytes()).hexdigest()

    book = Workbook()
    sheet = book.active
    sheet.title = "Ведомость"
    entries = {
        "A1": "Расчетная ведомость по оплате труда",
        "A2": "Документ: ACT-31",
        "A3": "Проект: E2E-31 | Период: Февраль 2027",
        "A5": "Код статьи",
        "B5": "Вид начисления",
        "C5": "Сумма, руб.",
        "C6": 750.25,
        "C7": 422.45,
        "B8": "Итого",
        "C8": "=SUM(C6:C7)",
    }
    for cell, value in entries.items():
        sheet[cell] = value
    book.save(tmp_path / uploaded_files[1]["id"])
    _replace_primary(uploaded_files, tmp_path, "xlsx")
    request = v32.runtime.api

    def predict_payroll(path, body=None, timeout=600):
        response = request(path, body, timeout)
        if path == "/api/chat":
            payload = json.loads(response["message"]["content"])
            payload["category"] = "payroll"
            response["message"]["content"] = json.dumps(payload)
        return response

    monkeypatch.setattr(v32.runtime, "api", predict_payroll)
    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert result.rows[0].observed_evidence_sum == "1172.70"
    evidence = {item.kind: item for item in result.evidence}
    assert evidence["amount"].locator.range == "C8"
    assert evidence["period"].locator.range == "A3"
    assert evidence["period"].normalized_value.end == "2027-02-28"


def test_raster_pdf_report_requires_addressed_scope(uploaded_files, tmp_path, monkeypatch):
    from test_native_pdf import _write_pdf

    calls = _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    _write_pdf(path, [b"0 0 10 10 re f"])
    report.update(format="pdf", name="report.pdf", sha256=sha256(path.read_bytes()).hexdigest())

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert calls == ["/api/tags"]
    assert job.status == "failed"
    assert job.error.code == "v32_pdf_scope_unavailable"
    assert job.result is None


def test_png_model_quote_never_becomes_source_address(uploaded_files, tmp_path, monkeypatch):
    from PIL import Image

    calls = _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    Image.new("RGB", (30, 30), "white").save(tmp_path / uploaded_files[1]["id"], "PNG")
    _replace_primary(uploaded_files, tmp_path, "png")
    request = v32.runtime.api

    def predict_scan(path, body=None, timeout=600):
        if path == "/api/chat":
            assert body["messages"][0]["images"]
            body["messages"][0]["content"] += "E2E-31"
        return request(path, body, timeout)

    monkeypatch.setattr(v32.runtime, "api", predict_scan)
    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert job.status == "completed"
    assert job.result.documents[1].decision.state == "needs_review"
    assert job.result.rows[0].observed_evidence_sum is None
    assert all(item.document_id != uploaded_files[1]["id"] for item in job.result.evidence)


def test_native_pdf_kfz_binds_report_and_retains_docx_primary(
    uploaded_files, tmp_path, monkeypatch
):
    from doccheck_backend.contracts.locators import PageLocator
    from doccheck_backend.native_observations import NativeDocument, Observation
    from doccheck_backend.v32_adapter import read_native_document

    calls = _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    path.write_bytes(b"%PDF-1.4 input addressed by stubbed native reader")
    report.update(format="pdf", name="report.pdf", sha256=sha256(path.read_bytes()).hexdigest())

    # The native PDF reader and rendering are tested independently against real PDF
    # files. Here only its addressed observations and the model response are injected.
    observations = NativeDocument(
        observations=tuple(
            Observation(text, PageLocator(kind="page", page=1, line=index))
            for index, text in enumerate(
                [
                    "Договор № E2E-31.",
                    "Период: 2027-02-01 — 2027-03-31.",
                    "Общехозяйственные расходы: 1 250,50 руб.",
                ],
                1,
            )
        )
    )

    def read(path, kind):
        return observations if kind == "pdf" else read_native_document(path, kind)

    monkeypatch.setattr("doccheck_backend.v32_adapter.read_native_document", read)
    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert job.status == "completed"
    assert job.result.scope.period_end == "2027-03-31"
    (row,) = job.result.rows
    assert (row.reported_value, row.observed_evidence_sum) == ("1250.50", "1172.70")
    source = next(item for item in job.result.evidence if item.kind == "reported_value")
    assert source.locator.line == 3
    assert source.document_id == report["id"]


def _write_text_pdf(path, lines):
    from test_native_pdf import _write_pdf

    codes = {character: code for code, character in enumerate(sorted(set("".join(lines))), 32)}
    text = (
        b"BT /F1 7 Tf 10 180 Td "
        + b" 0 -14 Td ".join(
            b"<" + bytes(codes[character] for character in line).hex().encode() + b"> Tj"
            for line in lines
        )
        + b" ET"
    )
    mapping = "\n".join(f"<{code:02x}> <{ord(character):04x}>" for character, code in codes.items())
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /TestUCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<00> <ff>\nendcodespacerange\n"
        f"{len(codes)} beginbfchar\n{mapping}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode()
    _write_pdf(path, [text], cmap=cmap)


@pytest.mark.parametrize("duplicate", [False, True])
def test_pdf_report_requires_exact_unambiguous_row_labels(
    uploaded_files, tmp_path, monkeypatch, duplicate
):
    _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    extra = "Оплата труда" if duplicate else "Оплата труда подрядчиков"
    _write_text_pdf(
        path,
        [
            "Договор № E2E-31.",
            "Период: 2027-02-01 — 2027-03-31.",
            "Общехозяйственные расходы: 1 250,50 руб.",
            "Оплата труда: 300,12 руб.",
            f"{extra}: 400,12 руб.",
        ],
    )
    report.update(format="pdf", name="report.pdf", sha256=sha256(path.read_bytes()).hexdigest())

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    if duplicate:
        assert job.status == "failed" and job.result is None
        assert job.error.code == "v32_pdf_scope_ambiguous"
    else:
        assert job.status == "completed"
        by_label = {row.label: row for row in job.result.rows}
        assert by_label["Оплата труда"].reported_value == "300.12"


def _stub_xlsx_prediction(monkeypatch, amount, category):
    calls = _stub_ollama(monkeypatch, amount)
    from bench.e2e_v32_20261114 import run as v32

    request = v32.runtime.api

    def predict(path, body=None, timeout=600):
        response = request(path, body, timeout)
        if path == "/api/chat":
            payload = json.loads(response["message"]["content"])
            payload["category"] = category
            response["message"]["content"] = json.dumps(payload)
        return response

    monkeypatch.setattr(v32.runtime, "api", predict)
    return calls


def _set_report_article(uploaded_files, tmp_path, label):
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    with path.open("rb") as source:
        book = load_workbook(source)
    book.active["B7"] = label
    book.save(path)
    report["sha256"] = sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("in_formula", [False, True])
def test_xlsx_primary_date_is_not_money(uploaded_files, tmp_path, monkeypatch, in_formula):
    _set_report_article(
        uploaded_files, tmp_path, "Оплата труда" if in_formula else "Страховые взносы"
    )
    book = Workbook()
    sheet = book.active
    sheet["A2"] = "Документ: ACT-31"
    sheet["A3"] = "Проект: E2E-31 | Период: Февраль 2027"
    if in_formula:
        sheet["A1"] = "Расчетная ведомость по оплате труда"
        sheet["A5"], sheet["B5"], sheet["C5"] = "Код статьи", "Вид начисления", "Сумма, руб."
        sheet["C6"], sheet["C7"] = date(2027, 2, 28), 10
        sheet["B8"], sheet["C8"] = "Итого", "=SUM(C6:C7)"
        _stub_xlsx_prediction(monkeypatch, "46456.00", "payroll")
    else:
        sheet["A1"] = "Расчет страховых взносов"
        sheet["A5"], sheet["B5"], sheet["C5"] = (
            "База начислений, руб.",
            "Начислено взносов, руб.",
            "Код статьи",
        )
        sheet["B6"] = date(2027, 2, 28)
        _stub_xlsx_prediction(monkeypatch, "46446.00", "insurance")
    book.save(tmp_path / uploaded_files[1]["id"])
    _replace_primary(uploaded_files, tmp_path, "xlsx")

    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result

    assert result is not None
    assert result.rows[0].observed_evidence_sum is None
    assert result.documents[1].decision.state != "include"


def test_xlsx_primary_formula_cache_conflict_requires_review(uploaded_files, tmp_path, monkeypatch):
    _set_report_article(uploaded_files, tmp_path, "Оплата труда")
    _stub_xlsx_prediction(monkeypatch, "1172.70", "payroll")
    book = Workbook()
    sheet = book.active
    for cell, value in {
        "A1": "Расчётная ведомость по оплате труда",
        "A2": "Документ: ACT-31",
        "A3": "Проект: E2E-31 | Период: Февраль 2027",
        "A5": "Код статьи",
        "B5": "Вид начисления",
        "C5": "Сумма, руб.",
        "C6": 750.25,
        "C7": 422.45,
        "B8": "Итого",
        "C8": "=SUM(C6:C7)",
    }.items():
        sheet[cell] = value
    fresh = tmp_path / "fresh.xlsx"
    book.save(fresh)
    with ZipFile(fresh) as before, ZipFile(tmp_path / uploaded_files[1]["id"], "w") as after:
        for member in before.infolist():
            data = before.read(member)
            if member.filename == "xl/worksheets/sheet1.xml":
                formula = b"<f>SUM(C6:C7)</f>"
                assert formula + b"<v></v>" in data
                data = data.replace(formula + b"<v></v>", formula + b"<v>1172.99</v>")
            after.writestr(member, data)
    _replace_primary(uploaded_files, tmp_path, "xlsx")

    result = process(StoredRun(uuid4(), None, uploaded_files), tmp_path).result

    assert result is not None
    assert result.rows[0].observed_evidence_sum is None
    decision = result.documents[1].decision
    assert decision.state == "needs_review"
    assert decision.reason_code == "formula_cache_mismatch"


def test_scan_reports_inferred_period_and_marks_missing_amounts(
    uploaded_files, tmp_path, monkeypatch
):
    from test_local_ocr import _box
    from test_native_pdf import _write_pdf

    from doccheck_backend.native_observations import NativeDocument

    calls = _stub_ollama(monkeypatch, "1172.70")
    report = uploaded_files[0]
    path = tmp_path / report["id"]
    _write_pdf(path, [b"0 0 10 10 re f"])
    report.update(format="pdf", name="report.pdf", sha256=sha256(path.read_bytes()).hexdigest())

    observations = (
        _box("Договор № E2E-31", 0.06, 0.09, 0.36),
        _box("Начало 2 этапа", 0.06, 0.12, 0.14),
        _box('"22" октября 2026 г.', 0.18, 0.12, 0.28),
        _box("Окончание 2 этапа", 0.06, 0.15, 0.15),
        _box('"17" марта 2027 г.', 0.18, 0.15, 0.28),
        _box("Общехозяйственные затраты", 0.73, 0.24, 0.81),
        _box("2 этап, 2026 г.:", 0.04, 0.50, 0.16),
        _box("2 этап, 2027 г.:", 0.04, 0.53, 0.16),
        _box("1 250,50", 0.75, 0.53, 0.79),
    )
    monkeypatch.setattr(
        "doccheck_backend.v32_adapter.read_scan", lambda *_: NativeDocument(observations)
    )
    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert job.status == "completed"
    assert job.result.scope.period_start == "2027-01-01"
    assert job.result.scope.period_end == "2027-03-17"
    assert job.result.scope.report_row_locator.bbox[:2] == (0.04, 0.53)
    rows = {row.id: row for row in job.result.rows}
    assert rows["general_admin"].reported_value is None
    assert rows["general_admin"].observed_evidence_sum == "1172.70"
    for name in ("payroll", "insurance", "production_overhead", "general_admin"):
        assert rows[name].reported_value is None
        assert "ocr_report_amount_unconfirmed" in {reason.code for reason in rows[name].reasons}

    report_sources = [item for item in job.result.evidence if item.document_id == report["id"]]
    cutoff, contract = report_sources
    assert cutoff.kind == "period"
    assert cutoff.normalized_value.start is None and cutoff.normalized_value.end == "2027-03-17"
    assert cutoff.locator.bbox[:2] == (0.06, 0.15)
    assert contract.kind == "contract" and contract.normalized_value == "E2E-31"
    assert contract.locator.bbox[:2] == (0.06, 0.09)
    assert job.result.documents[0].decision.evidence_refs == [cutoff.id, contract.id]


def test_unrelated_xlsx_heading_cannot_relabel_total():
    from decimal import Decimal

    from doccheck_backend.contracts.locators import SheetLocator
    from doccheck_backend.native_observations import Observation
    from doccheck_backend.v32_adapter import _source_groups

    def cell(address, text, **values):
        return Observation(
            text, SheetLocator(kind="sheet", sheet="Взносы", range=address), **values
        )

    observations = (
        cell("A1", "Расчет страховых взносов"),
        cell("E1", "Расчетная ведомость по оплате труда"),
        cell("B6", "1172.70", amount=Decimal("1172.70"), amount_role="total"),
    )
    assert _source_groups("xlsx", observations, {}, "payroll") == ([], [])
    assert _source_groups("xlsx", observations, {}, "insurance") == (
        [observations[2]],
        [observations[0]],
    )


def test_primary_png_contract_conflict_prevents_evidence(uploaded_files, tmp_path, monkeypatch):
    from PIL import Image
    from test_local_ocr import _box

    from doccheck_backend.native_observations import NativeDocument

    _stub_ollama(monkeypatch, "1172.70")
    from bench.e2e_v32_20261114 import run as v32

    Image.new("RGB", (30, 30), "white").save(tmp_path / uploaded_files[1]["id"], "PNG")
    _replace_primary(uploaded_files, tmp_path, "png")
    request = v32.runtime.api

    def predict_scan(path, body=None, timeout=600):
        if path == "/api/chat":
            body["messages"][0]["content"] += "E2E-31"
        return request(path, body, timeout)

    monkeypatch.setattr(v32.runtime, "api", predict_scan)
    observations = (
        _box("Договор № E2E-31", 0.06, 0.09, 0.36),
        _box("Договор № E2E-99", 0.06, 0.09, 0.36, confidence=0.74),
    )
    monkeypatch.setattr(
        "doccheck_backend.v32_adapter.read_scan", lambda *_: NativeDocument(observations)
    )
    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert job.result.documents[1].decision.state == "needs_review"
    assert not job.result.documents[1].decision.evidence_refs
    assert all(item.document_id != uploaded_files[1]["id"] for item in job.result.evidence)


@pytest.mark.parametrize("end_day", [30, 31], ids=["wholly-in-scope", "one-day-overlap"])
def test_primary_month_boundary_never_admits_unallocated_total(
    uploaded_files, tmp_path, monkeypatch, end_day
):
    report_path = tmp_path / uploaded_files[0]["id"]
    with report_path.open("rb") as source:
        book = load_workbook(source)
    book.active["B7"] = "Оплата труда"
    book.active["A4"] = "Период: 2027-05-01 — 2027-05-30. Этап 2."
    book.save(report_path)
    uploaded_files[0]["sha256"] = sha256(report_path.read_bytes()).hexdigest()

    primary_path = tmp_path / uploaded_files[1]["id"]
    book = Workbook()
    sheet = book.active
    interval = "Май 2027" if end_day == 31 else "2027-05-01 — 2027-05-30"
    for cell, value in {
        "A1": "Расчетная ведомость по оплате труда",
        "A2": "Документ: ACT-31",
        "A3": f"Проект: E2E-31 | Период: {interval}",
        "A5": "Код статьи",
        "B5": "Вид начисления",
        "C5": "Сумма, руб.",
        "C6": 750.25,
        "C7": 422.45,
        "B8": "Итого",
        "C8": "=SUM(C6:C7)",
    }.items():
        sheet[cell] = value
    book.save(primary_path)
    _replace_primary(uploaded_files, tmp_path, "xlsx")

    calls = _stub_xlsx_prediction(monkeypatch, "1172.70", "payroll")
    from bench.e2e_v32_20261114 import run as v32

    request = v32.runtime.api

    def predict_may(path, body=None, timeout=600):
        response = request(path, body, timeout)
        if path == "/api/chat":
            payload = json.loads(response["message"]["content"])
            payload.update(period_start="2027-05-01", period_end=f"2027-05-{end_day}")
            response["message"]["content"] = json.dumps(payload)
        return response

    monkeypatch.setattr(v32.runtime, "api", predict_may)

    job = process(StoredRun(uuid4(), None, uploaded_files), tmp_path)

    assert calls == ["/api/tags", "/api/chat", "/api/ps"]
    assert job.status == "completed"
    assert job.result.scope.period_end == "2027-05-30"
    row = job.result.rows[0]
    assert row.status == "unverified" and row.expected_value is None
    primary = job.result.documents[1]
    if end_day == 31:
        assert row.observed_evidence_sum is None
        assert not row.calculation.components
        assert primary.decision.state == "needs_review"
        assert primary.decision.reason_code == "period_partially_overlaps_unallocatable_amount"
    else:
        assert row.observed_evidence_sum == "1172.70"
        assert primary.decision.state == "include"
