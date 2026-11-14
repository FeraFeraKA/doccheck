"""Literal own-document numbers, separate from model and business identity.

Only bounded native headers/own-number labels authorize a correction. There is
no category/filename inference, tail matching, transliteration or OCR repair.
"""
from copy import deepcopy
import hashlib
import re

VERSION = "native-own-number-v2"
TITLE = re.compile(r"^(?:сч[её]т[- ]акт|сч[её]т[- ]фактура|сч[её]т\s+на\s+оплату|акт|справка|расч[её]тная\s+ведомость|ведомость|расч[её]т\s+страховых\s+взносов|служебная\s+записка|универсальный\s+передаточный\s+документ|упд)\b", re.I)
BARE_TITLE = re.compile(r"^(?:сч[её]т[- ]акт|акт|служебная\s+записка|универсальный\s+передаточный\s+документ|упд)\s+", re.I)
OWN_HEADER = re.compile(r"(?:сч[её]т[- ]акт|сч[её]т[- ]фактура|сч[её]т\s+на\s+оплату|акт(?:\s+(?:оказанных\s+услуг|выполненных\s+работ|при[её]ма[- ]передачи))?|справка(?:\s+расч[её]т(?:\s+страховых\s+взносов)?)?|расч[её]тная\s+ведомость(?:\s+по\s+оплате\s+труда)?|ведомость|расч[её]т\s+страховых\s+взносов|служебная\s+записка|универсальный\s+передаточный\s+документ|упд)\s*", re.I)
COPY_ACT_HEADER = re.compile(r"копия\s+акта(?:\s+(?:оказанных\s+услуг|выполненных\s+работ|при[её]ма[- ]передачи))?\s*", re.I)
OWN_LABEL = re.compile(r"^(?:(?:номер|№)\s+(?:настоящего\s+)?документа\b\s*[:№]?|документ\b\s*№|собственный\s+номер\s+документа\b\s*[:№]?)\s*", re.I)
MARKER = re.compile(r"(?:№|\bномер\b)\s*[:]?\s*", re.I)
REFERENCE = re.compile(r"\b(?:договор\w*|контракт\w*|основани\w*|согласно|приложени\w*|цитируем\w*|банк\w*|расч[её]тн\w*\s+сч[её]т|корреспондент\w*|сч[её]т\s+организации)\b|\b(?:к|по|из)\s+акту\b", re.I)
FOREIGN_LABEL = re.compile(r"^(?:договор|контракт|проект|основание|дата|р/с|к/с|расч[её]тный\s+сч[её]т|корреспондентский\s+сч[её]т|сч[её]т\s+организации)\b\s*(?:№|:)?\s*", re.I)
FOREIGN_MARKER_PREFIX = re.compile(r"(?:\b(?:договор(?:а|у|ом|е)?|контракт(?:а|у|ом|е)?|проект(?:а|у|ом|е)?|дата|расч[её]тный\s+сч[её]т|корреспондентский\s+сч[её]т|сч[её]т\s+организации)|(?:\bоснование\s*:\s*|\bсогласно\s+|\b(?:к|по|из)\s+)(?:акт(?:а|у|ом|е)?|документ(?:а|у|ом|е)?|заявк[аеуи]|отч[её]т(?:а|у|ом|е)?|сч[её]т(?:а|у|ом|е)?|накладн(?:ая|ой|ую)|справк[аеуи])(?:\s+[\w-]+){0,4})\s*$", re.I)
ISSUER_LABEL = re.compile(r"^(?:исполнитель|поставщик|составитель|выдавшая\s+организация)\b\s*:?\s*", re.I)
TABLE = re.compile(r"^(?:код\s+статьи|наименование|вид\s+начисления|база\s+начислений|описание\s*\||основание\s*\||итого|сумма\s*[,|]|№\s*(?:п/п|строки))", re.I)
TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:[ \t]*[-–—−‑/][ \t]*[A-Za-zА-Яа-яЁё0-9]+|[._][A-Za-zА-Яа-яЁё0-9]+|(?<=\d)[ \t]*\.[ \t]*\d+)*")
DATE_TOKEN = re.compile(r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})")
ABSENT = re.compile(r"^(?:б\s*/\s*н|без\s+номера|не\s+присвоен\w*|отсутствует|[-–—])\s*[.]?$", re.I)
ABSENCE_MARKER = r"(?:б\s*[/\\-]\s*н|без\s+номера|не\s+присвоен(?:а|о)?|отсутствует|[_—–-]+)"
DATE_TAIL = r"от\s+(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})\s*(?:г\.)?"
ABSENCE_VALUE = re.compile(r"(?P<marker>" + ABSENCE_MARKER + r")\s*[.]?(?:\s+" + DATE_TAIL + r")?\s*", re.I)


def absence_proof(cell, start, end, basis, label, reason):
    return {"start": cell["start"] + start, "end": cell["start"] + end,
            "text": cell["text"][start:end], "line": cell["line"], "basis": basis,
            "label": label, "reason": reason, "context_start": cell["start"],
            "context_end": cell["end"], "context": cell["text"]}


def literal_id(value):
    """Raw alias for suspicion only; remove a standalone number field marker."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    value = re.sub(r"^(?:№\s*|номер\b(?:\s*:\s*|\s+))", "", value, flags=re.I).strip()
    if not value or ABSENT.fullmatch(value) or value.casefold() in {"null", "none", "unknown", "неизвестно", "номер", "№"}:
        return None
    return value


def header_cells(text, bounded=True):
    """Retain native offsets while splitting XLSX/DOCX cells and PDF lines."""
    offset, meaningful = 0, 0
    cells = []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        plain = line.rstrip("\r\n")
        if re.match(r"^\s*(?:Лист:|Страница\s+\d+\s*$)", plain, re.I):
            offset += len(line)
            continue
        if plain.strip():
            meaningful += 1
        if bounded and meaningful > 16:
            break
        # Table headers terminate the own-header window; numbered body rows
        # and references within the table cannot become the document number.
        clean = re.sub(r"^\s*[A-Z]+\d+:\s*", "", plain, flags=re.I)
        if bounded and TABLE.search(clean):
            break
        for match in re.finditer(r"[^|;]+", plain):
            raw = match.group()
            prefix = re.match(r"\s*(?:[A-Z]+\d+:\s*)?", raw, re.I)
            value = raw[prefix.end():].strip()
            start = offset + match.start() + prefix.end()
            if value:
                cells.append({"text": value, "start": start, "end": start + len(value), "line": line_number})
        offset += len(line)
    return cells


def parse_value(cell, value_start, basis, label):
    value = cell["text"][value_start:]
    lead = re.match(r"\s*[«\"']?\s*", value).end()
    value = value[lead:]
    absent = ABSENCE_VALUE.fullmatch(value)
    if absent:
        start = value_start + lead + absent.start("marker")
        return [], [], [absence_proof(cell, start, start + len(absent.group("marker")), basis, label, "explicit_own_empty_marker")]
    if re.fullmatch(DATE_TAIL, value, re.I):
        return [], [], [absence_proof(cell, value_start + lead, value_start + lead, basis, label, "empty_own_slot_before_date_requisite")]
    if not value:
        return [], [{"reason": "own_value_unavailable", "line": cell["line"], "text": cell["text"]}], []
    match = TOKEN.match(value)
    if not match or not any(c.isdigit() for c in match.group()):
        return [], [{"reason": "own_number_value_unparsed", "line": cell["line"], "text": cell["text"]}], []
    token = match.group()
    if basis == "literal_bare_header" and DATE_TOKEN.fullmatch(re.sub(r"\s+", "", token)):
        return [], [{"reason": "date_shaped_bare_header_is_ambiguous", "line": cell["line"], "text": cell["text"]}], []
    tail = value[match.end():].strip().lstrip('»"\'').strip()
    start = cell["start"] + value_start + lead
    candidate = {"value": token, "start": start, "end": start + len(token),
                 "line": cell["line"], "basis": basis, "label": label,
                 "context_start": cell["start"], "context_end": cell["end"], "context": cell["text"]}
    # A date after "от" is a separate requisite, never part of the ID.
    if tail and not re.fullmatch(DATE_TAIL, tail, re.I):
        return [candidate], [{"reason": "multiple_or_unparsed_own_values", "line": cell["line"], "text": cell["text"]}], []
    return [candidate], [], []


def resolve_own_number(text, *, _bounded=True):
    cells = header_cells(text, bounded=_bounded)
    candidates, issues, absences = [], [], []
    previous_title = None
    consumed = set()
    quoted = list(re.finditer(r'«[^»]*»|“[^”]*”|"[^"]*"', text, re.S))
    for index, cell in enumerate(cells):
        if index in consumed:
            continue
        # A quoted form/example or the adjacent value of an explicit foreign
        # requisite is not the current document's own header.
        previous_foreign = FOREIGN_LABEL.match(cells[index - 1]['text']) if index else None
        if (any(q.start() <= cell['start'] < q.end() for q in quoted)
                or (previous_foreign and not cells[index - 1]['text'][previous_foreign.end():].strip())):
            previous_title = None
            continue
        value = cell["text"]
        own = OWN_LABEL.match(value)
        title = TITLE.match(value)
        copy_marker = MARKER.search(value)
        if copy_marker and not COPY_ACT_HEADER.fullmatch(value[:copy_marker.start()]):
            copy_marker = None
        # Labels naming another document or an organisation's account are not
        # own labels, even when their number resembles the model answer.
        if REFERENCE.search(value) and not own:
            previous_title = None
            continue
        basis, value_start, label = None, None, None
        if own:
            basis, value_start, label = "explicit_own_label", own.end(), own.group()
        elif copy_marker:
            # A marked copy names the act whose identity needs review; it does
            # not prove that differently hashed files are duplicate operations.
            basis, value_start, label = "own_copy_header", copy_marker.end(), value[:copy_marker.end()]
        elif title:
            marker = MARKER.search(value, title.end())
            if marker and OWN_HEADER.fullmatch(value[:marker.start()]):
                basis, value_start, label = "own_document_header", marker.end(), value[:marker.end()]
            else:
                bare = BARE_TITLE.match(value)
                absence_start = next((title.end() + item.start()
                    for item in re.finditer(ABSENCE_MARKER, value[title.end():], re.I)
                    if OWN_HEADER.fullmatch(value[:title.end() + item.start()])), None)
                if absence_start is not None:
                    basis, value_start, label = "own_header_absence", absence_start, value[:absence_start]
                elif bare and TOKEN.fullmatch(value[bare.end():]) and any(c.isdigit() for c in value[bare.end():]):
                    basis, value_start, label = "literal_bare_header", bare.end(), bare.group()
                else:
                    previous_title = index if OWN_HEADER.fullmatch(value) else None
                    continue
        elif previous_title == index - 1 and MARKER.match(value):
            marker = MARKER.match(value)
            basis, value_start, label = "number_below_own_title", marker.end(), cells[previous_title]["text"]
        previous_title = None
        if basis is None:
            continue
        if not value[value_start:].strip() and index + 1 < len(cells):
            # Only an immediately adjacent cell/line can be the value of a
            # standalone own-number label; another labelled requisite fails.
            value_cell = cells[index + 1]
            if FOREIGN_LABEL.match(value_cell["text"]) or ISSUER_LABEL.match(value_cell["text"]) or OWN_LABEL.match(value_cell["text"]):
                found, problems = [], []
                missing = [absence_proof(cell, value_start, value_start, basis, label, "empty_own_slot_before_next_label")]
            else:
                found, problems, missing = parse_value(value_cell, 0, basis + "_adjacent", label)
                consumed.add(index + 1)
        else:
            found, problems, missing = parse_value(cell, value_start, basis, label)
        candidates.extend(found)
        issues.extend(problems)
        absences.extend(missing)
    values = sorted({item["value"] for item in candidates})
    absence_conflicts = []
    if absences and _bounded:
        # A later own-number label can veto absence, but never authorizes a
        # positive number correction outside the bounded own-header grammar.
        all_slots = resolve_own_number(text, _bounded=False)
        absence_conflicts = ([{"kind": "later_candidate", "evidence": x} for x in all_slots["candidates"] if x not in candidates]
            + [{"kind": "later_unparsed_own_slot", "evidence": x} for x in all_slots["issues"] if x not in issues])
    if absences:
        status = "ambiguous" if values or issues or absence_conflicts else "explicit_absent"
    else:
        status = "resolved" if len(values) == 1 and not issues else "ambiguous" if len(values) > 1 or (values and issues) else "missing"
    return {"status": status, "resolved_number": values[0] if status == "resolved" else None,
            "candidates": candidates, "issues": issues, "non_own_candidates": non_own_numbers(text),
            "absence_evidence": absences, "absence_conflicts": absence_conflicts,
            **source_identity_context(text)}


def source_identity_context(text):
    """Optional explicit header kind/issuer evidence, not entity resolution."""
    cells = header_cells(text)
    kinds, issuers = [], []
    for index, cell in enumerate(cells):
        value = cell["text"]
        marker = MARKER.search(value)
        prefix = value[:marker.start()] if marker else value
        bare = BARE_TITLE.match(value)
        if not OWN_HEADER.fullmatch(prefix) and bare and TOKEN.fullmatch(value[bare.end():]):
            prefix = bare.group()
        if marker and COPY_ACT_HEADER.fullmatch(prefix):
            kinds.append({"kind": "act", "start": cell["start"], "end": cell["start"] + len(prefix), "text": prefix})
        elif OWN_HEADER.fullmatch(prefix):
            lowered = prefix.casefold().replace("ё", "е").strip()
            kind = next((kind for stem, kind in (
                ("счет-акт", "invoice_act"), ("счет акт", "invoice_act"), ("счет-фактура", "tax_invoice"),
                ("счет на оплату", "invoice"), ("акт", "act"), ("справка", "certificate"),
                ("расчетная ведомость", "statement"), ("ведомость", "statement"),
                ("расчет страховых взносов", "insurance_calculation"), ("служебная записка", "memo"),
                ("универсальный передаточный документ", "upd"), ("упд", "upd")) if lowered.startswith(stem)), None)
            if kind:
                kinds.append({"kind": kind, "start": cell["start"], "end": cell["start"] + len(prefix), "text": prefix})
        label = ISSUER_LABEL.match(value)
        if label:
            source, start = cell, label.end()
            if not value[start:].strip() and index + 1 < len(cells):
                source, start = cells[index + 1], 0
            literal = source["text"][start:].strip()
            if literal and not (FOREIGN_LABEL.match(literal) or OWN_LABEL.match(literal) or TITLE.match(literal) or ISSUER_LABEL.match(literal)):
                begin = source["start"] + start
                key = re.sub(r"\s+", " ", literal.translate(str.maketrans("", "", '«»"'))).strip().casefold()
                issuers.append({"issuer_key": key, "start": begin, "end": begin + len(literal), "text": literal})
    kind_set, issuer_set = {x["kind"] for x in kinds}, {x["issuer_key"] for x in issuers}
    return {"kind_evidence": kinds, "issuer_evidence": issuers,
            "document_kind": next(iter(kind_set)) if len(kind_set) == 1 else None,
            "issuer_key": next(iter(issuer_set)) if len(issuer_set) == 1 else None}


def non_own_numbers(text):
    """Foreign requisite roles can reject a raw alias, never create identity."""
    cells = header_cells(text, bounded=False)
    result = []
    for index, cell in enumerate(cells):
        value = cell["text"]
        starts = []
        for marker in MARKER.finditer(value):
            prefix = value[:marker.start()]
            if FOREIGN_MARKER_PREFIX.search(prefix):
                starts.append((cell, marker.end(), "foreign_reference"))
        label = FOREIGN_LABEL.match(value)
        if label:
            if value[label.end():].strip():
                starts.append((cell, label.end(), "foreign_requisite"))
            elif index + 1 < len(cells):
                starts.append((cells[index + 1], 0, "foreign_requisite_adjacent"))
        for source, start, role in starts:
            rest = source["text"][start:]
            leading = len(rest) - len(rest.lstrip())
            token = TOKEN.match(rest.lstrip())
            if token and any(c.isdigit() for c in token.group()):
                offset = source["start"] + start + leading
                item = {"value": token.group(), "start": offset, "end": offset + len(token.group()), "line": source["line"], "role": role}
                if item not in result:
                    result.append(item)
    return result


def validate_number_evidence(record):
    """Single downstream authority check; a 64-character string is not proof."""
    evidence = record.get("number_evidence")
    if not isinstance(evidence, dict) or evidence.get("gate_applies") is not True:
        return {"valid": False, "identity_usable": False, "status": "model_only", "number": None, "candidates": [], "non_own_candidates": []}
    native = record.get("source_native_text")
    valid = (evidence.get("version") == VERSION and evidence.get("source_verified") is True
        and isinstance(record.get("source_hash"), str) and bool(record["source_hash"])
        and evidence.get("source_hash") == record["source_hash"]
        and isinstance(native, str) and bool(native.strip())
        and evidence.get("native_text_sha256") == hashlib.sha256(native.encode()).hexdigest())
    parsed = resolve_own_number(native) if valid else None
    raw = record.get("raw_prediction", {}).get("doc_number")
    effective = record.get("prediction", {}).get("doc_number")
    valid = bool(valid and all(evidence.get(key) == parsed[key] for key in ("status", "resolved_number", "candidates", "issues", "non_own_candidates", "kind_evidence", "issuer_evidence", "document_kind", "issuer_key", "absence_evidence", "absence_conflicts"))
        and evidence.get("original_number") == raw and evidence.get("effective_number") == effective)
    if valid:
        resolved = parsed["status"] == "resolved"
        absent = parsed["status"] == "explicit_absent"
        decision = "confirmed" if raw == parsed["resolved_number"] else "corrected"
        valid = bool((resolved and evidence.get("identity_usable") is True and evidence.get("decision") == decision and effective == parsed["resolved_number"])
            or (absent and evidence.get("identity_usable") is False and evidence.get("decision") == ("confirmed_absent" if raw is None else "cleared") and effective is None)
            or (not resolved and not absent and evidence.get("identity_usable") is False and evidence.get("decision") == "unchecked" and effective == raw))
        valid = valid and evidence.get("raw_alias_allowed") is (not absent)
    if not valid:
        return {"valid": False, "identity_usable": False, "status": "invalid", "number": None, "candidates": [], "non_own_candidates": []}
    return {"valid": True, "identity_usable": evidence["identity_usable"], "status": parsed["status"],
            "number": parsed["resolved_number"], "candidates": sorted({item["value"] for item in parsed["candidates"]}),
            "non_own_candidates": sorted({item["value"] for item in parsed["non_own_candidates"]}),
            "document_kind": parsed["document_kind"], "issuer_key": parsed["issuer_key"],
            "raw_alias_allowed": parsed["status"] != "explicit_absent"}


def apply_document_number_checks(record, native_text=None):
    checked = deepcopy(record)
    prediction = checked.get("prediction")
    if not isinstance(prediction, dict):
        return checked
    checked.setdefault("raw_prediction", deepcopy(prediction))
    raw = checked["raw_prediction"].get("doc_number")
    prediction["doc_number"] = raw
    if not isinstance(native_text, str) or not native_text.strip():
        checked["number_evidence"] = {"version": VERSION, "gate_applies": False,
            "source_verified": False, "identity_usable": False, "decision": "model_only",
            "status": "native_source_unavailable", "original_number": raw, "effective_number": raw,
            "candidates": [], "issues": []}
        return checked
    checked.setdefault("source_native_text", native_text)
    parsed = resolve_own_number(native_text)
    resolved = parsed["status"] == "resolved"
    absent = parsed["status"] == "explicit_absent"
    if resolved:
        prediction["doc_number"] = parsed["resolved_number"]
    elif absent:
        prediction["doc_number"] = None
    checked["number_evidence"] = {**parsed, "version": VERSION, "gate_applies": True,
        "source_verified": True, "source_hash": checked.get("source_hash"),
        "native_text_sha256": hashlib.sha256(native_text.encode()).hexdigest(),
        "original_number": raw, "effective_number": prediction.get("doc_number"),
        "identity_usable": resolved, "raw_alias_allowed": not absent,
        "decision": (("confirmed" if raw == parsed["resolved_number"] else "corrected") if resolved else
                     ("confirmed_absent" if raw is None else "cleared") if absent else "unchecked")}
    if not validate_number_evidence(checked)["valid"]:
        # A mismatched supplied native text/record hash never gains authority.
        prediction["doc_number"] = raw
        checked["number_evidence"].update(identity_usable=False, decision="invalid", effective_number=raw, raw_alias_allowed=True)
    return checked
