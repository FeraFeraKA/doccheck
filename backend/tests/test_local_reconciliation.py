import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from scanned_kfz_fixture import (
    ScanRow,
    require_raster_ocr,
    write_kfz_with_breakdown,
    write_scanned_kfz,
)

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.run_worker import run_document_worker
from doccheck_backend.v32_processor import V32Processor

CONTRACT = "77/78419/26-02"
START, END = "2031-02-01", "2031-02-28"


def write_reconciliation_case(root: Path) -> tuple[Path, list[Path]]:
    report = root / "synthetic_kfz.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = f"Договор № {CONTRACT}"
    sheet["A4"] = f"Период: {START} — {END}. Этап 5."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    for row, name, amount in [
        (7, "Оплата труда", 1070.45),
        (8, "Страховые взносы", 351.29),
        (9, "Общепроизводственные расходы", 789.05),
        (10, "Общехозяйственные расходы", 399.12),
    ]:
        sheet[f"B{row}"], sheet[f"C{row}"] = name, amount
    sheet["A11"], sheet["C11"] = "Всего по отчету", "=SUM(C7:C10)"
    book.save(report)

    files = []
    for title, name, amount in [
        ("Расчетная ведомость по оплате труда", "payroll", "1070.45"),
        ("Расчет страховых взносов", "insurance", "351.29"),
    ]:
        workbook = Workbook()
        sheet = workbook.active
        sheet["A1"] = title
        sheet["A2"] = f"Документ: SYN-{name.upper()}-31"
        sheet["A3"] = f"Договор № {CONTRACT}"
        sheet["A4"] = f"Период: {START} — {END}"
        if name == "payroll":
            sheet.append(["Код статьи", "Вид начисления", "Сумма, руб."])
            sheet.append(["9101", "Оклад", float(amount)])
            sheet.append(["9102", "Премия", 0])
            sheet["B8"], sheet["C8"] = "Итого", "=SUM(C6:C7)"
        else:
            sheet.append(["База начислений, руб.", "Начислено взносов, руб.", "Код статьи"])
            sheet.append([1070.45, float(amount), "9201"])
        path = root / f"{name}.xlsx"
        workbook.save(path)
        files.append(path)

    for number, description, amount in [
        ("UPD-71", "Аренда испытательного оборудования для выполнения работ этапа 5.", "746,28"),
        ("ADM-72", "Общехозяйственные расходы.", "399,12"),
    ]:
        document = Document()
        document.add_paragraph(f"УПД № {number}")
        document.add_paragraph(f"Договор № {CONTRACT}")
        document.add_paragraph(f"Период: {START} — {END}")
        document.add_paragraph(description)
        document.add_paragraph(f"Итого: {amount} руб.")
        path = root / f"{number}.docx"
        document.save(path)
        files.append(path)
    return report, files


def no_model(*args, **kwargs):
    pytest.fail("Native synthetic data should not need the model")


def _prepare_and_start(client, files, data=None):
    prepared = client.post(
        "/api/v0/runs/uploads",
        headers={"Idempotency-Key": str(uuid4())},
        files=files,
        data=data,
    )
    assert prepared.status_code == 201, prepared.text
    upload_id = prepared.json()["upload_id"]
    assert client.get(f"/api/v0/runs/{upload_id}").status_code == 404
    accepted = client.post(f"/api/v0/runs/uploads/{upload_id}/start")
    assert accepted.status_code == 202
    assert accepted.json()["run_id"] == upload_id
    return upload_id


@pytest.mark.parametrize(
    "missing_article",
    [False, True],
)
def test_calculates_status_and_total_from_admitted_sources(database_url, tmp_path, missing_article):
    report, files = write_reconciliation_case(tmp_path)
    if missing_article:
        files = [p for p in files if p.name != "insurance.xlsx"]
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(uuid4())},
            files=[
                ("report", (report.name, report.read_bytes())),
                *(("documents", (p.name, p.read_bytes())) for p in files),
                ("documents", ("copy.docx", files[-1].read_bytes())),
            ],
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(no_model, no_model),
            once=True,
        )
        findings = client.get(f"/api/v0/runs/{run_id}/findings")
        assert findings.status_code == 200, client.get(f"/api/v0/runs/{run_id}").json()
        result = findings.json()
        rows = {row["id"]: row for row in result["rows"]}
        assert rows["production_overhead"]["observed_evidence_sum"] == "746.28"
        assert sum(bool(doc["duplicate_of"]) for doc in result["documents"]) == 1
        assert all(row["completeness"]["basis"] == "uploaded_package" for row in rows.values())
        mismatch, total = rows["production_overhead"], rows["total"]
        assert mismatch["delta"] == "42.77"
        assert total["is_aggregate"]
        if missing_article:
            insurance = rows["insurance"]
            assert insurance["expected_value"] == "0.00"
            assert insurance["observed_evidence_sum"] is None
            assert insurance["status"] == "discrepancy"
            assert insurance["delta"] == "351.29"
            assert insurance["reasons"][0]["code"] == "missing_supporting_documents"
            assert total["expected_value"] == "2215.85"
            assert total["delta"] == "394.06"
            assert not total["derived_mismatch"]
            assert result["summary"]["counts"] == {
                "verified": 2,
                "discrepancy": 3,
                "unverified": 0,
            }
        else:
            assert total["expected_value"] == "2567.14"
            assert total["delta"] == "42.77"
            assert total["derived_mismatch"]
            assert total["root_issue_id"] == mismatch["root_issue_id"]
            assert len(result["summary"]["primary_issues"]) == 1
            assert result["summary"]["counts"] == {
                "verified": 3,
                "discrepancy": 2,
                "unverified": 0,
            }
        assert client.get(f"/api/v0/runs/{run_id}/exports/xlsx").content.startswith(b"PK")


@pytest.mark.parametrize(
    ("filename", "code"),
    [
        ("truncated.pdf", "pdf_unreadable"),
        ("truncated.docx", "source_incomplete"),
        ("truncated.xlsx", "source_incomplete"),
        ("empty.docx", "source_incomplete"),
        ("empty.xlsx", "source_incomplete"),
    ],
)
def test_unreadable_source_keeps_the_rest_of_the_run(database_url, tmp_path, filename, code):
    report, files = write_reconciliation_case(tmp_path)
    if filename.endswith(".pdf"):
        content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog"
    elif filename.startswith("truncated"):
        content = b"PK\x03\x04"
    else:
        stream = BytesIO()
        empty = Document() if filename.endswith(".docx") else Workbook()
        empty.save(stream)
        content = stream.getvalue()
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        run_id = _prepare_and_start(
            client,
            [
                ("report", (report.name, report.read_bytes())),
                *(("documents", (path.name, path.read_bytes())) for path in files),
                ("documents", (filename, content)),
            ],
        )
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(no_model, no_model),
            once=True,
        )
        entry = f"/api/v0/runs/{run_id}"
        findings = client.get(entry + "/findings")
        assert findings.status_code == 200, client.get(entry).json()
        assert client.get(entry).json()["status"] == "completed_with_issues"
        result = findings.json()
        damaged = next(doc for doc in result["documents"] if doc["name"] == filename)
        assert damaged["decision"]["state"] == "parse_error"
        assert damaged["parse_status"] == "error"
        assert any(issue["code"] == code for issue in damaged["errors"])
        if filename.endswith(".pdf"):
            assert any("PDF" in issue["message"] for issue in damaged["errors"])
        assert any(doc["decision"]["state"] == "include" for doc in result["documents"])
        row = next(row for row in result["rows"] if row["id"] == "payroll")
        assert row["reported_value"] == row["observed_evidence_sum"] == "1070.45"
        assert row["status"] == "unverified"


def test_scanned_breakdown_retains_unverified_values_without_counting_them_twice(
    database_url, tmp_path
):
    require_raster_ocr()
    _, files = write_reconciliation_case(tmp_path)
    report = write_kfz_with_breakdown(
        tmp_path / "report.png",
        CONTRACT,
        (START, END),
        ScanRow(5, 2031, ("1070,45", "351,29", "789,05", "399,12", "2609,91")),
    )
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        run_id = _prepare_and_start(
            client,
            [
                ("report", (report.name, report.read_bytes())),
                *(("documents", (p.name, p.read_bytes())) for p in files),
            ],
        )
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(no_model, no_model),
            once=True,
        )
        entry = f"/api/v0/runs/{run_id}"
        status = client.get(entry).json()
        assert status["status"] == "completed", status
        result = client.get(entry + "/findings").json()
        rows = {row["id"]: row for row in result["rows"]}
        details = {key: row for key, row in rows.items() if row["status"] == "unverified"}
        assert result["summary"]["counts"] == {"verified": 3, "discrepancy": 2, "unverified": 9}
        assert {
            "0200-subtotal",
            "0200-base",
            "0200-additional",
            "0200-reserve",
            "0300-subtotal",
            "0300-base",
            "0300-additional",
            "0300-reserve",
            "labor_intensity",
        } == details.keys()
        for row in details.values():
            assert row["expected_value"] is row["observed_evidence_sum"] is row["delta"] is None
        assert details["0200-reserve"]["parent_row_id"] == "payroll"
        assert details["0200-reserve"]["reported_value"] == "73.30"
        assert details["0300-additional"]["reported_value"] == "51.90"
        assert details["0300-reserve"]["parent_row_id"] == "insurance"
        assert details["0300-reserve"]["reported_value"] is None
        labor = details["labor_intensity"]
        assert labor["unit"] == "чел.-ч." and labor["reported_value"] == "17.625"
        source = next(
            item for item in result["evidence"] if item["id"] in labor["reported_evidence_refs"]
        )
        assert source["locator"]["page"] == 1 and source["locator"]["bbox"]
        mismatch, total = rows["production_overhead"], rows["total"]
        assert total["delta"] == mismatch["delta"] == "42.77"
        assert total["derived_mismatch"] and total["root_issue_id"] == mismatch["root_issue_id"]
        coverage = result["summary"]["rub_coverage"]
        assert coverage["total"] == "2609.91" and coverage["unverified"] is None

        book = load_workbook(BytesIO(client.get(entry + "/exports/xlsx").content), read_only=True)
        labor_export = next(row for row in book["Сверка"].values if row[0] == labor["id"])
        assert labor_export[4:9] == ("17.625", None, None, None, "Не проверен")
        book.close()


def test_bundled_example_counts_the_document_total(database_url, tmp_path):
    root = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
    report, act = root / "report.xlsx", root / "act.docx"
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        run_id = _prepare_and_start(
            client,
            [
                ("report", (report.name, report.read_bytes())),
                ("documents", (act.name, act.read_bytes())),
            ],
        )
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(no_model, no_model),
            once=True,
        )
        findings = client.get(f"/api/v0/runs/{run_id}/findings")
        assert findings.status_code == 200
        result = findings.json()
        assert result["synthetic"]
        row = next(row for row in result["rows"] if row["id"] == "general_admin")
        assert row["expected_value"] == "8112.50"
        assert row["calculation"]["components"][0]["amount"] == "8112.50"


def test_unresolved_scan_can_retry_existing_files_with_the_correct_stage(database_url, tmp_path):
    require_raster_ocr()
    _, documents = write_reconciliation_case(tmp_path)
    for stage, amount in [(5, "399,12"), (6, "700,00")]:
        document = Document()
        document.add_paragraph("Акт № SYN-043")
        document.add_paragraph(f"Договор № {CONTRACT}")
        document.add_paragraph(f"Период: {START} — {END}")
        document.add_paragraph(f"Этап: № {stage:02}")
        document.add_paragraph("Общехозяйственные расходы.")
        document.add_paragraph(f"Итого: {amount} руб.")
        path = tmp_path / f"admin-stage-{stage}.docx"
        document.save(path)
        if stage == 5:
            documents = [path if item.name == "ADM-72.docx" else item for item in documents]
        else:
            documents.append(path)
    target = ScanRow(5, 2031, ("1070,45", "351,29", "789,05", "399,12", "2609,91"))
    ambiguous = ScanRow(6, 2031, ("1040,00", "340,00", "790,00", "400,00", "2570,00"))
    report = write_scanned_kfz(
        tmp_path / "report.png", ((target, ambiguous),), contract=CONTRACT, period=(START, END)
    )
    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    processor = V32Processor(no_model, no_model)
    with TestClient(create_app(settings)) as client:
        run_id = _prepare_and_start(
            client,
            [
                ("report", (report.name, report.read_bytes())),
                *(("documents", (doc.name, doc.read_bytes())) for doc in documents),
            ],
        )

        def retry_with_stage(previous, stage):
            assert run_document_worker(
                client.app.state.engine, settings.upload_root, processor, once=True
            )
            previous_url = f"/api/v0/runs/{previous}"
            state = client.get(previous_url).json()
            assert state["status"] == "failed" and state["error"]["code"] == "scan_scope_required"
            pack = client.get(previous_url + "/pack")
            assert pack.status_code == 200
            fields = {
                "source_run_id": previous,
                "contract_number": CONTRACT,
                "period_start": START,
                "period_end": END,
                "report_row_locator": json.dumps(
                    {"kind": "page", "page": 1, "fragment_id": f"kfz-stage-{stage}-2031"}
                ),
            }
            files = [
                ("retained_document_id", (None, item["id"])) for item in pack.json()["documents"]
            ]
            return _prepare_and_start(client, files, data=fields)

        incorrect = retry_with_stage(run_id, 7)
        corrected = retry_with_stage(incorrect, 5)
        assert run_document_worker(
            client.app.state.engine, settings.upload_root, processor, once=True
        )
        findings = client.get(f"/api/v0/runs/{corrected}/findings")
        assert findings.status_code == 200
        result = findings.json()
        assert result["summary"]["counts"] == {
            "verified": 3,
            "discrepancy": 2,
            "unverified": 0,
        }
        excluded = next(doc for doc in result["documents"] if doc["name"] == "admin-stage-6.docx")
        assert excluded["decision"]["reason_code"] == "different_stage"
        assert [
            evidence["normalized_value"]
            for evidence in result["evidence"]
            if evidence["kind"] == "stage"
            and evidence["id"] in excluded["decision"]["evidence_refs"]
        ] == ["6"]
        admin = next(row for row in result["rows"] if row["id"] == "general_admin")
        assert admin["expected_value"] == "399.12"


@pytest.mark.parametrize(
    ("first_issuer", "second_issuer", "second_kind", "expected"),
    [
        ("ООО Альфа", "ООО Бета", "Акт", "399.12"),
        ("ООО Альфа", "ООО Альфа", "Акт", None),
        ("ООО Альфа", "ООО Альфа.", "Акт", None),
        ("ООО Альфа", "ООО «Альфа» (ИНН 7700000000)", "Акт", None),
        ("ООО Альфа", None, "Акт", None),
        ("ООО Альфа", "ООО Альфа", "УПД", "399.12"),
        (
            "ООО Альфа (ИНН 7700000000)",
            "Общество с ограниченной ответственностью Альфа (ИНН 7700000000)",
            "Акт",
            None,
        ),
        ("ООО Альфа (ИНН 7700000000)", "ООО Альфа (ИНН 7800000000)", "Акт", "399.12"),
    ],
)
def test_equal_primary_numbers_require_compatible_issuer_and_kind(
    database_url, tmp_path, first_issuer, second_issuer, second_kind, expected
):
    report, _ = write_reconciliation_case(tmp_path)
    files = []
    for i, (issuer, kind, amount) in enumerate(
        [(first_issuer, "Акт", "200,00"), (second_issuer, second_kind, "199,12")]
    ):
        source = Document()
        source.add_paragraph(f"{kind} № 17")
        if issuer:
            source.add_paragraph(f"Исполнитель: {issuer}")
        source.add_paragraph(f"Договор № {CONTRACT}")
        source.add_paragraph(f"Период: {START} — {END}")
        source.add_paragraph("Оказаны общехозяйственные услуги.")
        source.add_paragraph(f"Итого: {amount} руб.")
        path = tmp_path / f"synthetic-{i}.docx"
        source.save(path)
        files.append(("documents", (path.name, path.read_bytes())))

    settings = Settings(database_url, upload_root=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        run_id = _prepare_and_start(
            client, [("report", (report.name, report.read_bytes())), *files]
        )
        assert run_document_worker(
            client.app.state.engine,
            settings.upload_root,
            V32Processor(no_model, no_model),
            once=True,
        )
        findings = client.get(f"/api/v0/runs/{run_id}/findings")
        assert findings.status_code == 200
        row = next(row for row in findings.json()["rows"] if row["id"] == "general_admin")
        assert row["expected_value"] == expected
        if expected is not None:
            assert row["status"] == "verified"
            assert len(row["calculation"]["components"]) == 2
        else:
            assert row["status"] == "unverified"
            assert row["calculation"]["components"] == []
            assert {reason["code"] for reason in row["reasons"]} == {"duplicate_identity"}
