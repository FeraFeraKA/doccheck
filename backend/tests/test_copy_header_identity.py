"""Synthetic checks for an explicitly numbered copy of an act."""

import io
import json
import os
from copy import deepcopy
from hashlib import sha256
from itertools import permutations
from pathlib import Path
from uuid import uuid4

import pytest
from bench.e2e_v32_20261114.decision_rules import reconcile
from bench.e2e_v32_20261114.document_identity import (
    apply_document_number_checks,
    resolve_own_number,
)
from bench.e2e_v32_20261114.explanations import explain
from bench.e2e_v32_20261114.runtime import native_text
from docx import Document
from jsonschema import Draft202012Validator
from openpyxl import Workbook
from test_scaffold_integration import process_environment, running_api, running_process

from doccheck_backend.v32_processor import V32Processor

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


@pytest.mark.parametrize(
    "header",
    [
        "Копия акта № ACT-71",
        "КОПИЯ АКТА оказанных услуг номер: ACT-71 от 31.01.2026",
        "Копия акта выполненных работ № ACT-71",
        "Копия: акт № ACT-71",
        "Акт № ACT-71 (копия)",
        "Акт № ACT-71 от 31.01.2026 (копия)",
        "Акт № ACT-71 (копия) от 31.01.2026",
    ],
)
def test_copy_header_has_literal_number_kind_and_address(header):
    text = f"{header}\nИсполнитель: ООО Синтетика\nДоговор № SYN-7"
    parsed = resolve_own_number(text)
    assert parsed["status"] == "resolved"
    assert parsed["resolved_number"] == "ACT-71"
    assert parsed["document_kind"] == "act"
    candidate = parsed["candidates"][0]
    assert text[candidate["start"] : candidate["end"]] == "ACT-71"
    assert text[candidate["context_start"] : candidate["context_end"]] == header


@pytest.mark.parametrize(
    "text",
    [
        "Основание: копия акта № ACT-71",
        "Для сверки использована копия акта № ACT-71",
        "«Копия акта № ACT-71»",
        "Копия акта ACT-71",
        "Копия акта к договору № ACT-71",
        "Копия акта № ACT-71 и ACT-72",
        "Копия акта № ACT-71\nАкт № ACT-72",
        "Копия: акт № ACT-71 и ACT-72",
        "Акт № ACT-71 (копия) и ACT-72",
        "Акт № ACT-71 (исправленный)",
        "Акт № ACT-71 (копия другого документа)",
        "Основание: копия: акт № ACT-71",
    ],
)
def test_reference_unmarked_or_ambiguous_copy_is_not_resolved(text):
    assert resolve_own_number(text)["status"] != "resolved"


def _no_model(*args, **kwargs):
    raise AssertionError("This office-only test must not call a model")


def process_synthetic_office(run, directory):
    """Actual v3.2 processor with model calls forbidden for these native files."""
    return V32Processor(_no_model, _no_model)(run, directory)


def _report(amount):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "КФЗ"
    sheet["A3"] = "Договор № SYN-7"
    sheet["A4"] = "Период: 2026-01-01 — 2026-01-31. Этап 1."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    sheet["B7"], sheet["C7"] = "Общехозяйственные расходы", amount
    sheet["A8"], sheet["C8"] = "Всего по отчету", "=SUM(C7:C7)"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _act(header, *, amount="100,00", contract="SYN-7", issuer="ООО Синтетика", period=None):
    doc = Document()
    for line in (
        header,
        f"Исполнитель: {issuer}",
        f"Договор № {contract}",
        f"Период: {period or '2026-01-01 — 2026-01-31'}",
        "Описание услуг: административное обслуживание",
        f"Итого: {amount} руб.",
    ):
        doc.add_paragraph(line)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def _cli_document(tmp_path, identifier, header, amount="100.00", issuer="ООО Синтетика"):
    path = tmp_path / f"{identifier}.docx"
    doc = Document(io.BytesIO(_act(header, amount=amount.replace(".", ","), issuer=issuer)))
    doc.add_paragraph(f"Примечание: синтетический вариант {identifier}")
    doc.save(path)
    record = {
        "id": identifier,
        "path": str(path),
        "source_hash": sha256(path.read_bytes()).hexdigest(),
        "prediction": {
            "contract_number": "SYN-7",
            "doc_number": None,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "category": "general_admin",
            "amount": amount,
        },
    }
    return apply_document_number_checks(record, native_text(path))


def _reconcile_cli(documents, reported="100.00"):
    return reconcile(
        documents,
        [{"category": "general_admin", "reported_amount": reported}],
        "SYN-7",
        "2026-01-01",
        "2026-01-31",
        {"status": "complete", "basis": "user_manifest"},
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("second_amount", ["100.00", "153.27"])
@pytest.mark.parametrize(
    "copy_header",
    ["Копия акта № ACT-71", "Копия: акт № ACT-71", "Акт № ACT-71 (копия)"],
)
def test_cli_copy_collision_is_reviewable_with_addressed_sources(
    tmp_path, reverse, second_amount, copy_header
):
    first = _cli_document(tmp_path, "first", "Акт № ACT-71")
    second = _cli_document(tmp_path, "second", copy_header, second_amount)
    assert first["source_hash"] != second["source_hash"]
    documents = [first, second]
    if reverse:
        documents.reverse()
    result = _reconcile_cli(documents)
    row = result["rows"][0]
    assert result["duplicates"] == []
    assert row["status"] == "unverified"
    assert row["expected_amount"] is None and row["delta"] is None
    assert row["source_ids"] == []
    assert {r["id"] for r in row["reasons"] if "id" in r} == {"first", "second"}
    assert any(
        w["reason"] == "unresolved_document_identity_collision" for w in result["identity_warnings"]
    )

    explanation = explain({"id": "report"}, documents, result)
    decisions = {item["document_id"]: item for item in explanation["document_decisions"]}
    assert set(decisions) == {"first", "second"}
    for identifier, item in decisions.items():
        assert item["disposition"] == "requires_review"
        number = [e for e in item["evidence"] if e["kind"] == "own_number"]
        assert len(number) == 1 and number[0]["text"] == "ACT-71"
        source = first if identifier == "first" else second
        span = number[0]["locator"]
        assert (
            source["source_native_text"][span["source_char_start"] : span["source_char_end"]]
            == "ACT-71"
        )


def test_cli_other_operation_stays_in_partial_sum_and_byte_copy_is_deduplicated(tmp_path):
    first = _cli_document(tmp_path, "first", "Акт № ACT-71")
    similar = _cli_document(tmp_path, "similar", "Акт № ACT-71")
    other = _cli_document(tmp_path, "other", "Акт № ACT-72", "25.00")
    result = _reconcile_cli([first, similar, other], "125.00")
    assert result["rows"][0]["status"] == "unverified"
    assert result["rows"][0]["partial_amount"] == "25.00"
    assert result["rows"][0]["source_ids"] == ["other"]
    assert result["duplicates"] == []

    byte_copy = deepcopy(first)
    byte_copy["id"] = "byte-copy"
    result = _reconcile_cli([first, byte_copy])
    assert result["rows"][0]["status"] == "correct"
    assert result["rows"][0]["expected_amount"] == "100.00"
    assert result["duplicates"] == [{"id": "byte-copy", "duplicate_of": "first", "basis": "hash"}]


def test_cli_distinct_numbers_and_equal_amounts_remain_separate(tmp_path):
    first = _cli_document(tmp_path, "first", "Акт № ACT-71")
    second = _cli_document(tmp_path, "second", "Копия акта № ACT-72")
    result = _reconcile_cli([first, second], "200.00")
    assert result["rows"][0]["status"] == "correct"
    assert result["rows"][0]["expected_amount"] == "200.00"
    assert result["rows"][0]["source_ids"] == ["first", "second"]
    assert result["duplicates"] == []


def test_cli_three_matching_numbers_remain_review_candidates(tmp_path):
    documents = [
        _cli_document(tmp_path, "first", "Акт № ACT-71"),
        _cli_document(tmp_path, "second", "Копия акта № ACT-71"),
        _cli_document(tmp_path, "third", "Акт № ACT-71"),
    ]
    result = _reconcile_cli(documents)
    assert result["duplicates"] == []
    assert result["rows"][0]["status"] == "unverified"
    assert result["rows"][0]["source_ids"] == []
    assert {r["id"] for r in result["rows"][0]["reasons"] if "id" in r} == {
        "first",
        "second",
        "third",
    }


def test_cli_all_compatible_pairs_are_checked_in_every_order(tmp_path):
    records = [
        _cli_document(tmp_path, "alpha1", "Акт № ACT-71", issuer="ООО Альфа"),
        _cli_document(tmp_path, "beta", "Акт № ACT-71", issuer="ООО Бета"),
        _cli_document(tmp_path, "alpha2", "Копия: акт № ACT-71", issuer="ООО Альфа"),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified"
        assert row["expected_amount"] is None and row["delta"] is None
        assert row["partial_amount"] == "100.00" and row["source_ids"] == ["beta"]
        assert {r["id"] for r in row["reasons"] if "id" in r} == {"alpha1", "alpha2"}
        decisions = {
            item["document_id"]: item["disposition"]
            for item in explain({"id": "report"}, list(order), result)["document_decisions"]
        }
        assert decisions == {
            "alpha1": "requires_review",
            "alpha2": "requires_review",
            "beta": "included",
        }


def test_cli_missing_issuer_does_not_hide_any_compatible_pair(tmp_path):
    records = [
        _cli_document(tmp_path, "alpha", "Акт № ACT-71", issuer="ООО Альфа"),
        _cli_document(tmp_path, "beta", "Акт № ACT-71", issuer="ООО Бета"),
        _cli_document(tmp_path, "unknown", "Копия: акт № ACT-71", issuer=""),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified"
        assert row["source_ids"] == []
        assert {r["id"] for r in row["reasons"] if "id" in r} == {"alpha", "beta", "unknown"}


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    ("second_kwargs", "second_header", "reported", "expected_state"),
    [
        ({}, "Копия акта № ACT-71", 100, "collision"),
        ({"amount": "153,27"}, "Копия акта № ACT-71", 100, "collision"),
        ({}, "Копия: акт № ACT-71", 100, "collision"),
        ({}, "Акт № ACT-71 (копия)", 100, "collision"),
        ({"amount": "153,27"}, "Акт № ACT-71 (копия)", 100, "collision"),
        ({}, "Копия акта № ACT-72", 200, "two_included"),
        ({}, "Копия: акт № ACT-72", 200, "two_included"),
        ({}, "Акт № ACT-72 (копия)", 200, "two_included"),
        ({"issuer": "ООО Другое"}, "Копия: акт № ACT-71", 200, "two_included"),
        ({"contract": "SYN-8"}, "Акт № ACT-71 (копия)", 100, "other_contract"),
        ({"period": "2026-01-15 — 2026-01-31"}, "Копия: акт № ACT-71", 200, "two_included"),
    ],
)
def test_real_api_worker_and_database_handle_copy_candidates(
    database_url, tmp_path, reverse, second_kwargs, second_header, reported, expected_state
):
    first = _act("Акт № ACT-71")
    second = _act(second_header, **second_kwargs)
    assert sha256(first).digest() != sha256(second).digest()
    documents = [("documents", ("one.docx", first)), ("documents", ("two.docx", second))]
    if reverse:
        documents.reverse()
    environment = {
        **process_environment(database_url),
        "DOCCHECK_UPLOAD_ROOT": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT), str(BACKEND / "ml_module" / "src"), str(BACKEND / "tests"))
        ),
    }
    with running_api(database_url, environment=environment) as client:
        created = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(uuid4())},
            files=[("report", ("report.xlsx", _report(reported))), *documents],
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        with running_process(
            [
                "-m",
                "doccheck_backend.run_worker",
                "--processor",
                "test_copy_header_identity:process_synthetic_office",
                "--once",
            ],
            environment,
        ) as worker:
            assert worker.wait(timeout=30) == 0
        assert client.get(f"/api/v0/runs/{run_id}").json()["status"] == "completed"
        response = client.get(f"/api/v0/runs/{run_id}/findings")
        assert response.status_code == 200
        result = response.json()

    schema = json.loads(
        (ROOT / "contracts" / "check-result.v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator({"$ref": "#/$defs/CheckResult", "$defs": schema["$defs"]}).validate(result)
    supporting = [item for item in result["documents"] if item["role"] == "support"]
    assert len(supporting) == 2
    assert all(item["duplicate_of"] is None for item in supporting)
    row = next(row for row in result["rows"] if row["id"] == "general_admin")
    if expected_state == "collision":
        assert row["status"] == "unverified"
        assert row["expected_value"] is None and row["delta"] is None
        assert row["calculation"]["components"] == []
        assert all(item["decision"]["state"] == "needs_review" for item in supporting)
        assert all(item["decision"]["reason_code"] == "duplicate_identity" for item in supporting)
        evidence = {item["id"]: item for item in result["evidence"]}
        for item in supporting:
            refs = [evidence[ref] for ref in item["decision"]["evidence_refs"]]
            identity = [ref for ref in refs if ref["kind"] == "document_identity"]
            assert len(identity) == 1
            assert identity[0]["document_id"] == item["id"]
            assert identity[0]["normalized_value"] == "ACT-71"
            assert identity[0]["locator"] == {"kind": "paragraph", "paragraph": 1}
        assert any(reason["code"] == "duplicate_identity" for reason in row["reasons"])
    else:
        assert row["status"] == "verified"
        assert row["delta"] == "0.00"
        included = [item for item in supporting if item["decision"]["state"] == "include"]
        assert len(included) == (1 if expected_state == "other_contract" else 2)
        assert len(row["calculation"]["components"]) == len(included)
        if expected_state == "other_contract":
            assert any(
                item["decision"]["reason_code"] == "different_contract" for item in supporting
            )
