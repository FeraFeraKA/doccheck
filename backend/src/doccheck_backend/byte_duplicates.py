"""Plan exclusions for copies with the same verified SHA-256 within a run."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .contracts.result import FileDecision, SourceDocument


@dataclass(frozen=True)
class ByteDuplicate:
    duplicate_of: str
    decision: FileDecision


def plan_byte_duplicates(documents: Sequence[SourceDocument]) -> dict[str, ByteDuplicate]:
    """Return copy decisions without rewriting source records or evidence.

    Use verified digests of the stored bytes and stable IDs for one run.
    Choose the representative before attributing readings or building components.
    An explicitly designated report remains the representative of its group.
    """
    if len({document.id for document in documents}) != len(documents):
        raise ValueError("document IDs must be unique")
    if sum(document.role == "report" for document in documents) != 1:
        raise ValueError("the run must have exactly one designated report")
    if any(document.duplicate_of is not None for document in documents):
        raise ValueError("a run with existing copy decisions cannot be regrouped")

    by_digest: dict[str, list[SourceDocument]] = defaultdict(list)
    for document in documents:
        by_digest[document.sha256].append(document)

    copies: dict[str, ByteDuplicate] = {}
    for members in by_digest.values():
        if len(members) < 2:
            continue
        representative = min(members, key=lambda document: (document.role != "report", document.id))
        for document in members:
            if document.id == representative.id:
                continue
            message = (
                "Байты совпадают с выбранной КФЗ по SHA-256. "
                "Этот экземпляр остаётся в списке файлов и исключён из первичных документов."
                if representative.role == "report"
                else "Байты совпадают с другим экземпляром по SHA-256. Используется один экземпляр."
            )
            copies[document.id] = ByteDuplicate(
                duplicate_of=representative.id,
                decision=FileDecision(
                    state="exclude",
                    reason_code="byte_duplicate",
                    message=message,
                    evidence_refs=[],
                ),
            )
    return copies
