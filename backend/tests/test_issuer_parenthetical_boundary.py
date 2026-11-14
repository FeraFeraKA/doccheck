"""Synthetic checks for direct issuer INN and uncertain parenthetical roles."""

from hashlib import sha256
from itertools import permutations

import pytest
from bench.e2e_v32_20261114.document_identity import explicit_issuer_inn
from test_copy_header_identity import _act, _cli_document, _reconcile_cli
from test_issuer_role_boundaries import ALPHA_INN, BETA_INN, _assert_ambiguous
from test_issuer_spelling_identity import _environment, _run_package
from test_scaffold_integration import running_api

OTHER_ROLES = ("субподрядчика", "учредителя", "руководителя", "банка", "неизвестной стороны")


@pytest.mark.parametrize(
    "value",
    [
        f"ООО Альфа (неизвестная роль ИНН {ALPHA_INN})",
        f"ООО Альфа (ИНН {ALPHA_INN} неизвестная роль)",
        f"ООО Альфа (филиал) ИНН {ALPHA_INN}",
        f"ООО Альфа [ИНН {ALPHA_INN}]",
        f"ООО Альфа ((ИНН {ALPHA_INN}))",
    ],
)
def test_unknown_or_nested_parenthetical_cannot_authorize_inn(value):
    assert explicit_issuer_inn(value) is None


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_cli_parenthetical_other_role_inn_is_not_issuer_inn(tmp_path, role):
    records = [
        _cli_document(
            tmp_path, "first", "Акт № XZ-614", issuer=f"ООО Альфа ({role} ИНН {ALPHA_INN})"
        ),
        _cli_document(
            tmp_path, "second", "Копия акта № XZ-614", issuer=f"ООО Альфа ({role} ИНН {BETA_INN})"
        ),
    ]
    assert records[0]["source_hash"] != records[1]["source_hash"]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "100.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified" and row["source_ids"] == []
        assert row["expected_amount"] is None and row["delta"] is None


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_real_api_parenthetical_other_role_requires_review(database_url, tmp_path, role):
    records = [
        ("first.docx", _act("Акт № XZ-614", issuer=f"ООО Альфа ({role} ИНН {ALPHA_INN})")),
        ("second.docx", _act("Копия акта № XZ-614", issuer=f"ООО Альфа ({role} ИНН {BETA_INN})")),
    ]
    assert sha256(records[0][1]).digest() != sha256(records[1][1]).digest()
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(records):
            result = _run_package(
                client,
                environment,
                [("documents", (name, content)) for name, content in order],
                100,
            )
            _assert_ambiguous(result)


def test_cli_direct_issuer_inns_remain_separate(tmp_path):
    records = [
        _cli_document(tmp_path, "first", "Акт № XZ-614", issuer=f"ООО Альфа (ИНН {ALPHA_INN})"),
        _cli_document(
            tmp_path, "second", "Копия акта № XZ-614", issuer=f"ООО Гамма (ИНН {BETA_INN})"
        ),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "correct"
        assert result["rows"][0]["expected_amount"] == "200.00"


def test_real_api_direct_issuer_inns_remain_separate(database_url, tmp_path):
    records = [
        ("first.docx", _act("Акт № XZ-614", issuer=f"ООО Альфа (ИНН {ALPHA_INN})")),
        ("second.docx", _act("Копия акта № XZ-614", issuer=f"ООО Гамма (ИНН {BETA_INN})")),
    ]
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(records):
            result = _run_package(
                client,
                environment,
                [("documents", (name, content)) for name, content in order],
                200,
            )
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            documents = [item for item in result["documents"] if item["role"] == "support"]
            assert row["status"] == "verified" and row["expected_value"] == "200.00"
            assert row["delta"] == "0.00"
            assert all(item["decision"]["state"] == "include" for item in documents)
            assert all(item["duplicate_of"] is None for item in documents)
