"""Regressions for evidence provenance in the versioned result contract."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_result_contract import accepts_draft as accepts_draft
from test_result_contract import payload as payload

from doccheck_backend.contracts import CheckJob


def test_each_component_keeps_its_evidence_after_a_result_round_trip(payload, accepts_draft):
    result = payload["result"]
    row = result["rows"][0]
    components = row["calculation"]["components"]
    by_id = {item["id"]: item for item in result["evidence"]}
    by_id["amount-1"].update(raw_value="31,05", normalized_value="31.05")
    by_id["amount-2"].update(raw_value="72,15", normalized_value="72.15")
    components[0]["amount"] = "31.05"
    components[1]["amount"] = "72.15"
    row.update(observed_evidence_sum="103.20", expected_value="103.20", delta="47.30")
    result["documents"].reverse()
    result["evidence"].reverse()
    components.reverse()

    assert accepts_draft(payload)
    job = CheckJob.model_validate(payload)
    assert accepts_draft(job.model_dump(mode="json"))
    restored = CheckJob.model_validate_json(job.model_dump_json())
    assert restored.result is not None
    evidence = {item.id: item for item in restored.result.evidence}

    restored_row = restored.result.rows[0]
    assert restored_row.observed_evidence_sum == "103.20"
    assert restored_row.delta == "47.30"
    restored_components = restored_row.calculation.components
    assert [component.amount for component in restored_components] == ["72.15", "31.05"]
    for component, evidence_id, cell, raw in zip(
        restored_components,
        ["amount-2", "amount-1"],
        ["C7", "C6"],
        ["72,15", "31,05"],
        strict=True,
    ):
        assert component.amount_refs == [evidence_id]
        amount = evidence[evidence_id]
        assert (amount.id, amount.document_id, amount.raw_value, amount.normalized_value) == (
            evidence_id,
            "ledger",
            raw,
            component.amount,
        )
        assert amount.locator.model_dump() == {"kind": "sheet", "sheet": "Синтетика", "range": cell}
        references = [
            ("contract", "A2", component.contract_refs),
            ("period", "A3", component.period_refs),
            ("article", "A6:A7", component.article_refs),
        ]
        for kind, anchor, ids in references:
            assert ids == [kind]
            support = evidence[ids[0]]
            assert support.kind == kind
            assert support.document_id == amount.document_id
            assert support.locator.model_dump() == {
                "kind": "sheet",
                "sheet": "Синтетика",
                "range": anchor,
            }


def test_rejects_reused_evidence_id_even_with_different_locator(payload):
    result = payload["result"]
    evidence = next(item for item in result["evidence"] if item["id"] == "amount-1")
    shadow = deepcopy(evidence)
    shadow["locator"]["range"] = "D12"
    result["evidence"].append(shadow)

    with pytest.raises(ValidationError, match="document and evidence IDs must be unique"):
        CheckJob.model_validate(payload)


def test_rejects_a_component_amount_reference_missing_from_its_run(payload):
    component = payload["result"]["rows"][0]["calculation"]["components"][1]
    component["amount_refs"] = ["other-run-amount"]

    with pytest.raises(ValidationError, match="other-run-amount.*is missing"):
        CheckJob.model_validate(payload)
