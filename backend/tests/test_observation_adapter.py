import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from doccheck_backend import observation_adapter as adapter
from doccheck_backend.contracts.locators import PageLocator, ParagraphLocator, SheetLocator
from doccheck_backend.observation_adapter import (
    IdentityResponseError,
    ObservationInputError,
    ObservedDocument,
    SourceObservation,
    identify_documents,
)


@pytest.fixture
def module_path(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "ml_module" / "src"
    monkeypatch.syspath_prepend(str(path))
    assert str(path) in sys.path


def _document(tmp_path: Path, document_id: str = "demo") -> ObservedDocument:
    path = tmp_path / document_id
    data = b"synthetic source bytes"
    path.write_bytes(data)
    return ObservedDocument(
        document_id,
        path,
        sha256(data).hexdigest(),
        "pdf",
        (
            SourceObservation("Акт № 321", PageLocator(kind="page", page=1, line=1), "native"),
            SourceObservation(
                "Сумма: 75,00 руб.",
                PageLocator(
                    kind="page",
                    page=1,
                    line=2,
                    bbox=(0.1, 0.2, 0.3, 0.4),
                    fragment_id="original-source",
                ),
                "native",
            ),
        ),
    )


def test_real_identity_retains_candidate_value_address_and_native_method(module_path, tmp_path):
    document = _document(tmp_path)
    result = identify_documents([document], synthetic=True)
    assert result.synthetic is True
    assert result.module_version == "0.1.0"
    assert result.policy_version.startswith("identity-v5")
    assert result.errors == ()
    (record,) = result.documents
    assert record.number_status == "native_source"
    assert not record.number_requires_review
    assert record.source_sha256 == document.source_sha256
    amount = next(item for item in record.candidates if item.field == "amount")
    assert amount.value == "75.00"
    assert amount.sources == (document.observations[1],)
    assert amount.sources[0].locator.fragment_id == "original-source"
    assert not amount.source_ambiguous


def test_mixed_input_is_scan_without_discarding_per_fragment_origin(module_path, tmp_path):
    document = _document(tmp_path)
    native, amount = document.observations
    scan = replace(amount, method="ocr")
    result = identify_documents([replace(document, observations=(native, scan))], synthetic=True)
    (record,) = result.documents
    assert record.acquisition == "scan"
    assert record.number_status == "ocr_source_only"
    assert record.number_requires_review
    number = next(item for item in record.candidates if item.field == "doc_number")
    assert number.sources == (native,)
    assert next(item for item in record.candidates if item.field == "amount").sources == (scan,)


def test_real_module_preserves_exact_byte_groups_and_per_file_errors(module_path, tmp_path):
    valid = _document(tmp_path, "valid")
    duplicate = _document(tmp_path, "duplicate")
    moved = _document(tmp_path, "absent")
    moved.source_path.unlink()
    changed = _document(tmp_path, "changed")
    changed.source_path.write_bytes(b"changed")

    result = identify_documents([valid, changed, duplicate, moved], synthetic=True)
    assert {item.id for item in result.documents} == {"valid", "duplicate"}
    assert {frozenset(group) for group in result.duplicate_groups} == {
        frozenset({"valid", "duplicate"})
    }
    assert {(item.document_id, item.code) for item in result.errors} == {
        ("changed", "source_changed"),
        ("absent", "source_unavailable"),
    }


def test_docx_unique_location_is_restored_and_duplicate_text_stays_ambiguous(module_path, tmp_path):
    document = _document(tmp_path)
    observations = (
        SourceObservation("Акт № 321", ParagraphLocator(kind="paragraph", paragraph=1), "native"),
        SourceObservation(
            "Сумма: 75,00 руб.", ParagraphLocator(kind="paragraph", paragraph=2), "native"
        ),
        SourceObservation(
            "Сумма: 75,00 руб.", ParagraphLocator(kind="paragraph", paragraph=3), "native"
        ),
    )
    real = replace(document, format="docx", observations=observations)
    (record,) = identify_documents([real], synthetic=True).documents
    number = next(item for item in record.candidates if item.field == "doc_number")
    amount = next(item for item in record.candidates if item.field == "amount")
    assert number.sources == (observations[0],)
    assert amount.value == "75.00" and amount.sources == () and amount.source_ambiguous


def test_prediction_without_evidence_does_not_become_addressed_amount(module_path, tmp_path):
    document = _document(tmp_path)
    supplied = replace(
        document, observations=document.observations[:1], prediction={"amount": "25.01"}
    )
    (record,) = identify_documents([supplied], synthetic=True).documents
    amount = next(item for item in record.candidates if item.field == "amount")
    assert amount.value == "25.01"
    assert amount.sources == ()


def test_preserves_known_xlsx_inventory_and_precise_cells(module_path, tmp_path):
    document = _document(tmp_path)
    locator = SheetLocator(kind="sheet", sheet="Demo", range="B2")
    observation = SourceObservation("Сумма: 0,00 руб.", locator, "native")
    xlsx = replace(
        document,
        format="xlsx",
        observations=(observation,),
        sheet_names=frozenset({"Demo"}),
    )
    (record,) = identify_documents([xlsx], synthetic=True).documents
    amount = next(item for item in record.candidates if item.field == "amount")
    assert amount.value == "0.00"
    assert amount.sources == (observation,)
    assert not amount.source_ambiguous


@pytest.mark.parametrize(
    "error", ["duplicates", "wrong_format", "png_page", "xlsx_sheet", "bounds"]
)
def test_rejects_invalid_input_before_loading_module(monkeypatch, tmp_path, error):
    monkeypatch.setattr(adapter, "_load_identity", lambda: pytest.fail("loaded module too early"))
    document = _document(tmp_path)
    source = document.observations[0]
    addressed = replace(source, locator=SheetLocator(kind="sheet", sheet="Unknown", range="B2"))
    match error:
        case "duplicates":
            inputs = [document, document]
        case "wrong_format":
            inputs = [replace(document, observations=(addressed,))]
        case "png_page":
            wrong_page = replace(source, locator=PageLocator(kind="page", page=2, line=1))
            inputs = [replace(document, format="png", observations=(wrong_page,))]
        case "xlsx_sheet":
            inputs = [replace(document, format="xlsx", observations=(addressed,))]
        case _:
            bad_box = source.locator.model_copy(update={"bbox": (0, 0, 1.1, 1)})
            inputs = [replace(document, observations=(replace(source, locator=bad_box),))]
    with pytest.raises(ObservationInputError):
        identify_documents(inputs, synthetic=True)


def test_rejects_mismatched_source_digest_in_response(module_path, monkeypatch, tmp_path):
    from doccheck_ml import DocumentInput, InputError, process_documents

    def invalid(documents, *, synthetic):
        result = process_documents(documents, synthetic=synthetic)
        result["records"][0]["source_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(adapter, "_load_identity", lambda: (DocumentInput, invalid, InputError))
    with pytest.raises(IdentityResponseError, match="source does not match"):
        identify_documents([_document(tmp_path)], synthetic=True)
