"""Synthetic issuer-spelling collisions through CLI and the document queue."""

import json
import os
from hashlib import sha256
from itertools import permutations
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from test_copy_header_identity import _act, _cli_document, _reconcile_cli, _report, _synthetic_inn
from test_scaffold_integration import process_environment, running_api, running_process

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SPELLING_PAIRS = [
    ("ООО Альфа-Бета", "Общество с ограниченной ответственностью Альфа—Бета"),
    ("ООО Алёнка", "Общество с ограниченной ответственностью Аленка"),
]


def _environment(database_url, upload_root):
    return {
        **process_environment(database_url),
        "DOCCHECK_UPLOAD_ROOT": str(upload_root),
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT), str(BACKEND / "ml_module" / "src"), str(BACKEND / "tests"))
        ),
    }


def _run_package(client, environment, documents, reported):
    response = client.post(
        "/api/v0/runs",
        headers={"Idempotency-Key": str(uuid4())},
        files=[("report", ("report.xlsx", _report(reported))), *documents],
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
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
    Draft202012Validator({"$ref": "#/$defs/CheckResult", "$defs": schema["$defs"]}).validate(result)
    return result


@pytest.mark.parametrize(("first_issuer", "second_issuer"), SPELLING_PAIRS)
def test_cli_spelling_variants_require_review_in_both_orders(tmp_path, first_issuer, second_issuer):
    first = _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=first_issuer)
    second = _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=second_issuer)
    assert first["source_hash"] != second["source_hash"]
    for order in permutations((first, second)):
        result = _reconcile_cli(list(order), "100.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified" and row["source_ids"] == []
        assert row["expected_amount"] is None and row["delta"] is None
        assert {reason["id"] for reason in row["reasons"] if "id" in reason} == {"first", "second"}


@pytest.mark.parametrize(("first_issuer", "second_issuer"), SPELLING_PAIRS)
def test_cli_spelling_variants_preserve_independent_third_in_every_order(
    tmp_path, first_issuer, second_issuer
):
    documents = [
        _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=first_issuer),
        _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=second_issuer),
        _cli_document(tmp_path, "third", "Акт № ACT-71", issuer="ООО Гамма"),
    ]
    assert len({document["source_hash"] for document in documents}) == 3
    for order in permutations(documents):
        result = _reconcile_cli(list(order), "200.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified"
        assert row["partial_amount"] == "100.00" and row["source_ids"] == ["third"]
        assert row["expected_amount"] is None and row["delta"] is None
        assert {reason["id"] for reason in row["reasons"] if "id" in reason} == {"first", "second"}


@pytest.mark.parametrize(("first_issuer", "second_issuer"), SPELLING_PAIRS)
def test_real_api_worker_spelling_variants_require_review_in_both_orders(
    database_url, tmp_path, first_issuer, second_issuer
):
    variants = [
        ("first.docx", _act("Акт № ACT-71", issuer=first_issuer)),
        ("second.docx", _act("Акт № ACT-71", issuer=second_issuer)),
    ]
    assert sha256(variants[0][1]).digest() != sha256(variants[1][1]).digest()
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(variants):
            result = _run_package(
                client,
                environment,
                [("documents", (name, content)) for name, content in order],
                100,
            )
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            supports = [item for item in result["documents"] if item["role"] == "support"]
            assert row["status"] == "unverified"
            assert row["expected_value"] is None and row["delta"] is None
            assert row["observed_evidence_sum"] is None
            assert row["calculation"]["components"] == []
            assert all(item["duplicate_of"] is None for item in supports)
            assert all(item["decision"]["state"] == "needs_review" for item in supports)


@pytest.mark.parametrize(("first_issuer", "second_issuer"), SPELLING_PAIRS)
def test_real_api_worker_all_orders_keep_only_independent_third(
    database_url, tmp_path, first_issuer, second_issuer
):
    variants = [
        ("first.docx", _act("Акт № ACT-71", issuer=first_issuer)),
        ("second.docx", _act("Акт № ACT-71", issuer=second_issuer)),
        ("third.docx", _act("Акт № ACT-71", issuer="ООО Гамма")),
    ]
    assert len({sha256(content).digest() for _, content in variants}) == 3
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(variants):
            documents = [("documents", (name, content)) for name, content in order]
            result = _run_package(client, environment, documents, 200)
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            supports = {
                item["name"]: item for item in result["documents"] if item["role"] == "support"
            }
            assert all(item["duplicate_of"] is None for item in supports.values())
            assert row["status"] == "unverified"
            assert row["expected_value"] is None and row["delta"] is None
            assert row["observed_evidence_sum"] == "100.00"
            assert supports["first.docx"]["decision"]["state"] == "needs_review"
            assert supports["second.docx"]["decision"]["state"] == "needs_review"
            assert supports["third.docx"]["decision"]["state"] == "include"
            assert len(row["calculation"]["components"]) == 1
            evidence = {item["id"]: item for item in result["evidence"]}
            amount_ref = row["calculation"]["components"][0]["amount_refs"][0]
            assert evidence[amount_ref]["document_id"] == supports["third.docx"]["id"]
            for name in ("first.docx", "second.docx"):
                refs = [evidence[ref] for ref in supports[name]["decision"]["evidence_refs"]]
                assert any(
                    ref["kind"] == "document_identity"
                    and ref["locator"] == {"kind": "paragraph", "paragraph": 1}
                    for ref in refs
                )


@pytest.mark.parametrize(
    ("first_issuer", "second_issuer", "independent"),
    [
        (
            f"ООО Альфа, ИНН {_synthetic_inn('012345678')}",
            f"ООО Гамма, ИНН {_synthetic_inn('098765432')}",
            True,
        ),
        (
            f"ООО Альфа-Бета, ИНН {_synthetic_inn('012345678')}",
            f"ООО Альфа—Бета, ИНН {_synthetic_inn('098765432')}",
            False,
        ),
        (
            f"ООО Альфа, ИНН {_synthetic_inn('012345678')}",
            f"ООО Гамма, ИНН {_synthetic_inn('012345678')}",
            False,
        ),
    ],
)
def test_real_api_worker_accounts_for_issuer_tax_conflicts(
    database_url, tmp_path, first_issuer, second_issuer, independent
):
    variants = [
        ("first.docx", _act("Акт № ACT-71", issuer=first_issuer)),
        ("second.docx", _act("Акт № ACT-71", issuer=second_issuer)),
    ]
    assert sha256(variants[0][1]).digest() != sha256(variants[1][1]).digest()
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(variants):
            result = _run_package(
                client,
                environment,
                [("documents", (name, content)) for name, content in order],
                200,
            )
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            supports = [item for item in result["documents"] if item["role"] == "support"]
            assert all(item["duplicate_of"] is None for item in supports)
            if independent:
                assert row["status"] == "verified" and row["expected_value"] == "200.00"
                assert all(item["decision"]["state"] == "include" for item in supports)
            else:
                assert row["status"] == "unverified" and row["expected_value"] is None
                assert row["delta"] is None
                assert all(item["decision"]["state"] == "needs_review" for item in supports)
