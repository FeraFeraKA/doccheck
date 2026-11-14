"""Synthetic issuer ambiguity and source-attributed taxpayer identifiers."""

import io
from hashlib import sha256
from itertools import permutations
from uuid import uuid4

import pytest
from bench.e2e_v32_20261114.explanations import explain
from docx import Document
from test_copy_header_identity import _act, _cli_document, _reconcile_cli, _synthetic_inn
from test_issuer_spelling_identity import _environment, _run_package
from test_scaffold_integration import running_api

from doccheck_backend.contracts.locators import ParagraphLocator
from doccheck_backend.evidence_binding import ManifestDocument, bind_observations
from doccheck_backend.grounded_amounts import ground_document
from doccheck_backend.native_reader import read_native_document
from doccheck_backend.v32_processor import _identity_collisions

ALPHA_INN = _synthetic_inn("012345678")
BETA_INN = _synthetic_inn("098765432")
AMBIGUOUS_NAMES = [
    ("ООО Альфа, г. Москва", "Общество с ограниченной ответственностью Альфа г. Москва"),
    ("ООО Северо-Запад", "Общество с ограниченной ответственностью Северо Запад"),
    ("ООО Альфа", "ООО Гамма"),
]


@pytest.mark.parametrize(("first_issuer", "second_issuer"), AMBIGUOUS_NAMES)
def test_cli_names_alone_do_not_establish_independent_operations(
    tmp_path, first_issuer, second_issuer
):
    records = [
        _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=first_issuer),
        _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=second_issuer),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "100.00")
        row = result["rows"][0]
        assert result["duplicates"] == []
        assert row["status"] == "unverified" and row["source_ids"] == []
        assert row["expected_amount"] is None and row["delta"] is None


@pytest.mark.parametrize(("first_issuer", "second_issuer"), AMBIGUOUS_NAMES[:2])
def test_cli_three_names_without_attributed_inn_remain_unverified_in_every_order(
    tmp_path, first_issuer, second_issuer
):
    records = [
        _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=first_issuer),
        _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=second_issuer),
        _cli_document(tmp_path, "third", "Акт № ACT-71", issuer="ООО Гамма"),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "unverified"
        assert result["rows"][0]["source_ids"] == []


@pytest.mark.parametrize(("first_issuer", "second_issuer"), AMBIGUOUS_NAMES[:2])
def test_real_api_names_alone_require_review_in_both_orders(
    database_url, tmp_path, first_issuer, second_issuer
):
    records = [
        ("first.docx", _act("Акт № ACT-71", issuer=first_issuer)),
        ("second.docx", _act("Акт № ACT-71", issuer=second_issuer)),
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
            row = next(item for item in result["rows"] if item["id"] == "general_admin")
            supports = [item for item in result["documents"] if item["role"] == "support"]
            assert row["status"] == "unverified"
            assert row["expected_value"] is None and row["delta"] is None
            assert row["observed_evidence_sum"] is None
            assert all(item["duplicate_of"] is None for item in supports)
            assert all(item["decision"]["state"] == "needs_review" for item in supports)


@pytest.mark.parametrize(("first_issuer", "second_issuer"), AMBIGUOUS_NAMES[:2])
def test_real_api_three_names_without_attributed_inn_remain_unverified(
    database_url, tmp_path, first_issuer, second_issuer
):
    records = [
        ("first.docx", _act("Акт № ACT-71", issuer=first_issuer)),
        ("second.docx", _act("Акт № ACT-71", issuer=second_issuer)),
        ("third.docx", _act("Акт № ACT-71", issuer="ООО Гамма")),
    ]
    environment = _environment(database_url, tmp_path)
    with running_api(database_url, environment=environment) as client:
        result = _run_package(
            client, environment, [("documents", (name, content)) for name, content in records], 200
        )
    row = next(item for item in result["rows"] if item["id"] == "general_admin")
    supports = [item for item in result["documents"] if item["role"] == "support"]
    assert row["status"] == "unverified" and row["expected_value"] is None
    assert row["calculation"]["components"] == []
    assert all(item["duplicate_of"] is None for item in supports)
    assert all(item["decision"]["state"] == "needs_review" for item in supports)


def test_native_issuer_inn_has_attributed_source_address(tmp_path):
    path = tmp_path / "source.docx"
    path.write_bytes(_act("Акт № ACT-71", issuer=f"ООО Альфа (ИНН {ALPHA_INN})"))
    result = ground_document(
        uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
    )
    assert result.issuer_tax_id == ALPHA_INN
    assert result.issuer_locator == ParagraphLocator(kind="paragraph", paragraph=2)
    observations = read_native_document(path, "docx").observations
    source = next(item for item in observations if item.locator == result.issuer_locator)
    assert source.raw_text.startswith("Исполнитель:") and ALPHA_INN in source.raw_text
    assert all(
        assertion.normalized_value != ALPHA_INN
        for assertion in result.assertions
        if assertion.kind == "document_identity"
    )


@pytest.mark.parametrize("issuer", ["ООО Альфа (ИНН 7700000000)", "ООО Альфа (ИНН 7800000000)"])
def test_invalid_inn_is_not_a_trusted_issuer_identity(tmp_path, issuer):
    path = tmp_path / "source.docx"
    path.write_bytes(_act("Акт № ACT-71", issuer=issuer))
    result = ground_document(
        uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
    )
    assert result.issuer_tax_id is None and result.issuer_locator is None


def test_unattributed_inn_does_not_establish_issuer_identity(tmp_path):
    path = tmp_path / "source.docx"
    doc = Document(io.BytesIO(_act("Акт № ACT-71", issuer="ООО Альфа")))
    doc.add_paragraph(f"Заказчик: ООО Покупатель (ИНН {ALPHA_INN})")
    doc.save(path)
    result = ground_document(
        uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
    )
    assert result.issuer_tax_id is None and result.issuer_locator is None


def test_native_issuer_inn_is_not_replaced_by_the_buyers_inn(tmp_path):
    path = tmp_path / "source.docx"
    doc = Document(io.BytesIO(_act("Акт № ACT-71", issuer=f"ООО Альфа (ИНН {ALPHA_INN})")))
    doc.add_paragraph(f"Заказчик: ООО Покупатель (ИНН {BETA_INN})")
    doc.save(path)
    result = ground_document(
        uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
    )
    assert result.issuer_tax_id == ALPHA_INN
    assert result.issuer_locator == ParagraphLocator(kind="paragraph", paragraph=2)


@pytest.mark.parametrize(
    "issuer",
    [
        f"ООО Альфа (ИНН {ALPHA_INN}x)",
        f"ООО Альфа; ИНН {ALPHA_INN}",
        f"ООО Альфа, заказчик ООО Бета (ИНН {ALPHA_INN})",
        f"ООО Альфа (ИНН {ALPHA_INN}, ИНН {BETA_INN})",
    ],
)
def test_ambiguous_or_unbound_inn_does_not_establish_issuer_identity(tmp_path, issuer):
    path = tmp_path / "source.docx"
    path.write_bytes(_act("Акт № ACT-71", issuer=issuer))
    result = ground_document(
        uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
    )
    assert result.issuer_tax_id is None and result.issuer_locator is None


def test_unbound_source_hash_cannot_prove_distinct_issuers(tmp_path):
    run_id = uuid4()
    grounds, manifests, assertions = {}, [], []
    for i, inn in enumerate((ALPHA_INN, BETA_INN)):
        path = tmp_path / f"source-{i}.docx"
        path.write_bytes(_act("Акт № ACT-71", issuer=f"ООО Альфа (ИНН {inn})"))
        digest, document_id = sha256(path.read_bytes()).hexdigest(), uuid4().hex
        source = ground_document(run_id, document_id, path, "docx", digest)
        assert source.issuer_locator == ParagraphLocator(kind="paragraph", paragraph=2)
        grounds[document_id] = source
        manifests.append(ManifestDocument(document_id, digest, "docx", "supporting"))
        assertions.extend(source.assertions)

    bound = bind_observations(run_id, manifests, assertions)
    assert _identity_collisions(grounds, bound.evidence) == set()
    mismatched = [manifests[0], ManifestDocument(manifests[1].id, "0" * 64, "docx", "supporting")]
    bound = bind_observations(run_id, mismatched, assertions)
    assert _identity_collisions(grounds, bound.evidence) == set(grounds)


def test_cli_invalid_source_gate_cannot_establish_distinct_issuer(tmp_path):
    first = _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=f"ООО Альфа (ИНН {ALPHA_INN})")
    second = _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=f"ООО Альфа (ИНН {BETA_INN})")
    second["number_evidence"]["native_text_sha256"] = "0" * 64
    for order in permutations((first, second)):
        result = _reconcile_cli(list(order), "200.00")
        assert result["rows"][0]["status"] == "unverified"
        assert result["rows"][0]["expected_amount"] is None
        assert "second" not in result["rows"][0]["source_ids"]


def test_cli_distinct_attributed_inns_keep_same_named_issuers_separate(tmp_path):
    records = [
        _cli_document(tmp_path, "first", "Акт № ACT-71", issuer=f"ООО Альфа (ИНН {ALPHA_INN})"),
        _cli_document(tmp_path, "second", "Акт № ACT-71", issuer=f"ООО Альфа (ИНН {BETA_INN})"),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "correct"
        assert result["rows"][0]["expected_amount"] == "200.00"
        assert set(result["rows"][0]["source_ids"]) == {"first", "second"}
        decisions = {
            item["document_id"]: item
            for item in explain({"id": "report"}, list(order), result)["document_decisions"]
        }
        for record, inn in zip(records, (ALPHA_INN, BETA_INN), strict=True):
            issuer = [
                item for item in decisions[record["id"]]["evidence"] if item["kind"] == "issuer"
            ]
            assert len(issuer) == 1 and inn in issuer[0]["text"]
            address = issuer[0]["locator"]
            assert (
                record["source_native_text"][
                    address["source_char_start"] : address["source_char_end"]
                ]
                == issuer[0]["text"]
            )


@pytest.mark.parametrize("other_party_inn", [False, True])
def test_cli_attributed_issuer_inns_do_not_require_a_known_legal_form(tmp_path, other_party_inn):
    records = [
        _cli_document(
            tmp_path,
            "first",
            "Акт № ACT-71",
            issuer=f"Организация Альфа (ИНН {ALPHA_INN})",
            extra=f"Заказчик: ООО Клиент (ИНН {BETA_INN})" if other_party_inn else None,
        ),
        _cli_document(
            tmp_path,
            "second",
            "Акт № ACT-71",
            issuer=f"Организация Гамма (ИНН {BETA_INN})",
        ),
    ]
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["duplicates"] == []
        assert result["rows"][0]["status"] == "correct"
        assert set(result["rows"][0]["source_ids"]) == {"first", "second"}


def test_distinct_attributed_person_inns_are_read_in_cli_and_native_source(tmp_path):
    records = []
    for identifier, inn in (("first", "014234567800"), ("second", "012345678943")):
        record = _cli_document(tmp_path, identifier, "Акт № ACT-71", issuer=f"ИП Альфа (ИНН {inn})")
        path = tmp_path / f"{identifier}.docx"
        source = ground_document(
            uuid4(), uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
        )
        assert source.issuer_tax_id == inn
        assert source.issuer_locator == ParagraphLocator(kind="paragraph", paragraph=2)
        records.append(record)
    for order in permutations(records):
        result = _reconcile_cli(list(order), "200.00")
        assert result["rows"][0]["status"] == "correct"
        assert set(result["rows"][0]["source_ids"]) == {"first", "second"}
        assert result["duplicates"] == []


def test_real_api_distinct_valid_inns_are_attributed_to_source_fields(database_url, tmp_path):
    records = [
        ("first.docx", _act("Акт № ACT-71", issuer=f"ООО Альфа (ИНН {ALPHA_INN})")),
        ("second.docx", _act("Акт № ACT-71", issuer=f"ООО Альфа (ИНН {BETA_INN})")),
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
            assert row["status"] == "verified" and row["expected_value"] == "200.00"
            assert len(row["calculation"]["components"]) == 2
            docs = {item["name"]: item for item in result["documents"] if item["role"] == "support"}
            evidence = {item["id"]: item for item in result["evidence"]}
            for name, inn in (("first.docx", ALPHA_INN), ("second.docx", BETA_INN)):
                document = docs[name]
                assert document["decision"]["state"] == "include"
                assert document["duplicate_of"] is None
                preview = client.get(
                    f"/api/v0/runs/{result['run_id']}/documents/{document['id']}/preview"
                )
                assert preview.status_code == 200
                block = next(
                    item for item in preview.json()["blocks"] if item.get("paragraph") == 2
                )
                assert block["text"].startswith("Исполнитель:") and inn in block["text"]
                refs = [evidence[ref] for ref in document["decision"]["evidence_refs"]]
                assert all(
                    item["normalized_value"] != inn
                    for item in refs
                    if item["kind"] == "document_identity"
                )
