"""Select monetary observations and their scope from an uploaded original."""

import re
from calendar import monthrange
from dataclasses import dataclass
from decimal import Decimal
from math import ulp
from pathlib import Path
from uuid import UUID

from doccheck_backend.contracts.locators import (
    Locator,
    PageLocator,
    ParagraphLocator,
    SheetLocator,
    TableCellLocator,
)
from doccheck_backend.contracts.result import EvidenceKind, FileFormat, Period
from doccheck_backend.evidence_binding import ObservationAssertion
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation
from doccheck_backend.native_reader import _text_amount, read_native_document
from doccheck_backend.normalization import normalize_contract_number, normalize_document_date
from doccheck_backend.page_ocr import page_locator, recognize_lines, render_pages

ARTICLES = {
    "payroll": ("0200", "Затраты на оплату труда"),
    "insurance": ("0300", "Страховые взносы"),
    "production_overhead": ("0800", "Общепроизводственные затраты"),
    "general_admin": ("0900", "Общехозяйственные затраты"),
    "other": (None, "Прочие расходы"),
}
_TITLES = {
    "расчетная ведомость по оплате труда": "payroll",
    "расчет страховых взносов": "insurance",
    "расчетная ведомость заработной платы": "payroll",
    "ведомость начисленных страховых взносов": "insurance",
}
_MONTHS = (
    ("январь", "января", "январе"),
    ("февраль", "февраля", "феврале"),
    ("март", "марта", "марте"),
    ("апрель", "апреля", "апреле"),
    ("май", "мая", "мае"),
    ("июнь", "июня", "июне"),
    ("июль", "июля", "июле"),
    ("август", "августа", "августе"),
    ("сентябрь", "сентября", "сентябре"),
    ("октябрь", "октября", "октябре"),
    ("ноябрь", "ноября", "ноябре"),
    ("декабрь", "декабря", "декабре"),
)
_MONTH = {name: i for i, variants in enumerate(_MONTHS, 1) for name in variants}
_PERIOD_TITLE = r"(?:^\s*|\|\s*)(?:отч[её]тный\s+)?период\b"
_PERIOD_LABEL = (
    rf"{_PERIOD_TITLE}(?:\s+[\w-]+){{0,4}}\s*[:—–-]\s*"
    rf"|{_PERIOD_TITLE}(?:\s+(?:оказания\s+услуг|выполнения\s+работ))?\s+"
)
_MONTH_YEAR = rf"({'|'.join(_MONTH)})\s+([0-9]{{4}})\b(?:\s+(?:года?\b|г\b\.?))?"
_MONTH_PERIOD = re.compile(rf"(?:(?:{_PERIOD_LABEL})(?:с\s+)?|\bза\s+|\bв\s+){_MONTH_YEAR}", re.I)
_MONTH_RANGE_END = re.compile(rf"\s*(?:[—–\-/]|\bпо\b|\bдо\b)\s*{_MONTH_YEAR}", re.I)
_PERIOD_CONTINUATION = re.compile(r"^\s*(?:[—–\-/]|\bпо\b|\bдо\b)", re.I)
_PERIOD_FIELD = re.compile(_PERIOD_TITLE, re.I)
_DAY = r"(?:[0-9]{2}\.[0-9]{2}\.[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
_ADDITIONAL_PERIOD = re.compile(
    rf"^\s*(?:г(?:ода?)?\.?\s*)?(?:[.,;+/&]\s*)?"
    rf"(?:(?:и|или|а\s+также)\s+)?(?:с\s+|за\s+|в\s+)?"
    rf"(?:{_DAY}|[0-9]{{1,2}}[./][0-9]{{1,2}}|(?:{'|'.join(_MONTH)})\b|период\b)",
    re.I,
)
_ADDITIONAL_PERIOD_PREFIX = re.compile(r"^\s*(?:и|или|а\s+также)\s+с(?:\s+|$)", re.I)
_ONLY_RUBLE_VALUE = re.compile(
    r"^[+−-]?\s*[0-9][0-9 ,.\u00a0\u2009\u202f]*\s*"
    r"(?:руб(?:\.|лей|ля|ль)?|р\.|₽|RUB)\.?$",
    re.I,
)
_DURATION_QUANTITY = (
    r"(?:[0-9]+(?:[.,][0-9]+)?|од(?:ин|на|но|ну|ного|ной)|два|две|двух|двест\w*|"
    r"три|тр[её]х|трист\w*|четыр\w*|пят\w*|шест\w*|сем\w*|восем\w*|восьм\w*|"
    r"девят\w*|девяност\w*|десят\w*|одиннадцат\w*|двенадцат\w*|тринадцат\w*|"
    r"двадцат\w*|тридцат\w*|сорок\w*|сто|ста|сот\w*|тысяч\w*|полтор\w*|"
    r"нескольк\w*|пару|пара)"
)
_DURATION_UNIT = (
    r"(?:(?:день|дня|дней|сутки|суток|недел\w*|месяц\w*|квартал\w*|"
    r"полугоди\w*|год(?:а|ов|у|ом)?|лет|час(?:а|ов|у|ом)?|минут\w*)\b|"
    r"(?:дн|сут|нед|мес|кв|г|ч|мин)(?:\.(?=\s|$|[,;])|(?=\s|$|[,;])))"
)
_DURATION = re.compile(
    rf"^\s*(?:(?:на|за|в\s+течени[еи]|на\s+протяжении|(?:на\s+)?срок(?:ом)?(?:\s+на)?|"
    rf"(?:продолжительност(?:ь|ью)|длительност(?:ь|ью))(?:\s+в)?)\s*[:：]?\s+)?"
    rf"(?:(?:около|примерно|не\s+менее|не\s+более)\s+)?"
    rf"(?:(?:от\s+)?{_DURATION_QUANTITY}"
    rf"(?:\s*(?:[–—-]|\bдо\b)\s*{_DURATION_QUANTITY})?"
    rf"(?:\s+{_DURATION_QUANTITY}){{0,3}}\s+"
    rf"(?:(?:рабоч\w*|календарн\w*|полн\w*|неполн\w*)\s+){{0,2}}{_DURATION_UNIT}"
    rf"|пол(?:года|месяца|суток|недели)\b"
    rf"|(?:неопредел[её]нн\w*|неизвестн\w*|неограниченн\w*)\s+(?:срок|период)\b"
    rf"|(?:время|период)\s+(?:оказания|обслуживания|работы|действия|эксплуатации)\b"
    rf"|бессрочно\b)",
    re.I,
)
_SINGLE_DURATION = re.compile(
    rf"^\s*(?:на|за|в\s+течени[еи])\s+(?:(?:весь|всю|целый|целую|целое)\s+)?"
    rf"{_DURATION_UNIT}",
    re.I,
)
_ADJECTIVAL_DURATION = re.compile(
    r"^\s*(?:на|сроком\s+на|продолжительностью\s+в)\s+"
    r"(?:[0-9]+[-‑]|одно|двух|тр[её]х|четыр[её]х|полу)"
    r"(?:летн\w*|месячн\w*|дневн\w*|недельн\w*)\s+(?:срок|период)\b",
    re.I,
)
_MONTH_ABBREVIATION = r"(?:янв|фев|мар|апр|июн|июл|авг|сен|сент|окт|ноя|дек)"
_PERIOD_BOUND_START = re.compile(
    rf"^(?:\?|[0-9]{{1,4}}(?=$|[./-][0-9?]|\s+(?:{'|'.join(_MONTH)}|г(?:ода?)?)\b"
    rf"|\s+{_MONTH_ABBREVIATION}(?:\.|\s|$))"
    rf"|(?:{'|'.join(_MONTH)})\b|{_MONTH_ABBREVIATION}(?:\.(?=\s|$)|(?=\s+[0-9]{{4}}\b))"
    rf"|[а-яё]{{2,10}}\.\s+[0-9]{{4}}\b|с\b|неразборчив\w*|неизвест\w*"
    rf"|настоящ(?:ее\s+время|его\s+времени|ий\s+момент|его\s+момента)\b"
    rf"|текущ(?:ая\s+дата|ую\s+дату|ий\s+момент|его\s+(?:дня|месяца|года|момента))\b"
    rf"|сегодня(?:шний\s+день)?\b|(?:конец|конца|начало|начала|середина|середины"
    rf"|окончание|окончания|завершение|завершения)\b)",
    re.I,
)
_BARE_DATE_RANGE = re.compile(rf"^\s*(?:с\s+)?{_DAY}(?:\s+г\.?)?\s*(?:по\b|до\b|[–—-])", re.I)
_BARE_MONTH_PERIOD = re.compile(rf"^\s*(?:(?:с|за|в)\s+)?{_MONTH_YEAR}", re.I)
_DATE_RANGE = re.compile(
    rf"(?:{_PERIOD_LABEL})(?:с\s+)?({_DAY})(?:\s+г\.?)?\s*(?:по|до|[–—-])\s*({_DAY})\b",
    re.I,
)
_DATE = re.compile(rf"^дата(?:\s+документа)?\s*[:№]?\s*({_DAY})(?:\s*г\.?)?$", re.I)
_HEADER_DATE = re.compile(
    rf"^(?:акт|счет-акт|счёт-акт|упд)\b[^\n]{{0,72}}?\bот\s+({_DAY})(?:\s*г\.?)?$", re.I
)
_OPERATION_DATE = re.compile(
    rf"^(?:услуги\s+оказаны|услуга\s+оказана|работы\s+выполнены|"
    rf"дата\s+оказания\s+услуг(?:и)?|дата\s+выполнения\s+работ(?:ы)?)\s*"
    rf"(?:[:—–-]\s*)?({_DAY})(?:\s*г\.?)?\.?$",
    re.I,
)
_CONTRACT_ID = r"[\w]+(?:[/-][\w]+)*"
_STAGE_FIELD = re.compile(
    r"^(?:номер\s+)?этап(?:\s+работ)?(?:\s*[:|—–-]\s*|\s+(?=№|[0-9])|(?=№|$))(.*)$",
    re.I,
)
_STAGE_VALUE = re.compile(r"(?:№\s*)?0*([1-9][0-9]*)[.]?")
_STAGE_CONTINUATION = re.compile(r"^(?:[,;/—–-]|и\s+|по\s+|до\s+)\s*(?:№\s*)?[0-9]", re.I)
_CONTRACT_TYPE = r"(?:подряда|поставки|аренды|купли-продажи|оказания\s+услуг|выполнения\s+работ)"
_CONTRACT_MARKER = r"(?:№\s*|N[eoо°º]\.?\s+)"
_CONTRACT = re.compile(
    rf"^(?:(?:по\s+|основание\s*:?\s*)?договор(?:у)?|контракт)(?=\s|[:№])\s*:?\s*"
    rf"(?:(?:{_CONTRACT_TYPE}\s+)?{_CONTRACT_MARKER}|(?=[\w/-]*[0-9]))"
    rf"({_CONTRACT_ID})(?=$|[\s,.;|])",
    re.I,
)
_BASIS = re.compile(r"^основание\s*:?\s*([0-9]+(?:/[0-9]+){2}-[0-9]+)$", re.I)
_PROJECT = re.compile(rf"^проект\s*:\s*({_CONTRACT_ID})(?=$|\s*\|)", re.I)
_LABEL = re.compile(r"^(?:договор|контракт|основание|дата(?:\s+документа)?)\s*:?$", re.I)
_BASIS_ID = re.compile(r"[\w]+(?:[/‑-][\w]+)+")
_FINAL_LABEL = (
    r"(?:итого(?:\s+(?:к\s+(?:оплате|уч[её]ту)|стоимость\s+(?:услуг|работ)))?"
    r"|всего\s+к\s+(?:оплате|уч[её]ту)|к\s+оплате(?:\s+по\s+документу)?)"
)
_TOTAL_LABEL = re.compile(
    r"^(?:сумма(?:\s+по\s+акту)?|стоимость(?:\s+(?:оказанных\s+)?услуг"
    r"(?:\s+за\s+расчетный\s+период)?)?)\s*[:：]",
    re.I,
)
_FINAL_VALUE = re.compile(rf"^{_FINAL_LABEL}(?:\s*[:：—–]\s*|\s+-\s+|\s+)(?=[+−-]?[0-9])", re.I)
_FINAL_CELL = re.compile(rf"^{_FINAL_LABEL}\s*[:.：]?$", re.I)
_FINAL_LINE = re.compile(rf"^{_FINAL_LABEL}(?=[\s:：.—–-]|$)", re.I)
_BARE_FINAL = re.compile(
    r"-?(?:[0-9]+|[0-9]{1,4}(?: [0-9]{3})+)[,.][0-9]{2}",
)
_OCR_LABEL_MAP = str.maketrans("ABCEHKMOPTXYabcehkmoptxy", "АВСЕНКМОРТХУавсенкмортху")
_AMOUNT_CELL_HEADER = re.compile(r"^(?:сумма|стоимость)\s*[,()]?\s*(?:руб\.?|₽)\)?$", re.I)
_PAGE_RUB_HEADER = re.compile(
    r"^(?:наименование\s+)?(?:сумма|стоимость)\s*[,()]?\s*(?:руб\.?|₽)\)?$", re.I
)
_RUB_DECLARATION = re.compile(r"^(?:все )?сумм[аы] указан[аы] в рублях(?:[.,]|$)", re.I)
_OTHER_CURRENCY = re.compile(
    r"\b(?:USD|EUR|CNY|GBP|JPY|KZT|BYN|доллар\w*|евро|юан\w*)\b|[€$¥£]", re.I
)
_WHOLE_RUBLES = Decimal("0.01")
_PDF_OCR_ISSUES = {"clipped_pdf_text", "no_native_text"}
_ISSUER_REQUISITES = re.compile(r"\s*[,;(]?\s*(?:инн|кпп|огрн(?:ип)?)\s*(?:[:№]\s*)?[0-9].*$")
_ISSUER_TAX_ID = re.compile(r"\bинн\b\s*(?:[:№]\s*)?([0-9]{12}|[0-9]{10})(?![0-9])")
_ISSUER_FORMS = {
    "общество с ограниченной ответственностью": "ооо",
    "публичное акционерное общество": "пао",
    "акционерное общество": "ао",
    "индивидуальный предприниматель": "ип",
}


@dataclass(frozen=True)
class GroundedDocument:
    assertions: tuple[ObservationAssertion, ...]
    category: str | None
    contract: str | None
    period: Period | None
    amount: str | None
    total_locator: Locator | None
    identity_locator: Locator | None
    issues: tuple[NativeIssue, ...]
    text: str
    identity: str | None
    document_kind: str | None
    issuer_key: str | None
    issuer_tax_id: str | None
    stage_uncertain: bool
    period_ambiguous: bool
    period_date_conflict: bool


def _norm(text: str) -> str:
    normalized = " ".join(text.casefold().replace("ё", "е").split())
    return normalized.removesuffix(" — синтетический документ").removesuffix(
        " - синтетический документ"
    )


def _read_observations(
    path: Path, format_: FileFormat
) -> tuple[NativeDocument, str, tuple[Observation, ...]]:
    native = read_native_document(path, format_)
    # Use full-page OCR when images or clipped text may hide part of the document.
    # Unsupported PDF visibility is left to review instead of mixing layers.
    render = format_ == "png" or (
        format_ == "pdf"
        and (native.has_raster_content or native.issues)
        and all(issue.code in _PDF_OCR_ISSUES for issue in native.issues)
    )
    if not render:
        return native, "native", ()
    observations = []
    potential = []
    issues = []
    for page, image in enumerate(render_pages(path), 1):
        before = len(observations)
        for line in recognize_lines(image):
            text = line.text.strip()
            normalized = text.translate(_OCR_LABEL_MAP)
            if (_FINAL_LINE.match(normalized) or _TOTAL_LABEL.match(normalized)) and (
                line.confidence < 50 or not (_FINAL_LINE.match(text) or _TOTAL_LABEL.match(text))
            ):
                issues.append(
                    NativeIssue("unreadable_amount_line", page_locator(page, image, line.box))
                )
                continue
            observation = Observation(text, page_locator(page, image, line.box))
            potential.append(observation)
            if line.confidence >= 50:
                observations.append(observation)
        if len(observations) == before:
            issues.append(NativeIssue("no_addressed_source_text", page=page))
    # Weak readings can veto an assertion without becoming evidence themselves.
    return NativeDocument(tuple(observations), tuple(issues)), "ocr", tuple(potential)


def _following(label: Observation, value: Observation) -> bool:
    first, second = label.locator, value.locator
    return (
        isinstance(first, PageLocator)
        and isinstance(second, PageLocator)
        and first.page == second.page
        and first.bbox is not None
        and second.bbox is not None
        and 0 <= second.bbox[1] - first.bbox[1] <= 0.10
    )


def _duration_continuation(text: str) -> bool:
    # Duration is only a veto: it does not establish a computed end date.
    return bool(
        _DURATION.match(text) or _SINGLE_DURATION.match(text) or _ADJECTIVAL_DURATION.match(text)
    )


def _period_continuation(text: str) -> bool:
    match = _PERIOD_CONTINUATION.match(text)
    if not match:
        return False
    rest = text[match.end() :].strip()
    if _ONLY_RUBLE_VALUE.fullmatch(rest) and _text_amount(rest)[0] is not None:
        return False
    if _duration_continuation(rest):
        return True
    rest = re.sub(r"^(?:по|до|на)(?:\s+|$)", "", rest, flags=re.I).strip()
    # A delimiter followed by unrelated prose (e.g. "по договору") is not
    # another period; a missing or period-shaped bound remains uncertain.
    return not rest or bool(_PERIOD_BOUND_START.match(rest))


def _additional_period_prefix(text: str) -> bool:
    match = _ADDITIONAL_PERIOD_PREFIX.match(text)
    if not match:
        return False
    rest = text[match.end() :].strip()
    return not rest or bool(_PERIOD_BOUND_START.match(rest))


def _period_following(first: Observation, second: Observation) -> bool:
    left, right = first.locator, second.locator
    return (
        left == right
        or _following(first, second)
        or (
            isinstance(left, ParagraphLocator)
            and isinstance(right, ParagraphLocator)
            and right.paragraph == left.paragraph + 1
        )
        or (
            isinstance(left, TableCellLocator)
            and isinstance(right, TableCellLocator)
            and left.table == right.table
            and (
                (
                    right.cell == left.cell + first.column_span
                    and right.row < left.row + first.row_span
                    and left.row < right.row + second.row_span
                )
                or (
                    right.row == left.row + first.row_span
                    and right.cell < left.cell + first.column_span
                    and left.cell < right.cell + second.column_span
                )
            )
        )
    )


def _additional_pipe_period(tail: str) -> bool:
    for part in tail.split("|")[1:]:
        if _BARE_MONTH_PERIOD.match(part) or _duration_continuation(part):
            return True
        if match := _BARE_DATE_RANGE.match(part):
            rest = part[match.end() :].strip()
            if not rest or _PERIOD_BOUND_START.match(rest):
                return True
    return False


def _stages(
    observations: tuple[Observation, ...],
) -> tuple[list[tuple[str, Observation]], bool]:
    stages = []
    unresolved = False
    for index, observation in enumerate(observations):
        if not (field := _STAGE_FIELD.fullmatch(observation.raw_text.strip())):
            continue
        value = field[1].strip()
        source = observation
        if index + 1 < len(observations):
            following = observations[index + 1]
            label_cell, value_cell = observation.locator, following.locator
            adjacent_cells = (
                isinstance(label_cell, TableCellLocator)
                and isinstance(value_cell, TableCellLocator)
                and (label_cell.table, label_cell.row) == (value_cell.table, value_cell.row)
                and label_cell.cell + 1 == value_cell.cell
            )
            if adjacent_cells or label_cell == value_cell or _following(observation, following):
                next_text = following.raw_text.strip()
                if value in {"", "№"}:
                    value, source = next_text, following
                elif _STAGE_CONTINUATION.match(next_text):
                    unresolved = True
                    continue
        if match := _STAGE_VALUE.fullmatch(value):
            stages.append((match[1], source))
        else:
            unresolved = True
    return stages, unresolved


def _contracts(
    observations: tuple[Observation, ...], *, template: bool
) -> list[tuple[str, Observation]]:
    results = []
    for i, observation in enumerate(observations):
        raw = observation.raw_text.strip()
        match = _CONTRACT.match(raw) or _BASIS.fullmatch(raw)
        match = match or (_PROJECT.match(raw) if template else None)
        if match:
            results.append((match[1], observation))
            continue
        label = _LABEL.fullmatch(raw)
        if not label or _norm(label[0]).startswith("дата") or i + 1 == len(observations):
            continue
        candidate = observations[i + 1]
        token = candidate.raw_text.strip()
        if _following(observation, candidate) and _BASIS_ID.fullmatch(token):
            results.append((token, candidate))
    return results


def _period_readings(
    observations: tuple[Observation, ...],
) -> tuple[list[tuple[Period, Observation]], bool, bool]:
    periods, dates = [], []
    operation_dates = set()
    unresolved_period = False
    ambiguous_period = False
    cells = {}
    for observation in observations:
        locator = observation.locator
        if isinstance(locator, TableCellLocator):
            for row_offset in range(observation.row_span):
                for col_offset in range(observation.column_span):
                    key = (locator.table, locator.row + row_offset, locator.cell + col_offset)
                    cells.setdefault(key, []).append(observation)
    for i, observation in enumerate(observations):
        raw = observation.raw_text.strip()
        # A second labelled field at the same address is not evidence that the
        # document total belongs to only the first one.
        if len(list(_PERIOD_FIELD.finditer(raw))) > 1:
            unresolved_period = ambiguous_period = True
            continue
        # Look at adjacent table cells even if row-major traversal visits other
        # columns before reaching the next row of the same column.
        candidates = list(observations[i + 1 : i + 2])
        locator = observation.locator
        if isinstance(locator, TableCellLocator):
            for row_offset in range(observation.row_span):
                candidates.extend(
                    cells.get(
                        (
                            locator.table,
                            locator.row + row_offset,
                            locator.cell + observation.column_span,
                        ),
                        (),
                    )
                )
            for col_offset in range(observation.column_span):
                candidates.extend(
                    cells.get(
                        (
                            locator.table,
                            locator.row + observation.row_span,
                            locator.cell + col_offset,
                        ),
                        (),
                    )
                )
        has_continuation = False
        if _PERIOD_FIELD.search(raw) or _MONTH_PERIOD.search(raw):
            for following in candidates:
                if not _period_following(observation, following):
                    continue
                next_text = following.raw_text.strip()
                additional_line = bool(
                    _additional_pipe_period(next_text)
                    or _additional_period_prefix(next_text)
                    or _duration_continuation(next_text)
                    or (
                        re.match(r"^(?:(?:и|или|а\s+также)\b|[,;+/&])", next_text, re.I)
                        and _ADDITIONAL_PERIOD.match(next_text)
                    )
                )
                if _period_continuation(next_text) or additional_line:
                    unresolved_period = True
                    ambiguous_period = True
                    has_continuation = True
                    break
        if has_continuation:
            continue
        if match := _DATE_RANGE.search(raw):
            full_tail = raw[match.end() :]
            tail = full_tail.split("|", 1)[0]
            if (
                _period_continuation(tail)
                or _ADDITIONAL_PERIOD.match(tail)
                or _additional_period_prefix(tail)
                or _duration_continuation(tail)
                or _additional_pipe_period(full_tail)
            ):
                unresolved_period = ambiguous_period = True
                continue
            low, high = (normalize_document_date(value).value for value in match.groups())
            if low and high and low <= high:
                periods.append((Period(start=low, end=high), observation))
            else:
                unresolved_period = True
        elif match := _MONTH_PERIOD.search(raw):
            first_month, first_year = _MONTH[match[1].casefold()], int(match[2])
            tail = raw[match.end() :]
            last_month, last_year = first_month, first_year
            if end_month := _MONTH_RANGE_END.match(tail):
                last_month, last_year = _MONTH[end_month[1].casefold()], int(end_month[2])
                tail = tail[end_month.end() :]
            full_tail, tail = tail, tail.split("|", 1)[0]
            if (
                _ADDITIONAL_PERIOD.match(tail)
                or _additional_period_prefix(tail)
                or _duration_continuation(tail)
                or _additional_pipe_period(full_tail)
            ):
                unresolved_period = ambiguous_period = True
                continue
            if _period_continuation(tail):
                unresolved_period = ambiguous_period = True
            elif (
                not first_year
                or not last_year
                or (first_year, first_month) > (last_year, last_month)
            ):
                unresolved_period = True
            else:
                period = Period(
                    start=f"{first_year:04}-{first_month:02}-01",
                    end=f"{last_year:04}-{last_month:02}-{monthrange(last_year, last_month)[1]:02}",
                )
                periods.append((period, observation))
        elif _PERIOD_FIELD.search(raw.translate(_OCR_LABEL_MAP)):
            unresolved_period = True
        if match := _OPERATION_DATE.fullmatch(raw):
            if value := normalize_document_date(match[1]).value:
                operation_dates.add(value)
        if match := _DATE.fullmatch(raw) or _HEADER_DATE.fullmatch(raw):
            if value := normalize_document_date(match[1]).value:
                dates.append((Period(start=value, end=value), observation))
        elif _norm(raw).rstrip(":") in {"дата", "дата документа"} and i + 1 < len(observations):
            candidate = observations[i + 1]
            if _following(observation, candidate):
                if value := normalize_document_date(candidate.raw_text.strip()).value:
                    dates.append((Period(start=value, end=value), candidate))
    # This guard does not promote a date of service to a period. It only vetoes
    # the legacy document-date fallback when an explicit operation date differs.
    date_conflict = bool(
        not periods
        and dates
        and operation_dates
        and any(day != period.start for period, _ in dates for day in operation_dates)
    )
    return (
        ([] if unresolved_period or date_conflict else periods or dates),
        ambiguous_period,
        date_conflict,
    )


def _periods(observations: tuple[Observation, ...]) -> list[tuple[Period, Observation]]:
    return _period_readings(observations)[0]


def format_rubles(amount: Decimal | None, *, xlsx: bool = False) -> str | None:
    if amount is None or not amount.is_finite() or abs(amount) >= Decimal("1e19"):
        return None
    rounded = amount.quantize(_WHOLE_RUBLES)
    if rounded != amount:
        if not xlsx:
            return None
        # OOXML producers can serialize an adjacent binary float. Limit the
        # correction to four representable steps and a millionth of a ruble.
        tolerance = min(Decimal.from_float(4 * ulp(float(amount))), Decimal("0.000001"))
        if abs(amount - rounded) > tolerance:
            return None
    return format(rounded or Decimal("0.00"), ".2f")


def _total_column(label: Observation, value: Observation) -> bool:
    left, right = label.locator, value.locator
    if isinstance(left, TableCellLocator) and isinstance(right, TableCellLocator):
        return left.table == right.table and left.row == right.row and left.cell < right.cell
    if isinstance(left, PageLocator) and isinstance(right, PageLocator):
        if left.page != right.page or left.bbox is None or right.bbox is None:
            return False
        a, b = left.bbox, right.bbox
        overlap = min(a[3], b[3]) - max(a[1], b[1])
        return a[2] <= b[0] and overlap >= min(a[3] - a[1], b[3] - b[1]) * 0.6
    return False


def _rub_column(value: Observation, observations: tuple[Observation, ...]) -> bool:
    address = value.locator
    if isinstance(address, TableCellLocator):
        return any(
            isinstance(header.locator, TableCellLocator)
            and header.locator.table == address.table
            and header.locator.cell == address.cell
            and header.locator.row == 1
            and _AMOUNT_CELL_HEADER.fullmatch(header.raw_text)
            for header in observations
        )
    if not isinstance(address, PageLocator) or address.bbox is None:
        return False
    for header in observations:
        locator = header.locator
        if (
            not isinstance(locator, PageLocator)
            or locator.page != address.page
            or locator.bbox is None
            or not _PAGE_RUB_HEADER.fullmatch(header.raw_text)
        ):
            continue
        a, b = locator.bbox, address.bbox
        if a[3] <= b[1] and min(a[2], b[2]) > max(a[0], b[0]):
            return True
    return False


def _money(
    native: NativeDocument, *, template: bool, format_: FileFormat
) -> tuple[Observation | None, list[Observation]]:
    if template:
        totals = [o for o in native.observations if o.amount_role == "total"]
        if len(totals) != 1 or native.issues:
            return None, []
        total = totals[0]
        parts = [o for o in native.observations if o.locator in total.component_locators]
        return total, parts
    candidates = []
    for obs in native.observations:
        raw = obs.raw_text.strip()
        if value_label := _FINAL_VALUE.match(raw):
            value_text = raw[value_label.end() :]
            amount, ambiguous = _text_amount(value_text)
            if ambiguous:
                return None, []
            if amount is None and isinstance(obs.locator, PageLocator):
                bare = _BARE_FINAL.fullmatch(value_text)
                page_text = [
                    item.raw_text
                    for item in native.observations
                    if isinstance(item.locator, PageLocator)
                    and item.locator.page == obs.locator.page
                ]
                if (
                    bare
                    and any(_RUB_DECLARATION.match(text) for text in page_text)
                    and not any(_OTHER_CURRENCY.search(text) for text in page_text)
                ):
                    amount = Decimal(bare[0].replace(" ", "").replace(",", "."))
            if amount is not None:
                candidates.append(Observation(obs.raw_text, obs.locator, amount, "total"))
            else:
                return None, []
        elif _FINAL_CELL.fullmatch(raw):
            found = False
            for value in native.observations:
                if not _total_column(obs, value):
                    continue
                amount, ambiguous = _text_amount(
                    value.raw_text, rub_column=_rub_column(value, native.observations)
                )
                if ambiguous:
                    return None, []
                if amount is not None:
                    candidates.append(Observation(value.raw_text, value.locator, amount, "total"))
                    found = True
            if not found:
                return None, []
        elif _FINAL_LINE.match(raw):
            return None, []
    if candidates:
        # The explicit final line takes priority over an intermediate amount.
        unique = {item.locator.model_dump_json(): item for item in candidates}
        return (next(iter(unique.values())), []) if len(unique) == 1 else (None, [])
    for obs in native.observations:
        if _TOTAL_LABEL.match(obs.raw_text):
            amount, ambiguous = _text_amount(obs.raw_text)
            if ambiguous:
                return None, []
            if amount is not None:
                candidates.append(Observation(obs.raw_text, obs.locator, amount, "total"))
    if not candidates and format_ == "docx":
        headings = {
            (o.locator.table, o.locator.cell)
            for o in native.observations
            if isinstance(o.locator, TableCellLocator)
            and o.locator.row == 1
            and _AMOUNT_CELL_HEADER.fullmatch(o.raw_text.strip())
        }
        money_tables = {table for table, _ in headings}
        populated_rows = {
            (o.locator.table, o.locator.row)
            for o in native.observations
            if isinstance(o.locator, TableCellLocator)
            and o.locator.table in money_tables
            and o.locator.row > 1
            and o.raw_text.strip()
        }
        # Without a printed total the only supported table layout is one
        # populated charge row with one unambiguous ruble cell.
        if len(populated_rows) != 1 or len(headings) != 1:
            return None, []
        candidates = [
            o
            for o in native.observations
            if isinstance(o.locator, TableCellLocator)
            and (o.locator.table, o.locator.row) in populated_rows
            and (o.locator.table, o.locator.cell) in headings
            and o.amount is not None
        ]
    if len(candidates) != 1:
        return None, []
    return candidates[0], []


def _ocr_lines_at_page_edge(observations: tuple[Observation, ...]) -> frozenset[int]:
    clipped = set()
    for index, (line, following) in enumerate(zip(observations, observations[1:]), start=1):
        first, second = line.locator, following.locator
        if (
            isinstance(first, PageLocator)
            and isinstance(second, PageLocator)
            and first.page == second.page
            and first.bbox is not None
            and second.bbox is not None
            and first.bbox[2] >= 0.995
            and abs(first.bbox[0] - second.bbox[0]) <= 0.03
            and 0 < second.bbox[1] - first.bbox[1] <= 2.5 * (first.bbox[3] - first.bbox[1])
        ):
            clipped.add(index)
    return frozenset(clipped)


def _category(
    observations: tuple[Observation, ...], text: str, *, ocr: bool = False
) -> tuple[str | None, list[Observation]]:
    from bench.e2e_v32_20261114.classification import classify_source

    # The fixture disclaimer labels the source, not the work described below it.
    # Preserve its line position so classifier spans still address the source.
    classified_text = "\n".join(
        " "
        if re.fullmatch(
            r"синтетический документ\s*[—–-]\s*не для бухгалтерского учета[.]?",
            _norm(line),
        )
        else line
        for line in text.splitlines()
    )
    source = classify_source(
        classified_text,
        clipped_lines=_ocr_lines_at_page_edge(observations) if ocr else frozenset(),
    )
    category = source["category"]
    if source["decision"] != "resolved" or category not in ARTICLES:
        return None, []
    indices = {
        index - 1
        for statement in source["statements"]
        if category in statement["positive_categories"]
        and statement["decision_effect"] == "evidence"
        for index in range(statement["line_start"], statement["line_end"] + 1)
    }
    if not indices or min(indices) < 0 or max(indices) >= len(observations):
        return None, []
    return category, [observations[i] for i in sorted(indices)]


def ground_document(
    run_id: UUID, document_id: str, path: Path, format_: FileFormat, opened_sha256: str
) -> GroundedDocument:
    """Build addressed facts. A model prediction cannot create a monetary assertion."""
    from bench.e2e_v32_20261114.document_identity import resolve_own_number

    native, method, potential = _read_observations(path, format_)
    # Match the line indices used by v3.2 to the original structural/visual location.
    observations = tuple(
        Observation(
            line.strip(),
            obs.locator,
            obs.amount,
            obs.amount_role,
            obs.cached_value,
            obs.component_locators,
            obs.column_span,
            obs.row_span,
        )
        for obs in native.observations
        for line in obs.raw_text.splitlines()
        if line.strip()
    )
    text = "\n".join(o.raw_text for o in observations)
    articles = [
        (_TITLES[_norm(o.raw_text)], o)
        for o in observations
        if isinstance(o.locator, SheetLocator)
        and o.locator.range == "A1"
        and _norm(o.raw_text) in _TITLES
    ]
    template = format_ == "xlsx" and len(articles) == 1
    category, article_evidence = (
        (articles[0][0], [articles[0][1]])
        if template
        else _category(observations, text, ocr=method == "ocr")
    )
    has_weak_ocr = len(potential) > len(observations)
    if category and has_weak_ocr:
        possible, _ = _category(potential, "\n".join(item.raw_text for item in potential), ocr=True)
        if possible != category:
            category, article_evidence = None, []

    if template:
        sheet = articles[0][1].locator.sheet
        observations = tuple(
            o
            for o in observations
            if isinstance(o.locator, SheetLocator) and o.locator.sheet == sheet
        )

    assertions = []

    def add(
        kind: EvidenceKind,
        value: str | Period,
        observation: Observation,
    ) -> None:
        assertions.append(
            ObservationAssertion(
                run_id=run_id,
                document_id=document_id,
                opened_sha256=opened_sha256,
                source_format=format_,
                kind=kind,
                raw_value=observation.raw_text,
                normalized_value=value,
                unit="RUB" if kind == "amount" else None,
                method=method,
                locator=observation.locator,
            )
        )

    contract_hits = [
        (value, o)
        for raw, o in _contracts(observations, template=template)
        if (value := normalize_contract_number(raw).value)
    ]
    period_hits, period_ambiguous, period_date_conflict = _period_readings(observations)
    stage_hits, stage_uncertain = _stages(observations)
    if has_weak_ocr:
        possible_stages, unresolved_stage = _stages(potential)
        stage_uncertain |= unresolved_stage or {stage for stage, _ in possible_stages} != {
            stage for stage, _ in stage_hits
        }
    periods = {(p.start, p.end) for p, _ in period_hits}
    if has_weak_ocr:
        possible_periods, possible_ambiguity, possible_conflict = _period_readings(potential)
        period_ambiguous |= possible_ambiguity
        period_date_conflict |= possible_conflict
        if {(p.start, p.end) for p, _ in possible_periods} != periods:
            periods.clear()
    contracts = {value for value, _ in contract_hits}
    if has_weak_ocr:
        possible_contracts = {
            value
            for raw, _ in _contracts(potential, template=False)
            if (value := normalize_contract_number(raw).value)
        }
        if possible_contracts != contracts:
            contracts.clear()
    contract = next(iter(contracts)) if len(contracts) == 1 else None
    period = period_hits[0][0] if len(periods) == 1 else None
    if contract:
        for value, o in contract_hits:
            add("contract", value, o)
    if period:
        for value, o in period_hits:
            add("period", value, o)
    for value, o in stage_hits:
        add("stage", value, o)
    if category:
        code, _ = ARTICLES[category]
        for o in article_evidence:
            add("article", code or category, o)

    total, parts = (
        (None, [])
        if native.issues
        else _money(NativeDocument(observations), template=template, format_=format_)
    )
    amount = format_rubles(total.amount, xlsx=template) if total is not None else None
    if amount is not None and total is not None:
        add("amount", amount, total)
        # These remain source observations. The component points to the document
        # total, so formula operands are never counted again.
        for part in parts:
            if (value := format_rubles(part.amount, xlsx=template)) is not None:
                add("amount", value, part)

    if template:
        identity_text = "\n".join(
            f"{o.locator.range}: {o.raw_text}"
            for o in observations
            if isinstance(o.locator, SheetLocator)
        )
    else:
        identity_text = text
    parsed = resolve_own_number(identity_text)
    identity = parsed["resolved_number"]
    identity_observation = None
    if identity:
        for candidate in parsed["candidates"]:
            line = candidate["line"] - 1
            if candidate["value"] == identity and 0 <= line < len(observations):
                identity_observation = observations[line]
                break
    if template:
        numbers = [
            (match[1], obs)
            for obs in observations
            if (match := re.fullmatch(r"Документ\s*:\s*([\w/-]+)", obs.raw_text, re.I))
        ]
        if len(numbers) == 1 and parsed["status"] in {"missing", "resolved"}:
            if identity is None or identity == numbers[0][0]:
                identity, identity_observation = numbers[0]
            else:
                identity, identity_observation = None, None
    if identity is None and parsed["status"] == "missing":
        # An adjacent visible number after a supported title may carry No.
        number_line = re.compile(r"^(?:№|No)\s*([\w/-]+)\s+от\s+" + _DAY + r"$", re.I)
        title_line = re.compile(
            r"^(?:акт|сч[её]т-акт|служебная записка|справка|универсальный передаточный документ)\b",
            re.I,
        )
        markers = [
            (match[1], o)
            for before, o in zip(observations, observations[1:])
            if title_line.match(before.raw_text) and (match := number_line.fullmatch(o.raw_text))
        ]
        if len(markers) == 1:
            identity, identity_observation = markers[0]
    identity_locator = None
    if identity and identity_observation:
        identity_locator = identity_observation.locator
        add("document_identity", identity, identity_observation)
    else:
        identity = None

    issuer = parsed["issuer_key"]
    tax_ids = set(_ISSUER_TAX_ID.findall(issuer or ""))
    issuer_tax_id = next(iter(tax_ids)) if len(tax_ids) == 1 else None
    if issuer:
        issuer = _ISSUER_REQUISITES.sub("", issuer).strip(" .,:;«»\"'()")
        for name, short in _ISSUER_FORMS.items():
            if issuer.startswith(name + " "):
                issuer = short + issuer[len(name) :]
                break
    return GroundedDocument(
        tuple(assertions),
        category,
        contract,
        period,
        amount,
        total.locator if amount and total else None,
        identity_locator,
        native.issues,
        text,
        identity,
        parsed["document_kind"],
        issuer or None,
        issuer_tax_id,
        stage_uncertain,
        period_ambiguous,
        period_date_conflict,
    )
