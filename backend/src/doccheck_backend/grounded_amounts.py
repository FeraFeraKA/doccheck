"""Select monetary observations and their scope from an uploaded original."""

import re
from calendar import monthrange
from dataclasses import dataclass
from decimal import Decimal
from math import ulp
from pathlib import Path
from typing import Literal
from uuid import UUID

from doccheck_backend.contracts.locators import Locator, PageLocator, SheetLocator, TableCellLocator
from doccheck_backend.contracts.result import FileFormat, Period
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
_MONTH_YEAR = rf"({'|'.join(_MONTH)})\s+([0-9]{{4}})(?:\s*(?:года|г\.))?(?!\d)"
_MONTH_PERIOD = re.compile(rf"(?:\bпериод\s*:\s*|\bза\s+|\bв\s+){_MONTH_YEAR}\b", re.I)
_DAY = r"(?:[0-9]{2}\.[0-9]{2}\.[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
_DATE_RANGE = re.compile(
    rf"(?:^|\|\s*)период\s*:\s*(?:с\s+)?({_DAY})\s*(?:по|[–—-])\s*({_DAY})\b", re.I
)
_DATE = re.compile(rf"^дата(?:\s+документа)?\s*[:№]?\s*({_DAY})(?:\s*г\.?)?$", re.I)
_HEADER_DATE = re.compile(
    rf"^(?:акт|счет-акт|счёт-акт|упд)\b[^\n]{{0,72}}?\bот\s+({_DAY})(?:\s*г\.?)?$", re.I
)
_CONTRACT_ID = r"[\w]+(?:[/-][\w]+)*"
_CONTRACT = re.compile(
    rf"^(?:(?:по\s+|основание\s*:?\s*)?договор(?:у)?|контракт)(?=\s|[:№])"
    rf"\s*:?\s*(?:№\s*|N[eoо°º]\s+(?=[\w/-]*[0-9]))?({_CONTRACT_ID})(?=$|[\s,.;|])",
    re.I,
)
_BASIS = re.compile(r"^основание\s*:?\s*([0-9]+(?:/[0-9]+){2}-[0-9]+)$", re.I)
_PROJECT = re.compile(rf"^проект\s*:\s*({_CONTRACT_ID})(?=$|\s*\|)", re.I)
_LABEL = re.compile(r"^(?:договор|контракт|основание|дата(?:\s+документа)?)\s*:?$", re.I)
_BASIS_ID = re.compile(r"[\w]+(?:[/‑-][\w]+)+")
_FINAL_LABEL = (
    r"(?:итого(?:\s+(?:к\s+(?:оплате|уч[её]ту)|стоимость\s+(?:услуг|работ)))?"
    r"|к\s+оплате(?:\s+по\s+документу)?)"
)
_TOTAL_LABEL = re.compile(
    r"^(?:сумма(?:\s+по\s+акту)?|стоимость(?:\s+(?:оказанных\s+)?услуг"
    r"(?:\s+за\s+расчетный\s+период)?)?)\s*[:：]",
    re.I,
)
_FINAL_VALUE = re.compile(rf"^{_FINAL_LABEL}(?:\s*[:：]\s*|\s+)(?=[+−-]?[0-9])", re.I)
_FINAL_CELL = re.compile(rf"^{_FINAL_LABEL}\s*[:.：]?$", re.I)
_FINAL_LINE = re.compile(rf"^{_FINAL_LABEL}(?=[\s:：.]|$)", re.I)
_BARE_FINAL = re.compile(
    rf"{_FINAL_LABEL}\s*[:：]?\s+(-?(?:[0-9]+|[0-9]{{1,4}}(?: [0-9]{{3}})+)[,.][0-9]{{2}})",
    re.I,
)
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


def _norm(text: str) -> str:
    normalized = " ".join(text.casefold().replace("ё", "е").split())
    return normalized.removesuffix(" — синтетический документ").removesuffix(
        " - синтетический документ"
    )


def _read_observations(path: Path, format_: FileFormat) -> tuple[NativeDocument, str]:
    native = read_native_document(path, format_)
    # Use full-page OCR when images or clipped text may hide part of the document.
    # Unsupported PDF visibility is left to review instead of mixing layers.
    render = format_ == "png" or (
        format_ == "pdf"
        and (native.has_raster_content or native.issues)
        and all(issue.code in _PDF_OCR_ISSUES for issue in native.issues)
    )
    if not render:
        return native, "native"
    observations = []
    issues = []
    for page, image in enumerate(render_pages(path), 1):
        before = len(observations)
        for line in recognize_lines(image):
            if line.confidence < 50:
                if _FINAL_LINE.match(line.text) or _TOTAL_LABEL.match(line.text):
                    issues.append(
                        NativeIssue("unreadable_amount_line", page_locator(page, image, line.box))
                    )
                continue
            observations.append(Observation(line.text, page_locator(page, image, line.box)))
        if len(observations) == before:
            issues.append(NativeIssue("no_addressed_source_text", page=page))
    return NativeDocument(tuple(observations), tuple(issues)), "ocr"


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


def _periods(observations: tuple[Observation, ...]) -> list[tuple[Period, Observation]]:
    periods, dates = [], []
    for i, observation in enumerate(observations):
        raw = observation.raw_text.strip()
        if match := _DATE_RANGE.search(raw):
            low, high = (normalize_document_date(value).value for value in match.groups())
            if low and high and low <= high:
                periods.append((Period(start=low, end=high), observation))
        elif match := _MONTH_PERIOD.search(raw):
            month, year = _MONTH[match[1].casefold()], int(match[2])
            if year:
                periods.append(
                    (
                        Period(
                            start=f"{year:04}-{month:02}-01",
                            end=f"{year:04}-{month:02}-{monthrange(year, month)[1]:02}",
                        ),
                        observation,
                    )
                )
        if match := _DATE.fullmatch(raw) or _HEADER_DATE.fullmatch(raw):
            if value := normalize_document_date(match[1]).value:
                dates.append((Period(start=value, end=value), observation))
        elif _norm(raw).rstrip(":") in {"дата", "дата документа"} and i + 1 < len(observations):
            candidate = observations[i + 1]
            if _following(observation, candidate):
                if value := normalize_document_date(candidate.raw_text.strip()).value:
                    dates.append((Period(start=value, end=value), candidate))
    return periods or dates


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
    has_final_label = False
    for obs in native.observations:
        raw = obs.raw_text.strip()
        if _FINAL_VALUE.match(raw):
            has_final_label = True
            amount, ambiguous = _text_amount(raw)
            if ambiguous:
                return None, []
            if amount is None and isinstance(obs.locator, PageLocator):
                bare = _BARE_FINAL.fullmatch(raw)
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
                    amount = Decimal(bare[1].replace(" ", "").replace(",", "."))
            if amount is not None:
                candidates.append(Observation(obs.raw_text, obs.locator, amount, "total"))
        elif _FINAL_CELL.fullmatch(raw):
            has_final_label = True
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
    if has_final_label:
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
        candidates = [
            o
            for o in native.observations
            if isinstance(o.locator, TableCellLocator)
            and o.locator.row > 1
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

    native, method = _read_observations(path, format_)
    # Match the line indices used by v3.2 to the original structural/visual location.
    observations = tuple(
        Observation(
            line.strip(),
            obs.locator,
            obs.amount,
            obs.amount_role,
            obs.cached_value,
            obs.component_locators,
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

    if template:
        sheet = articles[0][1].locator.sheet
        observations = tuple(
            o
            for o in observations
            if isinstance(o.locator, SheetLocator) and o.locator.sheet == sheet
        )

    assertions = []

    def add(
        kind: Literal["amount", "article", "contract", "period", "document_identity"],
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
    period_hits = _periods(observations)
    contracts = {value for value, _ in contract_hits}
    periods = {(p.start, p.end) for p, _ in period_hits}
    contract = next(iter(contracts)) if len(contracts) == 1 else None
    period = period_hits[0][0] if len(periods) == 1 else None
    if contract:
        for value, o in contract_hits:
            add("contract", value, o)
    if period:
        for value, o in period_hits:
            add("period", value, o)
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
        parsed["issuer_key"],
    )
