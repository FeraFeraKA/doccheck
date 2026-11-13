from hashlib import sha256

import pytest
from test_result_contract import payload as payload

from doccheck_backend.byte_duplicates import plan_byte_duplicates
from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import FileDecision, SourceDocument


def _document(
    identifier: str, content: bytes, *, name: str | None = None, role: str = "support"
) -> SourceDocument:
    return SourceDocument.model_validate(
        {
            "id": identifier,
            "name": name or identifier + ".pdf",
            "sha256": sha256(content).hexdigest(),
            "format": "pdf",
            "role": role,
            "parse_status": "pending",
            "decision": FileDecision(
                state="needs_review",
                reason_code="not_processed",
                message="Файл ожидает обработки.",
                evidence_refs=[],
            ),
            "errors": [],
        }
    )


def test_representative_is_stable_with_order_and_name_changes():
    report = _document("report", b"synthetic report", role="report")
    members = [
        _document("3", b"operation A: 42.30", name="a-first.pdf"),
        _document("1", b"operation A: 42.30", name="z-last.pdf"),
        _document("2", b"operation A: 42.30"),
    ]
    before = [item.model_dump() for item in members]
    planned = plan_byte_duplicates([report, *members])
    renamed = [
        item.model_copy(update={"name": "renamed-" + item.id + ".pdf"})
        for item in reversed(members)
    ]

    assert plan_byte_duplicates([*renamed, report]) == planned
    assert set(planned) == {"2", "3"}
    assert {copy.duplicate_of for copy in planned.values()} == {"1"}
    assert all(copy.decision.state == "exclude" for copy in planned.values())
    assert all(copy.decision.reason_code == "byte_duplicate" for copy in planned.values())
    assert all(copy.decision.evidence_refs == [] for copy in planned.values())
    assert [item.model_dump() for item in members] == before


def test_same_amount_is_not_a_byte_copy_and_mutated_copy_stays_separate():
    report = _document("report", b"synthetic report", role="report")
    first = _document("a", b"operation A: 42.30")
    equal_amount = _document("b", b"operation B: 42.30", name=first.name)
    copy = _document("c", b"operation A: 42.30")
    assert set(plan_byte_duplicates([report, first, equal_amount, copy])) == {"c"}

    mutated = _document("c", b"operation A: 42.31", name=copy.name)
    assert plan_byte_duplicates([report, first, equal_amount, mutated]) == {}


def test_report_is_retained_when_same_bytes_are_also_uploaded_as_primary():
    report = _document("z-report", b"same report and primary bytes", role="report")
    primary = _document("a-primary", b"same report and primary bytes")

    copies = plan_byte_duplicates([primary, report])
    assert set(copies) == {primary.id}
    assert copies[primary.id].duplicate_of == report.id
    assert "КФЗ" in copies[primary.id].decision.message
    assert "первичных документов" in copies[primary.id].decision.message


def test_copy_plan_fits_result_contract_and_keeps_addressed_operations(payload):
    documents = payload["result"]["documents"]
    previous_copy = next(item for item in documents if item["id"] == "ledger-copy")
    previous_copy["duplicate_of"] = None
    parsed = [SourceDocument.model_validate(item) for item in documents]
    copies = plan_byte_duplicates(parsed)
    for document in documents:
        if document["id"] in copies:
            copy = copies[document["id"]]
            document.update(duplicate_of=copy.duplicate_of, decision=copy.decision.model_dump())

    result = CheckJob.model_validate(payload).result
    assert result is not None
    assert {document.id for document in result.documents} == {document.id for document in parsed}
    assert result.rows[0].observed_evidence_sum == "120.50"
    addresses = {evidence.id: evidence for evidence in result.evidence}
    components = result.rows[0].calculation.components
    assert [component.amount_refs for component in components] == [["amount-1"], ["amount-2"]]
    assert all(
        addresses[reference].document_id == "ledger"
        for component in components
        for reference in component.amount_refs
    )


def test_rejects_existing_copy_decisions_and_duplicate_document_ids():
    report = _document("report", b"report", role="report")
    original = _document("a", b"shared")
    repeated_id = _document("a", b"other bytes")
    with pytest.raises(ValueError, match="document IDs must be unique"):
        plan_byte_duplicates([report, original, repeated_id])
    copy = _document("b", b"shared").model_copy(update={"duplicate_of": original.id})
    with pytest.raises(ValueError, match="existing copy decisions"):
        plan_byte_duplicates([report, original, copy])


@pytest.mark.parametrize("count", [0, 2])
def test_requires_one_designated_report(count: int):
    reports = [_document(str(i), b"bytes", role="report") for i in range(count)]
    with pytest.raises(ValueError, match="exactly one designated report"):
        plan_byte_duplicates(reports)
