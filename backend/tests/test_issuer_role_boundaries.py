"""Synthetic source-role boundaries for issuer INN comparisons."""

import io
from hashlib import sha256
from itertools import permutations

import pytest
from docx import Document
from test_copy_header_identity import _act, _cli_document, _reconcile_cli, _synthetic_inn
from test_issuer_spelling_identity import _environment, _run_package
from test_scaffold_integration import running_api

ALPHA_INN = _synthetic_inn("012345678")
BETA_INN = _synthetic_inn("098765432")
OTHER_ROLES = ("заказчика", "покупателя", "получателя", "плательщика", "клиента", "доверителя")


def _assert_ambiguous(result):
    row = next(item for item in result["rows"] if item["id"] == "general_admin")
    documents = [item for item in result["documents"] if item["role"] == "support"]
    assert row["status"] == "unverified"
    assert row["expected_value"] is None and row["delta"] is None
    assert row["observed_evidence_sum"] is None and row["calculation"]["components"] == []
    assert all(item["duplicate_of"] is None for item in documents)
    assert all(item["decision"]["state"] == "needs_review" for item in documents)
    evidence = {item["id"]: item for item in result["evidence"]}
    for document in documents:
        refs = [evidence[ref] for ref in document["decision"]["evidence_refs"]]
        assert any(
            item["kind"] == "document_identity"
            and item["normalized_value"] == "XZ-614"
            and item["locator"] == {"kind": "paragraph", "paragraph": 1}
            for item in refs
        )
        assert all(
            item["normalized_value"] not in {ALPHA_INN, BETA_INN}
            for item in refs
            if item["kind"] == "document_identity"
        )


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_cli_other_party_inn_is_not_attributed_to_issuer(tmp_path, role):
    records = [
        _cli_document(
            tmp_path,
            "first",
            "Акт № XZ-614",
            issuer=f"ООО Альфа, реквизиты {role}: ИНН {ALPHA_INN}",
        ),
        _cli_document(
            tmp_path,
            "second",
            "Копия акта № XZ-614",
            issuer=f"ООО Альфа, реквизиты {role}: ИНН {BETA_INN}",
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
def test_cli_declined_role_without_requisites_label_still_blocks_attribution(tmp_path, role):
    records = [
        _cli_document(
            tmp_path, "first", "Акт № XZ-614", issuer=f"ООО Альфа, {role} ИНН {ALPHA_INN}"
        ),
        _cli_document(
            tmp_path, "second", "Копия акта № XZ-614", issuer=f"ООО Альфа, {role} ИНН {BETA_INN}"
        ),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "100.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "unverified"
        assert result["rows"][0]["source_ids"] == []


def test_cli_inn_inside_quoted_company_text_is_not_a_requisite(tmp_path):
    records = [
        _cli_document(tmp_path, "first", "Акт № XZ-614", issuer=f"ООО «Альфа ИНН {ALPHA_INN}»"),
        _cli_document(tmp_path, "second", "Акт № XZ-614", issuer=f"ООО «Альфа ИНН {BETA_INN}»"),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "100.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "unverified"
        assert result["rows"][0]["source_ids"] == []


def test_cli_quoted_other_role_is_not_an_issuer_name(tmp_path):
    records = [
        _cli_document(
            tmp_path, "first", "Акт № XZ-614", issuer=f"ООО Альфа «заказчика» ИНН {ALPHA_INN}"
        ),
        _cli_document(
            tmp_path, "second", "Акт № XZ-614", issuer=f"ООО Альфа «заказчика» ИНН {BETA_INN}"
        ),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "100.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "unverified"
        assert result["rows"][0]["source_ids"] == []


@pytest.mark.parametrize("role", OTHER_ROLES)
@pytest.mark.parametrize("with_requisites", [False, True])
def test_real_api_other_party_inn_requires_review_in_both_orders(
    database_url, tmp_path, role, with_requisites
):
    qualifier = "реквизиты " if with_requisites else ""
    records = [
        (
            "first.docx",
            _act("Акт № XZ-614", issuer=f"ООО Альфа, {qualifier}{role}: ИНН {ALPHA_INN}"),
        ),
        (
            "second.docx",
            _act("Копия акта № XZ-614", issuer=f"ООО Альфа, {qualifier}{role}: ИНН {BETA_INN}"),
        ),
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


@pytest.mark.parametrize("separate_paragraph", [False, True])
def test_cli_valid_issuer_inn_with_separate_buyer_remains_usable(tmp_path, separate_paragraph):
    records = []
    for identifier, own, buyer in (("first", ALPHA_INN, BETA_INN), ("second", BETA_INN, ALPHA_INN)):
        buyer_text = f"Заказчик: ООО Клиент (ИНН {buyer})"
        issuer = f"ООО Альфа (ИНН {own})"
        if not separate_paragraph:
            issuer += "; " + buyer_text
        records.append(
            _cli_document(
                tmp_path,
                identifier,
                "Акт № XZ-614",
                issuer=issuer,
                extra=buyer_text if separate_paragraph else None,
            )
        )
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "correct"
        assert result["rows"][0]["expected_amount"] == "200.00"
        assert set(result["rows"][0]["source_ids"]) == {"first", "second"}


@pytest.mark.parametrize("separate_paragraph", [False, True])
def test_real_api_valid_issuer_inn_with_separate_buyer_remains_usable(
    database_url, tmp_path, separate_paragraph
):
    records = []
    for identifier, own, buyer in (("first", ALPHA_INN, BETA_INN), ("second", BETA_INN, ALPHA_INN)):
        buyer_text = f"Заказчик: ООО Клиент (ИНН {buyer})"
        issuer = f"ООО Альфа (ИНН {own})"
        if not separate_paragraph:
            issuer += "; " + buyer_text
        doc = Document(io.BytesIO(_act("Акт № XZ-614", issuer=issuer)))
        if separate_paragraph:
            doc.add_paragraph(buyer_text)
        buffer = io.BytesIO()
        doc.save(buffer)
        records.append((f"{identifier}.docx", buffer.getvalue()))
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
            assert all(item["decision"]["state"] == "include" for item in documents)
            assert all(item["duplicate_of"] is None for item in documents)


@pytest.mark.parametrize(
    "name", ["ООО «Заказчик»", "ООО Информационные системы", "ООО «Альфа:Сервис»"]
)
def test_cli_role_words_or_colon_inside_issuer_name_do_not_block_direct_inn(tmp_path, name):
    records = [
        _cli_document(tmp_path, "first", "Акт № XZ-614", issuer=f"{name} (ИНН {ALPHA_INN})"),
        _cli_document(tmp_path, "second", "Акт № XZ-614", issuer=f"{name} (ИНН {BETA_INN})"),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["rows"][0]["status"] == "correct"
        assert set(result["rows"][0]["source_ids"]) == {"first", "second"}


@pytest.mark.parametrize(
    "name", ["ООО «Заказчик»", "ООО Информационные системы", "ООО «Альфа:Сервис»"]
)
def test_real_api_quoted_issuer_name_does_not_block_direct_inn(database_url, tmp_path, name):
    records = [
        ("first.docx", _act("Акт № XZ-614", issuer=f"{name} (ИНН {ALPHA_INN})")),
        ("second.docx", _act("Акт № XZ-614", issuer=f"{name} (ИНН {BETA_INN})")),
    ]
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        for order in permutations(records):
            result = _run_package(
                client,
                environment,
                [("documents", (filename, content)) for filename, content in order],
                200,
            )
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            assert row["status"] == "verified" and row["expected_value"] == "200.00"


def test_real_api_invalid_issuer_inns_require_review(database_url, tmp_path):
    records = [
        ("first.docx", _act("Акт № XZ-614", issuer="ООО Альфа (ИНН 7700000000)")),
        ("second.docx", _act("Копия акта № XZ-614", issuer="ООО Альфа (ИНН 7800000000)")),
    ]
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
