"""Bounded source checks for the local financial experiment, version 2.

No answer keys, filenames, expected sums or model-confidence scores are used.
Native source evidence may correct overhead allocation; a model-generated quote
on a scan is not independent evidence and never authorizes such an override.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from .document_identity import header_cells, OWN_HEADER, OWN_LABEL, MARKER, TOKEN, ABSENCE_MARKER, DATE_TAIL, FOREIGN_LABEL

VERSION = "native-purpose-v3.2"
OVERHEAD = {"production_overhead", "general_admin"}
ACTION = re.compile(r"\b(?:сопровождени|обслуживани|поддержк|настройк|поверк|калибровк|метролог|ремонт|аренд|обеспечени|подготовк|содержани)\w*", re.I)
PURPOSE_LABEL = re.compile(r"(?:назначение|содержание\s+работ|описание\s+(?:работ|услуг)|наименование\s+(?:работ|услуг))\s*[:—-]", re.I)
METADATA = re.compile(r"^\s*(?:[A-Z]+\d+:\s*)?(?:исполнитель|заказчик|получатель|плательщик|подпис\w*|ответствен\w*|договор|контракт|период|дата|№|итого|ндс|сумм|стоимость|расчет\s+составлен|расчёт\s+составлен|руководител\w*|директор\w*|главный\s+бухгалтер|лист)\b", re.I)
ORGANIZATION_HEADER = re.compile(r"^\s*(?:[A-Z]+\d+:\s*)?(?:ООО|АО|ПАО|ОАО|ЗАО|ИП|АНО|НКО|ФГАОУ|ФГБОУ|ФГБУ|ГБУ|МБУ)\b", re.I)
ADMIN = re.compile(r"\b(?:административн\w*|общехозяйственн\w*|управленческ\w*|бухгалтер\w*|аппарат\w*\s+управлен\w*)", re.I)
PRODUCTION = re.compile(r"\b(?:общепроизводственн\w*|производственн\w*|лаборатор\w*|метролог\w*|калибров\w*|поверк\w*|испытательн\w*)", re.I)
NEGATION = re.compile(r"\b(?:не|без|кроме|исключая)\b", re.I)
PURCHASE = re.compile(r"\b(?:поставк|приобретени|закупк)\w*", re.I)
DENIED_SERVICE = re.compile(r"\b(?:работ\w*|услуг\w*|обслуживани\w*|поддержк\w*)\s+(?:\w+\s+){0,4}не\s+(?:выполн\w*|выполня\w*|оказ\w*|осуществл\w*|провод\w*)", re.I)
WORK_CONTEXT = re.compile(r"\b(?:работ\w*|услуг\w*|расход\w*|затрат\w*)\b", re.I)
NONASSERTIVE = re.compile(r"\b(?:если|возможно|предположительно|ли|планируется|планируются|планировал\w*|запланир\w*|предполага\w*|предполаг\w*|предстоит)\b|\bпри\s+условии\b", re.I)
UNPARSED_NEGATIVE = re.compile(r"\b(?:нет|отсутств\w*|исключ[её]н\w*|отмен\w*|отлож\w*|приостанов\w*)\b", re.I)
NARRATIVE_CONTEXT = re.compile(r"\b(?:в|из|по|согласно|для)\s+(?:образц\w*|пример\w*|шаблон\w*|цитат\w*|(?:друг|прежн|предыдущ|стар)\w*\s+(?:акт|документ|отч[её]т)\w*)\b|^\s*(?:пример|цитата|образец)\s*:", re.I)
# Selection only: these productive nominal forms retain an unfamiliar
# operation's risk statement. They NEVER grant positive category authority.
OPERATION_NOMINAL = re.compile(r"\b[а-яё]{2,}(?:ирование|изация|ование|овка|ание|ение)\b", re.I)
QUOTED = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"", re.S)
DENIED_OPERATION = re.compile(r"\bне\s+(?:выполн\w*|выполня\w*|провод\w*|оказ\w*|осуществл\w*)\b", re.I)
NAMED_RECIPIENT = re.compile(r"\b(?:подразделени\w*|дирекци\w*|отдел\w*|служб\w*|систем\w*|программ\w*|ООО|АО|ФГБУ)\s*$", re.I)
COREFERENCE = re.compile(r"\b(?:(?:эт(?:и|а|о|ого|ой|их|им|ими)|данн\w*|указанн\w*|настоящ\w*|так\w*)\s+(?:работ\w*|услуг\w*|обслуживани\w*|поддержк\w*|расход\w*|затрат\w*)|они|это)\b", re.I)

OLD_REQUEST = re.compile(
    r"^(?:(?:(?:в|из|по)\s+)?(?:первоначальн|предыдущ|прежн|стар|ранн)\w*\s+|"
    r"ранее\s+(?:(?:было|была|был)\s+)?(?:выдан\w*|оформлен\w*|составлен\w*)\s+)"
    r"(?P<kind>заявк\w*|поручени\w*)\b", re.I)
OLD_REFERENCE = re.compile(r"\b(?:заявк|поручени)\w*\b", re.I)
REQUEST_CANCELLATION = re.compile(
    r"(?:именно\s+)?(?:(?P<request>(?:эта|данная|указанная)\s+(?:часть\s+заявки|заявка))|"
    r"(?P<instruction>(?:это|данное|указанное)\s+(?:(?:прежнее|предыдущее|раннее)\s+)?поручение)|"
    r"(?P<item>(?:этот|данный|указанный)\s+пункт(?:\s+заявки)?))\s+"
    r"(?:отмен[её]н[ао]?|отозван[ао]?|аннулирован[ао]?|снят[ао]?\s+с\s+исполнения)"
    r"(?:\s*[,;]\s*(?:указанные|описанные|перечисленные|предусмотренные)\s+в\s+ней\s+"
    r"(?:услуги|работы)\s+(?:по\s+настоящему\s+акту\s+)?не\s+"
    r"(?:оказывались|оказаны|выполнялись|выполнены))?\s*[.!]?", re.I)
DENIAL_END = r"\s+не\s+(?:оказыва\w*|оказа\w*|выполня\w*|выполн\w*|проводи\w*)\s*[.!]?"
REFERENCED_OPERATION = r"предусмотренн(?:ая|ые|ое|ый)\s+"
OPERATION_NAME = r"[а-яё-]+(?:\s+[а-яё-]+){0,3}"
FOLLOWUP_DENIAL = {
    "request": re.compile(
        r"(?:(?:работы|услуги)\s+(?:по|из)\s+(?:этой|данной|указанной)\s+заявк[еи]|"
        + REFERENCED_OPERATION + r"(?:этой|данной|указанной)\s+заявкой\s+" + OPERATION_NAME + ")" + DENIAL_END, re.I),
    "item": re.compile(
        r"(?:(?:работы|услуги)\s+(?:из|по)\s+(?:этого|этому|данного|данному|указанного|указанному)\s+пункт[ау]|"
        + REFERENCED_OPERATION + r"(?:этим|данным|указанным)\s+пунктом\s+" + OPERATION_NAME + ")" + DENIAL_END, re.I),
    "instruction": re.compile(
        r"(?:(?:работы|услуги)\s+по\s+(?:этому|данному|указанному)\s+поручению|"
        + REFERENCED_OPERATION + r"(?:им|(?:этим|данным|указанным)\s+поручением)\s+" + OPERATION_NAME + ")" + DENIAL_END, re.I),
}
DEMONSTRATIVE_DENIAL = re.compile(
    r"(?:выполнени[ея]|составлени[ея]|подготовка|разработка|оформление|создание|изготовление)"
    r"\s+(?:этого|данного|этой|данной|этих|данных)\s+(?P<object>[а-яё-]{5,})" + DENIAL_END, re.I)
COMPLETED_WORK = re.compile(
    r"\b(?:выполнен[аоы]?|провед[её]н[аоы]?|оказан[аоы]?|осуществл[её]н[аоы]?|заверш[её]н[аоы]?|"
    r"(?:выполни|пров[её]|оказа|подготови|состави|оформи|заверши|осуществи|"
    r"обработа|сформирова|зарегистрирова|оцифрова|обнови|налади|настрои|проверя|установи)(?:л|ла|ли))\b", re.I)
COST_ALLOCATION = re.compile(
    r"^(?:в\s+полном\s+объ[её]ме\s+)?стоимость"
    r"(?:\s+(?:этих|данных|указанных|выполненных|оказанных|работ|услуг)){0,5}"
    r"\s+(?:(?:полностью|целиком)\s+)?(?:не\s+)?(?:относится|отнесена|учитывается)\s+"
    r"(?:к\s+|в\s+составе\s+)", re.I)
COST_OF_COMPLETED_WORK = re.compile(
    r"^стоимость\s+(?:фактически\s+)?(?:выполненн\w*|оказанн\w*|заверш[её]нн\w*)\s+"
    r"[^.!?]{1,250}\b(?:предъявлен[ао]?|подтвержд[её]н[ао]?|указан[ао]?|включен[ао]?)\s+"
    r"(?:по\s+настоящему\s+акту|в\s+настоящ(?:ем\s+акте|ий\s+акт)|к\s+оплате)\b", re.I)
REPORTED_COMPLETION = re.compile(
    r"^исполнитель\s+(?:указал|зафиксировал|отразил)\s+в\s+(?:настоящем\s+)?акте\s+"
    r"(?:заверш[её]нн\w*|выполненн\w*|оказанн\w*)\s+", re.I)
CELL_PREFIX = re.compile(r"^\s*(?:[A-Z]+\d+:\s*)?", re.I)
TEMPORARY_EQUIPMENT = re.compile(
    r"^(?:(?:предмет|операция|содержание|назначение)\s*:\s*)?"
    r"(?:(?:по\s+настоящему\s+(?:акту|документу)|фактически)\s+)?"
    r"(?:предоставлени[ея]|предоставлен[аоы]?|передач[аи]|передан[аоы]?|аренд[аы])\s+"
    r"(?:(?:специализированн\w*|контрольн\w*|измерительн\w*|испытательн\w*|метрологическ\w*)\s+){0,3}"
    r"(?P<equipment>(?:измерительн\w*|испытательн\w*|метрологическ\w*)\s+"
    r"(?:оборудовани\w*|прибор\w*|стенд\w*|установк\w*))\s+"
    r"(?:во\s+временн\w*\s+пользовани\w*|в\s+аренду)\b", re.I)
STAGE_WORK = re.compile(r"[\s,]+для\s+выполнения\s+работ\s+(?:по\s+)?этап[ау](?:\s+№?\s*\d+)?\b", re.I)
OTHER_ALLOCATION = re.compile(
    r"\b(?:заработн\w*\s+плат\w*|оплат\w*\s+труд\w*|страхов\w*\s+взнос\w*|материальн\w*\s+затрат\w*)\b", re.I)
EXTERNAL_EQUIPMENT_CONTEXT = re.compile(
    r"\b(?:смет[аеуы]|проекте\s+(?:акта|договора)|прошл\w*\s+(?:этап|акт|заявк)|"
    r"цитат\w*|образц\w*|справочн\w*|предложен\w*|заявк\w*|поручени\w*)\b", re.I)
EQUIPMENT_REVIEW_SCOPE = sorted(OVERHEAD | {"other"})


def content_text(value):
    return CELL_PREFIX.sub("", value, count=1)


def is_metadata(value):
    if ORGANIZATION_HEADER.search(value):
        return True
    if not METADATA.search(value):
        return False
    sentence = content_text(value)
    contractor = re.match(r"исполнитель\s+(?:не\s+)?", sentence, re.I)
    if contractor and (COMPLETED_WORK.match(sentence, contractor.end()) or REPORTED_COMPLETION.match(sentence)):
        return False
    return not ((COST_ALLOCATION.match(sentence) or COST_OF_COMPLETED_WORK.match(sentence))
                and (ADMIN.search(sentence) or PRODUCTION.search(sentence)))


def is_purpose_line(line):
    if is_metadata(line):
        return False
    content = content_text(line)
    if OLD_REQUEST.match(content) or REQUEST_CANCELLATION.match(content):
        return True
    if any(pattern.search(line) for pattern in (
            ACTION, COMPLETED_WORK, WORK_CONTEXT, PURPOSE_LABEL, PURCHASE, DENIED_SERVICE,
            DENIED_OPERATION, NARRATIVE_CONTEXT, REPORTED_COMPLETION, ADMIN, PRODUCTION)):
        return True
    if TEMPORARY_EQUIPMENT.match(content):
        return True
    risk = any(pattern.search(line) for pattern in (NEGATION, UNPARSED_NEGATIVE, NONASSERTIVE, QUOTED)) or "?" in line
    return allocation_denial_window(line) or bool(risk and (COREFERENCE.search(line) or OPERATION_NOMINAL.search(line)))


def own_requisite_spans(text):
    """Find bounded own-header fields; never erase surrounding purpose text."""
    spans = []
    quotes = list(QUOTED.finditer(text))
    absent = re.compile(ABSENCE_MARKER + r"(?![\w/\\-])", re.I)
    date = re.compile(DATE_TAIL, re.I)
    cells = header_cells(text)
    for index, cell in enumerate(cells):
        previous_foreign = FOREIGN_LABEL.match(cells[index - 1]['text']) if index else None
        if (any(q.start() <= cell['start'] < q.end() for q in quotes)
                or (previous_foreign and not cells[index - 1]['text'][previous_foreign.end():].strip())):
            continue
        value = cell['text']
        own, heading = OWN_LABEL.match(value), OWN_HEADER.match(value)
        if own:
            start, basis = own.end(), 'own_number_label'
        elif heading:
            start, basis = heading.end(), 'own_document_header'
            if start == len(value):
                spans.append({'start':cell['start'],'end':cell['end'],'text':value,'line':cell['line'],'basis':basis})
                continue
            marker = MARKER.match(value, start)
            if marker:
                start = marker.end()
        else:
            continue
        while start < len(value) and value[start].isspace():
            start += 1
        marker, token, empty_date = absent.match(value, start), TOKEN.match(value, start), date.match(value, start)
        if marker:
            end = marker.end()
        elif empty_date:
            end = empty_date.end()
        elif token and any(c.isdigit() for c in token.group()):
            end = token.end()
        elif start == len(value) and own:
            end = start
        else:
            continue
        tail = re.match(r'\s*', value[end:]).end() + end
        dated = date.match(value, tail)
        if dated:
            end = dated.end()
        if end and (end == len(value) or value[end].isspace() or value[end] in '.,;:!?|'):
            spans.append({'start':cell['start'],'end':cell['start']+end,'text':value[:end],'line':cell['line'],'basis':basis})
    return spans


def mask_requisites(text, spans):
    chars = list(text)
    for span in spans:
        for position in range(span['start'], span['end']):
            if chars[position] not in '\r\n':
                chars[position] = ' '
    return ''.join(chars)


NEGATION_BOUNDARY = re.compile(
    r"[.;!?]|\b(?:а|но)\b|\bи\s+(?:учитыва\w*|относи\w*|относя\w*|предназнач\w*|использу\w*|служ\w*|явля\w*)\b", re.I)
SUPPORTED_NEGATIVE_PREFIX = re.compile(
    r"(?:не\s+(?:(?:для|на)\s+)?"
    r"|не\s+отно(?:сится|сятся)\s+(?:непосредственно\s+)?к\s+(?:отдельн\w*\s+)?"
    r"|не\s+учитыва(?:ются|ется)\s+(?:в\s+составе|как)\s+"
    r"|не\s+явля(?:ются|ется)\s+"
    r"|не\s+предназначен(?:ы|о|а)?\s+для\s+"
    r"|не\s+использу(?:ется|ются)\s+для\s+"
    r"|(?:без|кроме|исключая)\s+(?:(?:участия|затрат|расходов|нужд|использования)\s+)?)", re.I)

BACKWARD_COMPLEMENT = re.compile(
    r"\bк\s+(?:отдельн\w*\s+)?(?P<allocation>"
    r"(?:общепроизводственн|производственн|лабораторн|административн|общехозяйственн|управленческ)\w*"
    r"\s+(?:затрат|расход|деятельност|операци|обеспечени|нужд|обслуживани)\w*)"
    r"(?:\s+(?:(?:эти|данн\w*|указанн\w*|настоящ\w*|это|так\w*|техническ\w*)\s+){0,2}"
    r"(?:услуг|работ|обслуживани|расход|затрат|обеспечени)\w*)?\s*$", re.I)
UNALLOCATED_AMOUNT = re.compile(
    r"\s*(?:раздельн\w*\s+)?(?:стоимость|сумм[аы]|расходы|затраты|"
    r"(?:распределение|разбивка)(?:\s+(?:сумм\w*|стоимости|расходов|затрат))?)"
    r"(?:\s+(?:работ|услуг))?"
    r"(?:\s+(?:по|между)\s+(?:направлени\w*|подразделени\w*|стать\w*|категори\w*|вид\w*\s+работ))?"
    r"\s+не\s+(?:определ[её]н|указан|привед[её]н|выдел[её]н|раздел[её]н|распредел[её]н|представлен)\w*\s*", re.I)


def clause_bounds(text, position):
    before = list(re.finditer(r"[.;!?]", text[:position]))
    start = before[-1].end() if before else 0
    after = re.search(r"[.;!?]", text[position:])
    end = position + after.start() if after else len(text)
    return start, end


def allocation_denial_window(text):
    """Retain explicit allocation denials even on a separate source line.

    Selection is not acceptance: questions, conditions and unsupported tails
    still reach the conservative polarity guard below.
    """
    for match in NEGATION.finditer(text):
        start, _ = clause_bounds(text, match.start())
        if BACKWARD_COMPLEMENT.search(text[start:match.start()]):
            return True
    return bool(re.search(r"\bне\s+(?:отно(?:сится|сятся)|предназначен(?:ы|о|а)?|использу(?:ется|ются))\s+", text, re.I)
                and (ADMIN.search(text) or PRODUCTION.search(text)))


def supported_backward_prefix(prefix):
    value = re.sub(r"^\s*(?:[A-Z]+\d+:\s*)?", "", prefix, flags=re.I)
    label = PURPOSE_LABEL.match(value)
    if label:
        value = value[label.end():].lstrip()
    return BACKWARD_COMPLEMENT.fullmatch(value)


def allocation_polarity(text):
    """Recognize only bounded literal positive/negative role assertions.

    A supported negation applies to its role phrase, including coordinated roles,
    until an explicit contrasting/affirmative clause. A sole denial cannot imply
    the opposite article. Unsupported syntax remains guarded.
    """
    roles = sorted([{"category": category, "start": m.start(), "end": m.end(),
                     "text": m.group(), "polarity": "positive"}
                    for category, pattern in (("general_admin", ADMIN), ("production_overhead", PRODUCTION))
                    for m in pattern.finditer(text)], key=lambda item: item["start"])
    guarded = bool(re.search(r"\bне\s+только\b", text, re.I) or DENIED_SERVICE.search(text))
    allocation_notes = []
    for match in NEGATION.finditer(text):
        tail = text[match.end():]
        if re.match(r"\s+(?:ндс\b|перерыв\w*\b|просто\w*\b|задерж\w*\b)", tail, re.I):
            continue
        if match.group().casefold() == "без" and re.match(
                r"\s+(?:замечаний|претензий|нареканий)(?:\s+по\s+качеству)?\s*(?:[.,;!?]|$)", tail, re.I):
            continue
        clause_start, clause_end = clause_bounds(text, match.start())
        clause = text[clause_start:clause_end]
        if UNALLOCATED_AMOUNT.fullmatch(clause):
            # This denies a numeric breakdown, not either service purpose.
            # It can preserve scope only when BOTH positive functions are
            # independently present outside this amount-only statement.
            allocation_notes.append((clause_start, clause_end))
            continue
        boundary = NEGATION_BOUNDARY.search(text, match.end())
        end = boundary.start() if boundary else len(text)
        if match.group().casefold() == "не" and re.fullmatch(r"\s+отно(?:сится|сятся)\s*,?\s*", text[match.end():end], re.I):
            prefix = text[clause_start:match.start()]
            backward = BACKWARD_COMPLEMENT.search(prefix)
            if backward and supported_backward_prefix(prefix) and text[clause_end:clause_end + 1] != "?":
                start = clause_start + backward.start("allocation")
                end = clause_start + backward.end("allocation")
                for role in roles:
                    if start <= role["start"] < end:
                        role["polarity"] = "negative"
                continue
        end = boundary.start() if boundary else len(text)
        affected = [r for r in roles if match.end() <= r["start"] < end]
        if not affected:
            guarded = True
            continue
        prefix = text[match.start():affected[0]["start"]]
        if len(prefix) > 100 or not SUPPORTED_NEGATIVE_PREFIX.fullmatch(prefix):
            guarded = True
            continue
        for role in affected:
            role["polarity"] = "negative"
    if allocation_notes:
        for role in roles:
            if any(start <= role["start"] < end for start, end in allocation_notes):
                role["polarity"] = "allocation_context"
        independent_positive = {r["category"] for r in roles if r["polarity"] == "positive"}
        if independent_positive != OVERHEAD:
            guarded = True
    return roles, guarded


def purpose_excerpts(text, analysis_text=None):
    """Return small literal windows around work descriptions, with line locators.

    A continuation is retained for PDF line wrapping. Requisites and signatories
    never start a purpose window. This is deliberately a bounded heuristic, not
    a claim to cover arbitrary native layouts.
    """
    lines = text.splitlines()
    literal_lines = text.splitlines(keepends=True)
    analyzed = (analysis_text if analysis_text is not None else text).splitlines()
    excerpts = []
    for index, line in enumerate(analyzed):
        # A header-like first sentence need not make the remaining prose on
        # the physical line metadata. Assertion parsing still checks each span.
        if not any(is_purpose_line(part) for part in re.split(r'(?<=[.!?])\s+', line)):
            continue
        block = [lines[index]]
        analysis_block = [line]
        for next_index in range(index + 1, min(index + 3, len(lines))):
            following = analyzed[next_index]
            if not following.strip() or is_metadata(following) or re.search(r"наименование|сумма,?\s*руб", following, re.I):
                break
            # Another sentence starts its own observation; retain only natural
            # wraps or an explicit one-line label's value.
            if analysis_block[-1].rstrip().endswith((".", ";")):
                break
            block.append(lines[next_index])
            analysis_block.append(following)
        joined = ''.join(literal_lines[index:index + len(block)]).rstrip('\r\n')
        if not any(joined == old["text"] for old in excerpts):
            excerpts.append({"line_start": index + 1, "line_end": index + len(block), "text": joined})
    return excerpts


def source_statements(excerpts, source_text=None, excluded_spans=()):
    """Literal sentence-sized assertions; a line is a locator, not a claim."""
    seen = set()
    source_lines = source_text.splitlines(keepends=True) if source_text is not None else []
    line_offsets, offset = [], 0
    for source_line in source_lines:
        line_offsets.append(offset)
        offset += len(source_line)
    quotes = list(QUOTED.finditer(source_text)) if source_text is not None else []
    for excerpt in excerpts:
        full = source_text if source_text is not None else excerpt['text']
        base = line_offsets[excerpt['line_start'] - 1] if source_text is not None else 0
        local_quotes = quotes if source_text is not None else list(QUOTED.finditer(full))
        pieces, cursor = [], 0
        for excluded in sorted(excluded_spans, key=lambda s:s['start']):
            left, right = max(0,excluded['start']-base), min(len(excerpt['text']),excluded['end']-base)
            if left >= right:
                continue
            if cursor < left:
                pieces.append((cursor,left))
            cursor=max(cursor,right)
        if cursor < len(excerpt['text']):
            pieces.append((cursor,len(excerpt['text'])))
        matches = [(left+m.start(),left+m.end(),m.group()) for left,right in pieces
                   for m in re.finditer(r"[^.;!?]+[.;!?]?",excerpt['text'][left:right])]
        for match_start, match_end, raw in matches:
            if not raw.strip():
                continue
            start = match_start + len(raw) - len(raw.lstrip())
            value = raw.strip()
            if not re.search(r'\w',value):
                continue
            line = excerpt["line_start"] + excerpt["text"][:start].count("\n")
            key = (line, value)
            if key in seen:
                continue
            seen.add(key)
            quote_context = []
            for quote in local_quotes:
                if quote.end() <= base + start or quote.start() >= base + match_end:
                    continue
                line_start = full.rfind('\n', 0, quote.start()) + 1
                prefix = full[line_start:quote.start()]
                prefix = re.sub(r'^\s*(?:[A-Z]+\d+:\s*)?', '', prefix, flags=re.I)
                own_label = PURPOSE_LABEL.fullmatch(prefix.strip()) is not None
                named_entity = (NAMED_RECIPIENT.search(prefix) is not None
                    and not re.search(r'[.;!?]', quote.group())
                    and not NARRATIVE_CONTEXT.search(prefix)
                    and bool(ACTION.search(prefix) or WORK_CONTEXT.search(prefix) or PURPOSE_LABEL.search(prefix)))
                quote_context.append({'source_start': quote.start(), 'source_end': quote.end(),
                    'text': quote.group(), 'kind': 'own_purpose_value' if own_label else 'named_recipient' if named_entity else 'quoted_assertion'})
            yield {"line_start": line, "line_end": line + value.count("\n"),
                   "excerpt_char_start": start, "excerpt_char_end": match_end, "text": value,
                   'source_char_start':base+start,'source_char_end':base+match_end-len(raw)+len(raw.rstrip()),
                   'quote_context': quote_context}


def is_adjacent(left, right, text):
    return (left['source_char_end'] <= right['source_char_start']
            and not text[left['source_char_end']:right['source_char_start']].strip())


def in_external_quote(statement):
    return any(q['kind'] == 'quoted_assertion' for q in statement['quote_context'])


def follows_same_cancellation(value, kind, quote):
    if FOLLOWUP_DENIAL[kind].fullmatch(value):
        return True
    match = DEMONSTRATIVE_DENIAL.fullmatch(value)
    if not match:
        return False
    noun = match.group('object').casefold().rstrip('аыяиеу')
    return len(noun) >= 5 and any(
        word.rstrip('аыяиеу') == noun for word in re.findall(r'[а-яё-]+', quote['text'].casefold())
    )


def cancelled_request_scopes(statements, text):
    """An explicit immediately preceding old request scopes its own cancellation.

    This attaches only a negative/reference scope. It cannot establish an actual
    service or transfer a quoted category into positive allocation evidence.
    """
    scopes = {}
    for statement in statements:
        cancellation = REQUEST_CANCELLATION.fullmatch(content_text(statement['text']))
        if not cancellation or in_external_quote(statement):
            continue
        earlier = [prior for prior in statements if is_adjacent(prior, statement, text)]
        distinct = {(p['source_char_start'], p['source_char_end']): p for p in earlier}
        if len(distinct) != 1:
            continue
        prior = next(iter(distinct.values()))
        clean = content_text(prior['text'])
        old = OLD_REQUEST.match(clean)
        quotes = [q for q in prior['quote_context'] if q['kind'] == 'quoted_assertion']
        if (not old or len(quotes) != 1 or '?' in clean or len(OLD_REFERENCE.findall(clean)) != 1
                or any(pattern.search(clean) for pattern in (NONASSERTIVE, NEGATION, UNPARSED_NEGATIVE))):
            continue
        quote = quotes[0]
        if not (prior['source_char_start'] <= quote['source_start'] < quote['source_end'] <= prior['source_char_end']):
            continue
        kind = cancellation.lastgroup
        instruction = old.group('kind').casefold().startswith('поручени')
        if instruction != (kind == 'instruction'):
            continue
        if kind == 'item' and not re.search(r'\bпункт\b', text[prior['source_char_start']:quote['source_start']], re.I):
            continue
        categories = set(prior['mentioned_categories'])
        if len(categories) != 1 or any(
                not (quote['source_start'] <= prior['source_char_start'] + role['start'] < quote['source_end'])
                for role in prior['roles']):
            continue
        proof = {
            'request_start': prior['source_char_start'], 'request_end': prior['source_char_end'],
            'request_text': prior['text'], 'quoted_request': quote, 'categories': sorted(categories),
            'cancellation_start': statement['source_char_start'], 'cancellation_end': statement['source_char_end'],
            'cancellation_text': statement['text'], 'basis': 'adjacent_explicit_old_request_cancellation',
        }
        scopes[(statement['source_char_start'], statement['source_char_end'])] = proof
        following = {
            (p['source_char_start'], p['source_char_end']): p for p in statements
            if is_adjacent(statement, p, text) and not in_external_quote(p)
            and follows_same_cancellation(content_text(p['text']), kind, quote)
            and set(p['mentioned_categories']) <= categories
        }
        if len(following) == 1:
            key, followup = next(iter(following.items()))
            scopes[key] = {**proof, 'followup_start': key[0], 'followup_end': key[1], 'followup_text': followup['text']}
    return scopes


def assertion(statement):
    """Parse evidence without granting authority to an unparsed role mention."""
    value = statement["text"]
    roles, unsupported = allocation_polarity(value)
    content = content_text(value)
    equipment = TEMPORARY_EQUIPMENT.match(content)
    equipment_external = equipment is not None and EXTERNAL_EQUIPMENT_CONTEXT.search(value)
    equipment_is_own = (equipment is not None and not equipment_external
                        and not in_external_quote(statement)
                        and not OTHER_ALLOCATION.search(value))
    equipment_with_stage = (equipment_is_own and not ADMIN.search(value)
                            and STAGE_WORK.match(content, equipment.end()))
    if (equipment_with_stage and not NEGATION.search(value) and not unsupported
            and not any(role["category"] == "production_overhead" for role in roles)):
        trim = len(value) - len(content)
        start, end = (pos + trim for pos in equipment.span('equipment'))
        roles.append({'category': 'production_overhead', 'start': start, 'end': end,
                      'text': value[start:end], 'polarity': 'positive'})
        roles.sort(key=lambda role: role["start"])
    mentions = sorted({r["category"] for r in roles})
    result = {**statement, "roles": roles, "mentioned_categories": mentions,
              "positive_categories": [], "negative_categories": [],
              "coreference": bool(COREFERENCE.search(value)), "state": "irrelevant"}
    if is_metadata(value):
        result["reason"] = "metadata_is_not_purpose"
        return result
    context = (any(pattern.search(value) for pattern in (ACTION, COMPLETED_WORK, PURPOSE_LABEL, WORK_CONTEXT))
               or any(pattern.match(content_text(value)) for pattern in
                      (COST_ALLOCATION, COST_OF_COMPLETED_WORK, REPORTED_COMPLETION)))
    quoted = in_external_quote(statement)
    if quoted or NARRATIVE_CONTEXT.search(value) or equipment_external:
        result.update(state="unknown", reason="quoted_or_external_context")
    elif value.endswith("?") or NONASSERTIVE.search(value):
        result.update(state="unknown", reason="nonassertive_statement")
    elif DENIED_SERVICE.search(value):
        result.update(state="denied_service", reason="explicit_service_denial")
    elif PURCHASE.search(value):
        result.update(state="purchase", reason="purchase_requires_separate_allocation")
    elif UNALLOCATED_AMOUNT.fullmatch(value.rstrip(".;! ")):
        result.update(state="amount_context", reason="no_numeric_breakdown")
    elif re.search(r"\bне\s+только\b", value, re.I):
        # This construction is explicitly non-exclusive, never one article.
        result.update(state="nonexclusive", reason="explicit_nonexclusive_purpose")
    elif REQUEST_CANCELLATION.fullmatch(content_text(value)):
        result.update(state="unknown", reason="unresolved_request_cancellation")
    elif unsupported or UNPARSED_NEGATIVE.search(value):
        result.update(state="unknown", reason="unsupported_allocation_syntax")
    elif equipment_with_stage and not NEGATION.search(value):
        result.update(state="asserted", reason="temporary_measurement_equipment_for_stage_work",
                      positive_categories=["production_overhead"])
    elif equipment_is_own and not NEGATION.search(value):
        # The expense is for temporary equipment use, but no allocation
        # between the two overhead articles is supported by this statement.
        result.update(state="unknown", reason="temporary_equipment_allocation_unknown",
                      uncertainty_scope=EQUIPMENT_REVIEW_SCOPE)
    elif roles and (context or any(role["polarity"] == "negative" for role in roles)):
        result.update(state="asserted", reason="bounded_literal_assertion",
            positive_categories=sorted({r["category"] for r in roles if r["polarity"] == "positive"}),
            negative_categories=sorted({r["category"] for r in roles if r["polarity"] == "negative"}))
    elif roles:
        result.update(state="unknown", reason="role_mention_without_work_assertion")
    return result


def classify_source(text):
    metadata = own_requisite_spans(text)
    excerpts = purpose_excerpts(text, mask_requisites(text,metadata))
    # Overlapping PDF windows can emit a complete sentence and its wrapped
    # suffix. Treat them as one assertion to avoid a second, orphaned denial.
    spans = sorted(source_statements(excerpts, text, metadata),
                   key=lambda item: (item['source_char_start'], -item['source_char_end']))
    statements = []
    end = -1
    for item in spans:
        if item['source_char_end'] > end:
            statements.append(assertion(item))
            end = item['source_char_end']
    cancellation_scopes = cancelled_request_scopes(statements, text)
    positive = {category for item in statements for category in item["positive_categories"]}
    negative = {category for item in statements for category in item["negative_categories"]}
    hard, unresolved, uncertain_roles = [], [], set()
    for item in statements:
        state = item["state"]
        mentioned = set(item["mentioned_categories"])
        # A denial/question about an explicitly DIFFERENT function is not a
        # denial of the independently established service. Anaphoric references
        # remain potentially about the same service and cannot bypass review.
        other_only = bool(positive and mentioned and not (positive & mentioned) and not item["coreference"])
        item["relation_to_positive"] = "other_article_only" if other_only else "same_or_unresolved"
        neutral_other = state == 'unknown' and item.get('reason') == 'role_mention_without_work_assertion' and other_only
        cancellation = cancellation_scopes.get((item['source_char_start'], item['source_char_end']))
        if cancellation:
            item['cancelled_request_scope'] = cancellation
        if cancellation and positive and not positive.intersection(cancellation['categories']):
            item['relation_to_positive'] = 'explicit_cancelled_prior_request_only'
            item['decision_effect'] = 'does_not_veto_independent_actual_work'
        elif state in {"denied_service", "unknown"} and other_only and not neutral_other:
            item["decision_effect"] = "does_not_veto_independent_positive"
        elif (state == "unknown" and item.get("reason") == "role_mention_without_work_assertion"
                and mentioned and mentioned <= positive and not item["coreference"]):
            # A neutral description is not proof, but lexical non-coverage is
            # not a contradiction of an independent affirmative allocation.
            # Negative/nonassertive/quoted/external clauses have distinct states
            # or reasons above and can never enter this non-veto branch.
            item["decision_effect"] = "neutral_same_article_nonveto"
            item["neutral_basis"] = "independent_affirmative_same_article"
        elif state in {"denied_service", "purchase", "nonexclusive"}:
            hard.append(item["reason"])
            item["decision_effect"] = "abstain"
        elif state == "unknown":
            unresolved.append(item["reason"])
            if neutral_other:
                uncertain_roles.update(mentioned)
            item["decision_effect"] = "financial_unchecked"
        else:
            item["decision_effect"] = "evidence" if state == "asserted" else "none"
    if positive & negative:
        hard.append("same_article_affirmed_and_denied")
    if negative and not positive:
        hard.append("negative_only_does_not_prove_opposite")
    details = {"excerpts": excerpts, "statements": statements, 'own_requisite_spans':metadata,
        "role_assertions": [{k: item[k] for k in ("line_start", "line_end", "roles", "state")} for item in statements],
        "positive_categories": sorted(positive), "negative_categories": sorted(negative),
        "hard_reasons": sorted(set(hard)), "unchecked_reasons": sorted(set(unresolved))}
    candidates = sorted(positive | uncertain_roles)
    if (not hard and set(unresolved) == {"temporary_equipment_allocation_unknown"}
            and not positive and not OTHER_ALLOCATION.search(text)):
        candidates = EQUIPMENT_REVIEW_SCOPE
        details["scope_basis"] = "literal_temporary_equipment_use"
    if "purchase_requires_separate_allocation" in hard:
        candidates = []  # Purchase may involve an article outside this rule.
    if hard:
        return {"status": "guarded_purpose", "category": None, "candidates": candidates,
                "decision": "abstain", "financial_usable": False, **details}
    if len(positive) > 1:
        return {"status": "mixed_purpose", "category": None, "candidates": candidates,
                "decision": "abstain", "financial_usable": False, **details}
    if unresolved or not positive:
        return {"status": "parser_inconclusive", "category": None, "candidates": candidates,
                "decision": "unchecked", "financial_usable": False, **details}
    return {"status": "explicit_purpose", "category": next(iter(positive)), "candidates": candidates,
            "decision": "resolved", "financial_usable": True, **details}


def apply_source_checks(record, native_text=None):
    """Return a copied extraction with auditable, native-source-only allocation.

    Existing payroll/insurance/other allocation is outside this bounded overhead
    rule. The original model answer is retained, even when the category changes.
    Amount, identifiers and dates are never inferred or changed by this module.
    """
    checked = deepcopy(record)
    prediction = checked.get("prediction")
    if not isinstance(prediction, dict):
        return checked
    checked.setdefault("raw_prediction", deepcopy(prediction))
    # Repeat checks and byte-alias replay must keep the original comparison,
    # not relabel a prior correction as an independently confirmed model answer.
    original = checked["raw_prediction"].get("category")
    prediction["category"] = original
    if not isinstance(native_text, str) or not native_text.strip():
        checked["category_evidence"] = {"version": VERSION, "status": "native_source_unavailable",
            "source_verified": False, "source_hash": checked.get("source_hash"), "candidates": [], "excerpts": [],
            "decision": "model_only", "financial_usable": None, "gate_applies": False,
            "original_category": prediction.get("category"), "effective_category": prediction.get("category"), "changed": False}
        return checked
    evidence = classify_source(native_text)
    checked.setdefault("source_native_text", native_text)
    evidence.update(version=VERSION, source_verified=True, source_hash=checked.get("source_hash"),
        native_text_sha256=hashlib.sha256(native_text.encode()).hexdigest(),
        original_category=original, gate_applies=True)
    if original in OVERHEAD or original is None:
        if evidence["decision"] in {"resolved", "abstain"}:
            prediction["category"] = evidence["category"]
        if evidence["decision"] == "resolved":
            evidence["decision"] = "confirmed" if prediction["category"] == original else "corrected"
    else:
        evidence["status"] = "outside_overhead_rule"
        evidence["candidates"] = []
        evidence.update(source_verified=False, decision="outside_gate", financial_usable=None, gate_applies=False)
    evidence["effective_category"] = prediction.get("category")
    evidence["changed"] = evidence["effective_category"] != original
    checked["category_evidence"] = evidence
    return checked
