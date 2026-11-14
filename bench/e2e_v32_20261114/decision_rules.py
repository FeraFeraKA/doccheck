"""Deterministic document reconciliation. No model calls or oracle lookups.

The input consists exclusively of extracted facts and source-file identifiers.
Missing or ambiguous supporting facts produce ``unverified``, not a fabricated
financial discrepancy. Money is never evaluated with binary floating point.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import re
import unicodedata
from .document_identity import literal_id, validate_number_evidence


CATEGORIES = {"production_overhead", "general_admin", "payroll", "insurance", "other"}


def normalize_identifier(value):
    if value is None:
        return None
    # NFKC turns № into "No", so strip the label before Unicode normalization.
    raw = re.sub(r"^(?:№|номер\s*)\s*", "", str(value).strip(), flags=re.IGNORECASE)
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text or text.casefold() in {"null", "none", "unknown", "неизвестно"}:
        return None
    text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"}))
    text = re.sub(r"^(?:№|номер\s*)\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", text).casefold()


def parse_amount(value):
    """Normalize explicit decimal notation; never guess a missing digit/decimal."""
    if value is None or isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(?:руб\.?|рублей|rub|₽)$", "", text, flags=re.IGNORECASE)
    if "," in text and "." in text:
        # Accept unambiguous grouped numbers such as 1,234.56 or 1.234,56.
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        group_separator = "." if decimal_separator == "," else ","
        integer, fraction = text.rsplit(decimal_separator, 1)
        if not re.fullmatch(r"[+-]?\d{1,3}(?:" + re.escape(group_separator) + r"\d{3})+", integer):
            return None
        if not re.fullmatch(r"\d{1,2}", fraction):
            return None
        text = integer.replace(group_separator, "") + "." + fraction
    elif "," in text:
        text = text.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def normalize_category(value):
    text = str(value).strip().casefold() if value is not None else None
    return text if text in CATEGORIES else None


def money_string(value):
    if value is None:
        return None
    # This is display formatting only; comparison uses the exact Decimal value.
    return format(value, ".2f") if value == value.quantize(Decimal("0.01")) else format(value, "f")


def extract_facts(document):
    facts = document.get("prediction", document.get("fields", document))
    return facts if isinstance(facts, dict) else {}


def document_interval(facts):
    start, end = parse_date(facts.get("period_start")), parse_date(facts.get("period_end"))
    explicit_period = facts.get("period_start") is not None or facts.get("period_end") is not None
    if explicit_period:
        if start is None or end is None or end < start:
            return None, None, "invalid_or_incomplete_period"
        return start, end, None
    point = parse_date(facts.get("date"))
    return (point, point, None) if point else (None, None, "date_and_period_missing")


def completeness_issue(completeness, category):
    """Use explicit input declarations; never infer completeness from arithmetic.

    ``missing_categories`` is an exhaustive declaration of affected categories.
    Missing/malformed declarations conservatively apply to the whole package.
    This metadata belongs to the caller/user, never to model predictions.
    """
    if not isinstance(completeness, dict):
        return "completeness_unknown"
    basis = completeness.get("basis")
    if not isinstance(basis, str) or not basis.strip():
        return "completeness_basis_missing"
    status = completeness.get("status")
    missing = completeness.get("missing_categories", [])
    if not isinstance(missing, list) or any(not isinstance(x, str) or x not in CATEGORIES for x in missing):
        return "completeness_declaration_invalid"
    if status == "complete":
        return "completeness_declaration_conflicting" if missing else None
    if status == "incomplete":
        return "declared_incomplete_sources" if not missing or category in missing else None
    return "completeness_unknown"


def reconcile(documents, report_rows, contract_number, period_start, period_end, completeness=None):
    """Return source-backed category totals/statuses, with conservative abstention.

    ``documents``: list of {id, prediction:{...}, source_hash?}; duplicate id/hash
    occurrences are skipped. A business duplicate uses contract + document number
    + covered period/date + optional counterparty. Conflicting duplicate values
    make both affected categories unverified. The caller must not supply labels
    or the answer key as extracted facts.
    """
    target = normalize_identifier(contract_number)
    window_start, window_end = parse_date(period_start), parse_date(period_end)
    if not target or not window_start or not window_end or window_end < window_start:
        raise ValueError("A valid target contract and closed date interval are required")

    known = defaultdict(list)
    uncertain = defaultdict(list)
    global_uncertain = []
    exclusions, duplicates = [], []
    seen_sources, seen_business = {}, {}
    identity_contexts = defaultdict(list)
    identity_warnings = []

    def abstain(doc_id, category, reason, candidates=None):
        item = {"id": doc_id, "reason": reason}
        if category:
            uncertain[category].append(item)
        elif candidates:
            for candidate in candidates:
                uncertain[candidate].append(dict(item))
        else:
            global_uncertain.append(item)

    for index, document in enumerate(documents):
        doc_id = str(document.get("id", f"document-{index}"))
        facts = extract_facts(document)
        category = normalize_category(facts.get("category"))
        evidence = document.get("category_evidence") or {}
        raw_candidates = evidence.get("candidates")
        native_evidence = (evidence.get("version") == "native-purpose-v3.2"
            and evidence.get("source_verified") is True
            and isinstance(document.get("source_hash"), str) and bool(document["source_hash"])
            and evidence.get("source_hash") == document["source_hash"]
            and isinstance(document.get("source_native_text"), str)
            and evidence.get("native_text_sha256") == hashlib.sha256(document["source_native_text"].encode()).hexdigest())
        # Only the source-checking layer may bound an unknown category. Model
        # confidence or the model's own quotation does not establish this scope.
        candidates = (sorted(set(raw_candidates)) if isinstance(raw_candidates, list)
            and raw_candidates and all(isinstance(x, str) and x in CATEGORIES for x in raw_candidates)
            and native_evidence else None)
        if document.get("error"):
            abstain(doc_id, category, "extraction_error", candidates)
            continue
        source_key = ("hash", document["source_hash"]) if document.get("source_hash") else ("id", doc_id)
        if source_key in seen_sources:
            duplicates.append({"id": doc_id, "duplicate_of": seen_sources[source_key], "basis": source_key[0]})
            continue
        seen_sources[source_key] = doc_id

        contract = normalize_identifier(facts.get("contract_number"))
        if contract is None:
            abstain(doc_id, category, "contract_missing", candidates)
            continue
        if contract != target:
            exclusions.append({"id": doc_id, "reason": "different_contract"})
            continue
        start, end, interval_error = document_interval(facts)
        if interval_error:
            abstain(doc_id, category, interval_error, candidates)
            continue
        if end < window_start or start > window_end:
            exclusions.append({"id": doc_id, "reason": "outside_period"})
            continue
        if start < window_start or end > window_end:
            abstain(doc_id, category, "period_partially_overlaps_unallocatable_amount", candidates)
            continue
        if evidence.get("gate_applies") is True and not native_evidence:
            abstain(doc_id, None, "category_evidence_invalid")
            continue
        # The native evidence gate may retain a raw category for inspection
        # without treating it as a source-resolved financial allocation. Apply
        # this only after duplicate and contract/period exclusions above.
        if evidence.get("gate_applies") is True:
            usable = (evidence.get("financial_usable") is True
                and evidence.get("decision") in {"confirmed", "corrected"}
                and evidence.get("category") == category and category is not None)
            if not usable:
                reason = "category_not_source_resolved" if evidence.get("decision") == "unchecked" else "category_source_abstention"
                abstain(doc_id, None, reason, candidates)
                continue
        if category is None:
            abstain(doc_id, None, "category_missing_or_invalid", candidates)
            continue
        amount = parse_amount(facts.get("amount"))
        if amount is None:
            abstain(doc_id, category, "amount_missing_or_invalid")
            continue
        identity = validate_number_evidence(document)
        number = identity["number"] if identity["identity_usable"] else None
        raw_number = literal_id(document.get("raw_prediction", facts).get("doc_number"))
        possible_ids = {number} if number else set(identity["candidates"])
        if not number and raw_number and identity.get("raw_alias_allowed", True) and (raw_number in possible_ids or raw_number not in identity["non_own_candidates"]):
            possible_ids.add(raw_number)
        item = {"id": doc_id, "amount": amount, "category": category,
                "period_start": start.isoformat(), "period_end": end.isoformat(),
                "document_kind": identity.get("document_kind"), "issuer_key": identity.get("issuer_key")}
        context = (contract, start, end, normalize_identifier(facts.get("counterparty")))
        if number:
            # A full literal native ID is not normalized across scripts, case,
            # punctuation or prefixes. Both sides of this map are verified.
            key = (*context, number)
            previous = seen_business.get(key)
            if previous:
                context_conflict = [field for field in ("document_kind", "issuer_key")
                    if item[field] is not None and previous[field] is not None and item[field] != previous[field]]
                if context_conflict:
                    abstain(doc_id, category, "explicit_identity_context_conflict")
                    abstain(previous["id"], previous["category"], "explicit_identity_context_conflict")
                    identity_warnings.append({"id": doc_id, "related_id": previous["id"],
                        "reason": "explicit_identity_context_conflict", "conflicting_fields": context_conflict})
                else:
                    duplicates.append({"id": doc_id, "duplicate_of": previous["id"], "basis": "business_identity"})
                    if previous["amount"] != amount or previous["category"] != category:
                        abstain(doc_id, category, "conflicting_duplicate")
                        abstain(previous["id"], previous["category"], "conflicting_duplicate")
                    continue
        else:
            # Unresolved identity alone does not invalidate a known amount.
            # It supplies neither merge authority nor a verified uniqueness
            # claim; an actual collision below does require scoped review.
            identity_warnings.append({"id": doc_id, "reason": "business_identity_" + identity["status"]})
        for previous in identity_contexts[context]:
            if number and previous["number"]:
                continue  # Distinct source-confirmed full IDs are distinct.
            shared = possible_ids & previous["possible_ids"]
            reason = "unresolved_document_identity_collision" if shared else None
            if reason is None and amount == previous["item"]["amount"] and category == previous["item"]["category"]:
                proven = number or previous["number"]
                unchecked = previous["possible_ids"] if number else possible_ids
                if proven and not proven.isdecimal():
                    tail = re.search(r"\d+$", proven)
                    if tail and any(value.isdecimal() and value == tail.group() for value in unchecked):
                        # This is only suspicion in a matching monetary context,
                        # never a correction, equivalence or confirmed duplicate.
                        reason = "suspected_bare_tail_identity"
            if reason:
                abstain(doc_id, category, reason)
                abstain(previous["item"]["id"], previous["item"]["category"], reason)
                identity_warnings.append({"id": doc_id, "related_id": previous["item"]["id"], "reason": reason})
        if number:
            seen_business[key] = item
        identity_contexts[context].append({"item": item, "number": number, "possible_ids": possible_ids})
        known[category].append(item)

    rows = []
    for report_row in report_rows:
        category = normalize_category(report_row.get("category", report_row.get("article")))
        reported = parse_amount(report_row.get("reported_amount", report_row.get("amount")))
        supporting = known.get(category, [])
        partial = sum((item["amount"] for item in supporting), Decimal("0"))
        reasons = list(global_uncertain) + list(uncertain.get(category, []))
        completeness_reason = completeness_issue(completeness, category)
        if completeness_reason:
            reasons.append({"reason": completeness_reason, "basis":
                completeness.get("basis") if isinstance(completeness, dict) else None})
        if category is None:
            reasons.append({"reason": "report_category_missing_or_invalid"})
        if reported is None:
            reasons.append({"reason": "reported_amount_missing_or_invalid"})
        if not supporting:
            reasons.append({"reason": "no_supporting_documents"})
        verified = not reasons
        status = "unverified" if not verified else ("correct" if reported == partial else "incorrect")
        rows.append({
            "category": category,
            "reported_amount": money_string(reported),
            "expected_amount": money_string(partial) if verified else None,
            "partial_amount": money_string(partial),
            "delta": money_string(reported - partial) if verified else None,
            "status": status,
            "source_ids": [item["id"] for item in supporting],
            "reasons": reasons,
        })
    return {
        "rows": rows, "excluded_documents": exclusions, "duplicates": duplicates,
        "identity_warnings": identity_warnings,
        "completeness": completeness,
        "limitations": [
            "Completeness is an explicit user/profile declaration, not inferred or independently proven from an available partial sum.",
            "Business duplicate merging requires a source-verified full own number on both records plus matching contract, date/period and optional counterparty.",
            "Unresolved identity alone is a warning; a contextual collision is reviewed without merging. Bare-tail suspicion never authorizes identity equivalence.",
        ],
    }
