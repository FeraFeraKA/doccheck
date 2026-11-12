"""Public boundary for observations supplied by a trusted local worker.

Parsers/OCR supply lines and their source digest. This module checks the file
still matches those observations, then applies the existing v5 identity policy.
It does not parse original formats, call OCR, or calculate a financial report.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import re

from .identity import identity_v2, identity_v3, identity_v4, identity_v5

RESULT_VERSION = "doccheck-ml-identity/1"
PREDICTION_FIELDS = {
    "doc_number", "verbatim_line", "contract_number", "date", "period_start",
    "period_end", "amount", "category", "description", "evidence_quote",
}
LINE_FIELDS = {"text", "page", "line", "cell", "sheet", "bbox", "score", "image"}


class InputError(ValueError):
    """Malformed worker input, distinct from a file or inference failure."""


@dataclass(frozen=True)
class DocumentInput:
    """Source observations, not ground truth or an HTTP upload payload.

    ``source_sha256`` is the digest at extraction time. ``native`` may only be
    used for actual native extraction, never OCR. Paths are trusted worker paths.
    Heterogeneous evidence dictionaries use object values and are checked below.
    """

    id: str
    source_path: Path
    source_sha256: str
    acquisition: str
    lines: list[dict[str, object]]
    prediction: dict[str, str | None] = field(default_factory=dict)


def _validate(document: DocumentInput) -> None:
    if not isinstance(document, DocumentInput):
        raise InputError("Every document must be a DocumentInput")
    if not isinstance(document.id, str) or not document.id.strip():
        raise InputError("A nonempty document ID is required")
    if not isinstance(document.source_path, Path):
        raise InputError("source_path must be a pathlib.Path")
    if not isinstance(document.source_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", document.source_sha256
    ):
        raise InputError("source_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(document.acquisition, str) or document.acquisition not in {"native", "scan"}:
        raise InputError("acquisition must be native or scan")
    if not isinstance(document.prediction, dict) or (
        set(document.prediction) - PREDICTION_FIELDS
    ) or any(value is not None and not isinstance(value, str)
             for value in document.prediction.values()):
        raise InputError("Prediction fields must be known strings or null")
    if not isinstance(document.lines, list):
        raise InputError("lines must be a list")
    for line in document.lines:
        if (not isinstance(line, dict) or set(line) - LINE_FIELDS
                or not isinstance(line.get("text"), str)):
            raise InputError("Every source line needs text and known evidence fields")
        for key in ("page", "line"):
            if key in line and (type(line[key]) is not int or line[key] < 1):
                raise InputError("Source page and line numbers start at one")
        for key in ("cell", "sheet", "image"):
            if key in line and not isinstance(line[key], str):
                raise InputError("Source address fields must be strings")
        if "bbox" in line:
            box = line["bbox"]
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           for v in box)
                    or box[0] < 0 or box[1] < 0
                    or box[2] <= box[0] or box[3] <= box[1]):
                raise InputError("bbox must contain four ordered finite coordinates")
        if "score" in line and (type(line["score"]) not in (int, float)
                                or not math.isfinite(line["score"])):
            raise InputError("Source score must be finite")


def process_documents(
    documents: Sequence[DocumentInput], *, synthetic: bool = False
) -> dict[str, object]:
    """Apply identity rules without loading a model or changing source files.

    Invalid input raises InputError before processing. Unreadable/changed files
    are reported individually and excluded from groups, never treated as empty
    documents. No additional reader evidence means uncertain numbers stay in
    review. Output is a module result, not the project's financial CheckResult.
    """
    if type(synthetic) is not bool:
        raise InputError("synthetic must be a boolean")
    if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
        raise InputError("documents must be a sequence")
    inputs = deepcopy(list(documents))
    for document in inputs:
        _validate(document)
    if len({document.id for document in inputs}) != len(inputs):
        raise InputError("Duplicate document IDs")
    records, errors = [], []
    for document in inputs:
        try:
            with document.source_path.open("rb") as source:
                current_sha = hashlib.file_digest(source, "sha256").hexdigest()
        except OSError:
            errors.append({"id": document.id, "code": "source_unavailable"})
            continue
        if current_sha != document.source_sha256:
            errors.append({"id": document.id, "code": "source_changed"})
            continue
        original = identity_v2.resolve_document(
            document.id, current_sha, document.acquisition,
            document.lines, document.prediction,
        )
        baseline = identity_v3.evaluate_arms(original, None)["combined"]
        a2 = identity_v4.evaluate_arms(baseline)["A2"]
        records.append(identity_v5.resolve_document(baseline, a2))
    return {
        "schema_version": RESULT_VERSION,
        "module_version": "0.1.0",
        "policy_version": identity_v5.VERSION,
        "synthetic": synthetic,
        "status": "partial" if errors else "completed",
        "records": records,
        "errors": errors,
        "groups": identity_v5.group_documents(records),
        "review_queue": identity_v5.review_queue(records),
        "inference_performed": False,
        "financial_reconciliation_performed": False,
    }
