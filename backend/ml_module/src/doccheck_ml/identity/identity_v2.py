"""Source-backed identifiers and conservative, explainable duplicate decisions.

No model calls, labels, learned prefix dictionary, or fuzzy automatic merges.
``value`` is a proposal; ``usable_value`` requires an unambiguous source anchor.
OCR corroboration is not proof of identity. Only exact file bytes or complete
native content with consistent, fully source-supported identity can auto-group.
All source files/versions are retained.
"""
from __future__ import annotations

import re
import unicodedata
from itertools import combinations

from .parsing import parse_amount, parse_date

VERSION = "identity-v2.1"
DASHES = str.maketrans({ch: "-" for ch in "–—−‑‐‒―"})
MISSING_VALUES = {"не указан", "не указана", "не указано", "отсутствует", "нет", "n/a", "null", "none", "-", "?"}
GLYPHS = str.maketrans(dict(zip("АВЕКМНОРСТХ", "ABEKMHOPCTX")))
NUMBER_MARK = r"(?:№|N(?:[oоº°])?\.?(?=\s|\d|$))"
DATE_PATTERN = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})"
FIELD_START = re.compile(r"^(?:дата|договор|контракт|проект|период|сумма|итого|исполнитель|поставщик|заказчик|получатель|содержание|назначение|артикул|код\s+контрагента|бланк|форма|инн|кпп|номер\s+договора)\b", re.I)
TYPE_PATTERNS = [
    ("invoice_act", r"сч[её]т\s*[-–]\s*акт"),
    ("upd", r"универсальн\w*\s+передаточн\w*\s+документ|^упд\b"),
    ("memo", r"служебн\w*\s+записк"),
    ("insurance_calculation", r"расч[её]т\s+страховых\s+взносов"),
    ("payroll", r"(?:расч[её]тн\w*|плат[её]жн\w*)\s+ведомость|ведомость\s+начислений"),
    ("certificate", r"справка"),
    ("invoice", r"^сч[её]т\b"),
    ("act", r"^(?:акт|akt)\b"),
]


def norm(value: object) -> str | None:
    if value is None:
        return None
    s = unicodedata.normalize("NFC", str(value)).translate(DASHES).strip()
    if re.sub(r"\s+", " ", s).casefold() in MISSING_VALUES:
        return None
    s = re.sub(r"\s+", "", s).upper()
    return s or None


def visual_key(value: object) -> str | None:
    """Candidate retrieval only. Never used as an automatic-merge identity."""
    s = norm(value)
    return s.translate(GLYPHS) if s else None


def clean_line(text: object) -> str:
    return re.sub(r"^[A-Z]{1,3}\d+:\s*", "", str(text).strip())


def evidence(line: dict) -> dict:
    return {k: line[k] for k in ("text", "page", "line", "cell", "sheet", "bbox", "score", "image") if k in line}


def _cell_position(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)", value)
    if not match:
        return None
    column = 0
    for letter in match[1].upper():
        column = column * 26 + ord(letter) - ord("A") + 1
    return column, int(match[2])


def _adjacent_source_lines(first: dict, second: dict) -> bool:
    """Require a shared location and reject gaps in supplied line/cell addresses."""
    page, sheet = first.get("page"), first.get("sheet")
    if not ((type(page) is int and page > 0)
            or (isinstance(sheet, str) and sheet.strip())):
        return False
    if any(first.get(key) != second.get(key) for key in ("page", "sheet")):
        return False
    if "line" in first or "line" in second:
        if (type(first.get("line")) is not int or type(second.get("line")) is not int
                or second["line"] != first["line"] + 1):
            return False
    if "cell" in first or "cell" in second:
        left, right = _cell_position(first.get("cell")), _cell_position(second.get("cell"))
        if not first.get("sheet") or left is None or right is None:
            return False
        if right not in ((left[0] + 1, left[1]), (left[0], left[1] + 1)):
            return False
    return True


def _contract_marker(text: str, position: int) -> bool:
    """A title elsewhere on the line cannot authorize a contract's number marker."""
    prefix = text[:position]
    references = list(re.finditer(r"\b(?:договор|контракт)[а-яё]*\b", prefix, re.I))
    if not references:
        return False
    documents = list(re.finditer(
        r"\b(?:акт(?:а|у|ом|е)?|документ(?:а|у|ом|е)?|сч[её]т(?:а|у|ом|е)?|упд|"
        r"ведомост(?:ь|и|ью)|справк(?:а|и|у|ой|е)|записк(?:а|и|у|ой|е))\b", prefix, re.I,
    ))
    return not documents or references[-1].end() > documents[-1].end()


def number_token(value: object) -> str | None:
    s = unicodedata.normalize("NFC", str(value)).translate(DASHES).strip(" \t:;.,«»\"")
    s = re.sub(r"\s+(?:[oоOО][тtTТ]|от)\s+.*$", "", s).strip()
    s = re.split(r"\s+(?:дата|договор|контракт|период)\b|\|", s, maxsplit=1, flags=re.I)[0].strip()
    if not s or FIELD_START.match(s) or re.fullmatch(DATE_PATTERN, s):
        return None
    if not re.search(r"[0-9?]", s) or len(s) > 64:
        return None
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9?][A-Za-zА-Яа-яЁё0-9?\s./_()-]*", s):
        return None
    # Space is allowed inside typed prefixes (e.g. ИТ 03-26), not in prose.
    if len(s.split()) > 3:
        return None
    return s


def extract_type(lines: list[dict]) -> dict:
    for line in lines[:12]:
        text = clean_line(line["text"])
        if FIELD_START.match(text) or re.match(r"^(?:основание|лист|страница)\b", text, re.I):
            continue
        for kind, pattern in TYPE_PATTERNS:
            if re.search(pattern, text, re.I):
                return {"value": kind, "evidence": evidence(line)}
    return {"value": None, "evidence": None}


def extract_number_candidates(lines: list[dict]) -> list[dict]:
    found = []
    for index, line in enumerate(lines[:32]):
        text = clean_line(line["text"])
        if FIELD_START.match(text) or re.match(r"^(?:основание|приложение|ссылка|артикул|код\b|утвержден)", text, re.I):
            continue
        value = None
        anchor = None
        explicit = re.match(r"^(?:номер\s+(?:документа|акта)|документ\s*(?:№|N[oо]?)?|№\s*документа)\s*[:：]?\s*(.*)$", text, re.I)
        if explicit:
            value, anchor = explicit.group(1), "explicit_document_number"
        else:
            marker = next((match for match in re.finditer(NUMBER_MARK, text, re.I)
                           if not _contract_marker(text, match.start())), None)
            near_title = False
            following = line
            for previous in reversed(lines[max(0, index - 2):index]):
                previous_text = clean_line(previous["text"])
                if FIELD_START.match(previous_text) or not _adjacent_source_lines(previous, following):
                    break
                if any(re.search(p, previous_text, re.I) for _, p in TYPE_PATTERNS):
                    near_title = True
                    break
                following = previous
            dated_header = bool(re.search(r"\s+[oоOО][тtTТ]\s+" + DATE_PATTERN, text))
            inline_title = any(re.search(p, text, re.I) for _, p in TYPE_PATTERNS)
            # A table row labelled N2 and footer OCR words beginning with N are
            # not document numbers. Bare markers need local header context.
            if marker and (inline_title or (marker.start() == 0 and (near_title or dated_header))):
                value, anchor = text[marker.end():].strip(), "document_header_number_marker"
            else:
                for pattern in [r"^служебн\w*\s+записка\s+(.+)$", r"^универсальн\w*\s+передаточн\w*\s+документ\s+(.+)$", r"^справка\s+о\s+расходах\s+(.+)$"]:
                    m = re.match(pattern, text, re.I)
                    if m:
                        value, anchor = m.group(1), "typed_header_without_marker"
                        break
        if value is None:
            continue
        used = [evidence(line)]
        if not value.strip() and index + 1 < len(lines):
            nxt = lines[index + 1]
            if not _adjacent_source_lines(line, nxt):
                continue
            value = clean_line(nxt["text"])
            if FIELD_START.match(value):
                continue
            used.append(evidence(nxt))
        # The current marker may be the document's own number followed by a
        # separately labelled contract reference on the same source line.
        value = re.split(
            r"\s+(?:(?:по|к|для|согласно|на\s+основании)\s+)?(?:договор|контракт)[а-яё]*\b",
            value, maxsplit=1, flags=re.I,
        )[0]
        token = number_token(value)
        if token:
            found.append({"value": token, "normalized": norm(token), "anchor": anchor, "evidence": used})
    # Preserve all evidence but collapse repeated assertions of the same number.
    unique = {}
    for item in found:
        if item["normalized"] in unique:
            unique[item["normalized"]]["evidence"].extend(item["evidence"])
        else:
            unique[item["normalized"]] = item
    return list(unique.values())


def number_issues(value: object, acquisition: str) -> list[str]:
    if not norm(value):
        return ["number_missing"]
    problems = []
    s = norm(value)
    if "?" in s or "..." in s:
        problems.append("incomplete_number")
    if acquisition == "scan":
        prefix = re.split(r"[-/_\s]", s)[0]
        if re.search(r"[A-ZА-ЯЁ]", prefix) and re.search(r"\d", prefix):
            problems.append("mixed_letter_digit_prefix_requires_review")
        letters = re.sub(r"[^A-ZА-ЯЁ]", "", prefix)
        if re.search(r"[A-Z]", prefix) and re.search(r"[А-ЯЁ]", prefix):
            problems.append("mixed_scripts_requires_review")
        if letters and all(ch in "АВЕКМНОРСТХABEKMHOPCTX" for ch in letters):
            problems.append("visually_ambiguous_alphabet")
    return problems


def extract_issuer(lines: list[dict]) -> dict:
    candidates, tax_ids = [], {}
    for i, line in enumerate(lines[:40]):
        text = clean_line(line["text"])
        tax = re.match(r"^инн\s+(?:исполнителя|поставщика|продавца)\s*[:：]?\s*(\d{10}(?:\d{2})?)\s*$", text, re.I)
        if tax:
            tax_ids[tax.group(1)] = evidence(line)
        m = re.match(r"^(?:исполнитель|поставщик|продавец|выставил|выставившая\s+организация)\s*[:：]?\s*(.*)$", text, re.I)
        if not m:
            continue
        value = m.group(1).strip()
        proof = [evidence(line)]
        if not value and i + 1 < len(lines):
            value = clean_line(lines[i + 1]["text"])
            proof.append(evidence(lines[i + 1]))
        if norm(value) and not FIELD_START.match(value):
            candidates.append({"value": re.sub(r"\s+", " ", value).strip(), "evidence": proof})
    values = {norm(x["value"]): x for x in candidates}
    tax_info = {"tax_id": next(iter(tax_ids)) if len(tax_ids) == 1 else None,
                "tax_id_evidence": list(tax_ids.values()), "tax_id_conflict": len(tax_ids) > 1}
    if len(values) == 1:
        return next(iter(values.values())) | {"status": "explicit_source_role"} | tax_info
    return {"value": None, "status": "missing" if not values else "conflicting_source_roles", "candidates": candidates} | tax_info


def extract_source_facts(lines: list[dict]) -> tuple[dict, dict]:
    result, proof = {}, {}
    for i, line in enumerate(lines):
        text = clean_line(line["text"])
        candidates = [(text, [line])]
        if i + 1 < len(lines):
            following = lines[i + 1]
            if _adjacent_source_lines(line, following):
                candidates.append((text + " " + clean_line(following["text"]), [line, following]))
        for joined, used_lines in candidates:
            for field, pattern in [
                ("contract_number", r"^(?:договор|контракт|проект)\s*[:№Nn]*\s*([A-Za-zА-Яа-я0-9?]+(?:[-/][A-Za-zА-Яа-я0-9?]+)+)"),
                ("date", r"^дата(?:\s+документа)?\s*:?\s*(" + DATE_PATTERN + r")"),
                ("amount", r"^(?:итого(?:\s+к\s+(?:учету|оплате))?|сумма(?:\s+по\s+акту)?|итоговая\s+сумма|к\s+оплате(?:\s+по\s+документу)?|стоимость)\s*(?:,?\s*руб\.?)?\s*:?\s*([0-9](?:[0-9\s.,]*[0-9])?)"),
            ]:
                m = re.match(pattern, joined, re.I)
                if m and field not in result:
                    value = m.group(1).strip()
                    if field == "date":
                        parsed = parse_date(value)
                        value = parsed.isoformat() if parsed else None
                    elif field == "amount":
                        parsed = parse_amount(value)
                        value = str(parsed) if parsed is not None else None
                    if value is not None and "?" not in value:
                        result[field] = value
                        proof[field] = [evidence(used) for used in used_lines]
        if "date" not in result and (re.match(NUMBER_MARK, text, re.I) or any(re.search(p, text, re.I) for _, p in TYPE_PATTERNS)):
            m = re.search(r"\s+[oоOО][тtTТ]\s+(" + DATE_PATTERN + r")", text)
            parsed = parse_date(m.group(1)) if m else None
            if parsed:
                result["date"] = parsed.isoformat()
                proof["date"] = [evidence(line)]
    return result, proof


def resolve_document(
    doc_id: str, source_sha256: str, acquisition: str, lines: list[dict],
    prediction: dict, content_fingerprint: str | None = None,
    content_complete: bool = False, package_fingerprint: str | None = None,
) -> dict:
    """Inputs contain source observations only, never expected answers or family IDs."""
    candidates = extract_number_candidates(lines)
    old = prediction.get("doc_number")
    value, status, reasons = old, "model_only", []
    if len(candidates) == 1:
        source = candidates[0]["value"]
        if acquisition == "native":
            value, status = source, "native_source"
            if old is not None and norm(old) != norm(source):
                reasons.append("model_number_replaced_by_native_source")
        elif not old:
            value, status = source, "ocr_source_only"
        elif norm(old) == norm(source):
            value, status = old, "source_corroborated"
        elif re.fullmatch(r"\d+(?:[-/]\d+)*", norm(old) or "") and norm(source).endswith("-" + norm(old)):
            value, status = source, "prefix_recovered_from_source"
            reasons.append("model_omitted_prefix")
        elif visual_key(old) == visual_key(source):
            value, status = old, "alphabet_ambiguous"
            reasons.append("source_model_alphabet_disagreement")
        else:
            status = "source_model_conflict"
            reasons.append("different_full_numbers")
    elif len(candidates) > 1:
        status = "multiple_source_numbers"
        reasons.append("ambiguous_number_anchor")
    else:
        status = "missing" if old is None else "model_only"
        reasons.append("no_source_number_anchor")
    issues = number_issues(value, acquisition)
    unusable_status = status in {"model_only", "missing", "source_model_conflict", "multiple_source_numbers", "alphabet_ambiguous", "ocr_source_only"}
    usable = value if not issues and not unusable_status else None
    source_facts, fact_proof = extract_source_facts(lines)
    facts = {k: prediction.get(k) for k in ("contract_number", "date", "period_start", "period_end", "amount", "category")}
    facts.update(source_facts)
    kind, issuer = extract_type(lines), extract_issuer(lines)
    return {
        "id": doc_id, "version": VERSION, "source_sha256": source_sha256,
        "acquisition": acquisition,
        "number": {"value": value, "usable_value": usable, "status": status,
                   "model_value": old, "issues": issues + reasons,
                   "candidates": candidates, "evidence": candidates[0]["evidence"] if len(candidates) == 1 else []},
        "doc_type": kind, "issuer": issuer, "facts": facts,
        "source_facts": source_facts, "fact_evidence": fact_proof,
        "content_fingerprint": content_fingerprint, "content_complete": bool(content_complete),
        "package_fingerprint": package_fingerprint,
        "limitations": ["OCR and model agreement are correlated, not proof.", "No issuer inferred from customer or unlabelled company name."]}


def date_key(record: dict) -> tuple[str, str] | None:
    f = record["facts"]
    # Document issue date is identity; an optional accounting period is a separate fact.
    d = parse_date(f.get("date"))
    if d:
        return (d.isoformat(), d.isoformat())
    if f.get("period_start") or f.get("period_end"):
        a, b = parse_date(f.get("period_start")), parse_date(f.get("period_end"))
        return (a.isoformat(), b.isoformat()) if a and b and a <= b else None
    return None


def complete_key(value: object) -> str | None:
    value = norm(value)
    return value if value and "?" not in value and "..." not in value else None


def compare_documents(a: dict, b: dict) -> dict:
    def decision(status, *reasons):
        return {"left": a["id"], "right": b["id"], "status": status,
                "auto_merge": status == "duplicate", "reasons": list(reasons)}
    if a.get("source_sha256") and a["source_sha256"] == b.get("source_sha256"):
        return decision("duplicate", "identical_file_sha256")
    av, bv = a["number"].get("value"), b["number"].get("value")
    an, bn = norm(av), norm(bv)
    ac, bc = complete_key(a["facts"].get("contract_number")), complete_key(b["facts"].get("contract_number"))
    ad, bd = date_key(a), date_key(b)
    ai, bi = norm(a["issuer"].get("value")), norm(b["issuer"].get("value"))
    ax, bx = a["issuer"].get("tax_id"), b["issuer"].get("tax_id")
    at, bt = a["doc_type"].get("value"), b["doc_type"].get("value")
    aa, ba = parse_amount(a["facts"].get("amount")), parse_amount(b["facts"].get("amount"))
    same_context = bool(ac and ac == bc and ad and ad == bd and aa is not None and aa == ba)
    conflicts = [name for name, x, y in [("issuer", ai, bi), ("issuer_tax_id", ax, bx), ("document_type", at, bt), ("contract", ac, bc)] if x and y and x != y]
    if conflicts:
        return decision("related" if same_context else "distinct", "different_" + ",".join(conflicts), "never_merge_different_identity_roles")
    strict_identity = bool(ai and ai == bi and ax == bx and at and at == bt and ac and ac == bc and ad and ad == bd and an and an == bn and "?" not in an and not any(x["issuer"].get("tax_id_conflict") for x in (a, b)))
    if strict_identity:
        if aa is not None and ba is not None and aa != ba:
            return decision("conflict", "same_identity_different_amount")
        native_complete = all(x["acquisition"] == "native" and x.get("content_complete") and x.get("content_fingerprint") for x in (a, b))
        source_identity = all(x["number"].get("usable_value") and {"date", "contract_number"} <= set(x.get("source_facts", {})) for x in (a, b))
        if native_complete and source_identity:
            if a.get("package_fingerprint") and a["package_fingerprint"] == b.get("package_fingerprint"):
                return decision("duplicate", "same_native_package_except_declared_metadata_and_source_identity")
            if a["content_fingerprint"] != b["content_fingerprint"]:
                return decision("conflict", "same_identity_different_native_content_or_version")
            return decision("candidate", "same_text_but_layout_or_other_package_content_changed")
        return decision("candidate", "same_identity_without_complete_content_proof")
    uncertain_number = a["number"].get("usable_value") is None or b["number"].get("usable_value") is None
    number_match = bool(an and bn and "?" not in an + bn and (an == bn or (uncertain_number and visual_key(an) == visual_key(bn))))
    if number_match and ((ac and ac == bc) or (ad and ad == bd)):
        if ad and bd and ad != bd:
            return decision("related", "same_number_different_date_or_period")
        return decision("candidate", "compatible_number_and_context", "issuer_or_complete_identity_unverified")
    if same_context and (not an or not bn or "?" in (an or "") + (bn or "") or uncertain_number):
        return decision("candidate", "matching_context_but_number_uncertain")
    if same_context:
        return decision("related", "same_context_different_verified_number")
    return decision("distinct" if ac and bc and ad and bd and an and bn else "insufficient", "no_supported_duplicate_identity")


def group_documents(records: list[dict]) -> dict:
    """Union only proven equalities; candidate/conflict edges never propagate."""
    by_id = {x["id"]: x for x in records}
    if len(by_id) != len(records):
        raise ValueError("Document IDs must be unique")
    parent = {k: k for k in by_id}
    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    pairs = []
    for a, b in combinations(records, 2):
        p = compare_documents(a, b)
        if p["auto_merge"]:
            parent[root(b["id"])] = root(a["id"])
        if p["status"] in {"duplicate", "candidate", "conflict"}:
            pairs.append(p)
    groups = {}
    for k in by_id:
        groups.setdefault(root(k), []).append(k)
    return {"groups": list(groups.values()), "review_pairs": pairs,
            "files_deleted": False, "candidate_edges_used_for_clustering": False}
