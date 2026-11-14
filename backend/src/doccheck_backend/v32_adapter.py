"""Translate the bounded v3.2 workflow into the saved result contract."""

import re
from calendar import monthrange
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from urllib.error import URLError
from zipfile import BadZipFile, ZipFile

from doccheck_backend.contracts.locators import PageLocator, SheetLocator
from doccheck_backend.contracts.result import (
    RESULT_SCHEMA_VERSION,
    Calculation,
    CheckJob,
    CheckResult,
    Completeness,
    Component,
    Evidence,
    FileDecision,
    FileError,
    Issue,
    Period,
    Reason,
    ResultRow,
    Scope,
    SourceDocument,
    StatusCounts,
    Summary,
    Versions,
)
from doccheck_backend.local_ocr import read_scan, read_scan_amounts
from doccheck_backend.native_observations import Observation
from doccheck_backend.native_reader import read_native_document
from doccheck_backend.ocr_report import parse_scan_report, select_scan_contract
from doccheck_backend.run_worker import StoredRun

_MODEL_DIGEST = "d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04"
_VERSION = "e2e-v32-20261114"
_ARTICLES = {
    "payroll": ("0200", "Оплата труда"),
    "insurance": ("0300", "Страховые взносы"),
    "production_overhead": ("0800", "Общепроизводственные расходы"),
    "general_admin": ("0900", "Общехозяйственные расходы"),
    "other": (None, "Прочие расходы"),
}
_CONTRACT = re.compile(r"^Договор\s*(?:№|:)\s*(\S+?)\.?$", re.IGNORECASE)
_XLSX_SCOPE = re.compile(r"^Проект:\s*(\S+)\s*\|\s*(Период:\s*.+)$", re.IGNORECASE)
_MONTHS = (
    "январь январе января",
    "февраль феврале февраля",
    "март марте марта",
    "апрель апреле апреля",
    "май мае мая",
    "июнь июне июня",
    "июль июле июля",
    "август августе августа",
    "сентябрь сентябре сентября",
    "октябрь октябре октября",
    "ноябрь ноябре ноября",
    "декабрь декабре декабря",
)
_MONTH_NUMBERS = {
    name: month for month, aliases in enumerate(_MONTHS, 1) for name in aliases.split()
}
_PERIOD_MONTH = re.compile(r"^Период:\s*([а-яё]+)\s+(\d{4})(?:\s*г\.?)?\.?$", re.IGNORECASE)
_XLSX_ARTICLES = {
    "payroll": ("C8", "расчетная ведомость по оплате труда"),
    "insurance": ("B6", "расчет страховых взносов"),
}
_DATE = re.compile(r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?!\d)")
_PERIOD = re.compile(r"^Период\b", re.IGNORECASE)
_TOTAL_CANDIDATE = re.compile(
    r"\b(?:итого|всего|итоговая\s+сумма|к\s+(?:оплате|уплате)|"
    r"стоимость\s+(?:услуг|работ|оказанных|выполненных))\b",
    re.IGNORECASE,
)
_RUB_DIGITS = r"(?:[0-9]+|[0-9]{1,3}(?:[ \u00a0\u2009\u202f][0-9]{3})+)(?:[.,][0-9]{1,2})?"
_CURRENT_TOTAL = re.compile(
    r"^(?:итого\s+|итоговая\s+)?стоимость\s+"
    r"(?:(?:оказанных|выполненных)(?:\s+в\s+этом\s+периоде)?\s+)?(?:услуг|работ)"
    rf"\s*:\s*{_RUB_DIGITS}\s*(?:руб\.?|₽)"
    r"(?:\.?\s+без\s+НДС)?\.?$",
    re.IGNORECASE,
)
_PDF_SCOPE = re.compile(
    r"^Период:\s*(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})"
    r"\s*[–—]\s*(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})\.?$",
    re.IGNORECASE,
)
_PDF_MONEY = re.compile(
    rf"\s*:\s*({_RUB_DIGITS})\s*(?:руб\.?|₽)(?:\.?\s+без\s+НДС)?\.?$",
    re.IGNORECASE,
)
_MAX_EXPANDED_OFFICE_BYTES = 128 * 1024**2
_IDENTITY_CONFLICTS = {
    "conflicting_duplicate",
    "explicit_identity_context_conflict",
    "unresolved_document_identity_collision",
    "suspected_bare_tail_identity",
}


@dataclass(frozen=True)
class InputFile:
    id: str
    name: str
    digest: str
    format: str

    @classmethod
    def from_manifest(cls, document: dict[str, object]) -> "InputFile":
        file_id, name, digest, file_format = (
            document["id"],
            document["name"],
            document["sha256"],
            document["format"],
        )
        if not all(isinstance(item, str) for item in (file_id, name, digest, file_format)):
            raise ValueError("invalid saved document metadata")
        if not re.fullmatch(r"[0-9a-f]{32}", file_id):
            raise ValueError("invalid saved document ID")
        if file_format not in {"xlsx", "docx", "pdf", "png"}:
            raise ValueError("invalid saved document format")
        return cls(file_id, name, digest, file_format)

    def v32_entry(self, folder: Path, role: str) -> dict[str, str]:
        return {
            "id": self.id,
            "path": str(folder / f"{self.id}.{self.format}"),
            "sha256": self.digest,
            "format": self.format,
            "role": role,
        }


def _safe_office(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            return sum(item.file_size for item in archive.infolist()) <= _MAX_EXPANDED_OFFICE_BYTES
    except (OSError, BadZipFile, UnicodeError):
        return False


def _money(value: str | Decimal) -> str:
    amount = Decimal(value)
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("unsupported precision in v3.2 result")
    return f"{abs(amount) if not amount else amount:.2f}"


def _document(
    file: InputFile,
    *,
    report: bool = False,
    state: str = "include",
    message: str = "Документ прочитан.",
    duplicate_of: str | None = None,
    technical_error: bool = False,
    reason_code: str | None = None,
) -> SourceDocument:
    codes = {
        "include": "parsed",
        "exclude": "duplicate" if duplicate_of else "excluded",
        "needs_review": "source_needs_review",
        "parse_error": "v32_file_unavailable",
    }
    return SourceDocument(
        id=file.id,
        name=file.name,
        sha256=file.digest,
        format=file.format,
        role="report" if report else "support",
        parse_status="error" if technical_error else "parsed",
        decision=FileDecision(
            state=state, reason_code=reason_code or codes[state], message=message, evidence_refs=[]
        ),
        errors=[FileError(id=f"{file.id}-read", code="v32_file_unavailable", message=message)]
        if technical_error
        else [],
        duplicate_of=duplicate_of,
    )


def _failure(run: StoredRun, code: str, message: str) -> CheckJob:
    return CheckJob(
        run_id=str(run.id), status="failed", result=None, error=Issue(code=code, message=message)
    )


def _report_evidence(file: InputFile, category: str, entry: dict) -> Evidence:
    sheet, cell = entry["source_cells"]["reported_amount"].rsplit("!", 1)
    amount = _money(entry["reported_amount"])
    return Evidence(
        id=f"{file.id}-{category}-reported",
        document_id=file.id,
        kind="reported_value",
        raw_value=entry["reported_amount"],
        normalized_value=amount,
        unit="RUB",
        method="v32_native_xlsx",
        locator=SheetLocator(kind="sheet", sheet=sheet, range=cell),
    )


def _read_pdf_report(
    file: InputFile, observations: tuple[Observation, ...], decision_rules
) -> tuple[Scope, dict[str, Evidence]] | None:
    # Only a single declared period with source addresses is accepted here.
    # The v3.2 benchmark's fixed raster target is not a generic scope rule.
    contracts = {
        contract for item in observations if (contract := _contract(item.raw_text)) is not None
    }
    periods = {
        _period(item.raw_text, decision_rules.parse_date)
        for item in observations
        if _PDF_SCOPE.fullmatch(item.raw_text.strip())
    }
    if len(contracts) != 1 or len(periods) != 1 or (period := next(iter(periods))) is None:
        return None
    if any(
        not _PDF_SCOPE.fullmatch(item.raw_text.strip())
        for item in observations
        if _period_candidate(item.raw_text)
    ):
        return None
    scope = Scope(
        report_document_id=file.id,
        contract_number=next(iter(contracts)),
        period_start=period[0].isoformat(),
        period_end=period[1].isoformat(),
        report_row_locator=None,
    )
    evidence = {}
    for category, (_, label) in _ARTICLES.items():
        candidates = []
        for item in observations:
            text = item.raw_text.strip()
            if text.partition(":")[0].strip().casefold() != label.casefold():
                continue
            if isinstance(item.locator, PageLocator):
                amount = _PDF_MONEY.fullmatch(text[len(label) :])
                candidates.append((item, amount[1] if amount else None))
        if len(candidates) > 1 or (candidates and candidates[0][1] is None):
            return None
        if len(candidates) == 1:
            item, raw_amount = candidates[0]
            value = decision_rules.parse_amount(raw_amount)
            if value is not None:
                evidence[category] = Evidence(
                    id=f"{file.id}-{category}-reported",
                    document_id=file.id,
                    kind="reported_value",
                    raw_value=item.raw_text,
                    normalized_value=_money(value),
                    unit="RUB",
                    method="native_pdf",
                    locator=item.locator,
                )
    return (scope, evidence) if evidence else None


def _contract(text: str) -> str | None:
    match = _CONTRACT.fullmatch(text.strip()) or _XLSX_SCOPE.fullmatch(text.strip())
    return match[1] if match else None


def _period(text: str, parse_date: Callable[[str], date | None]) -> tuple[date, date] | None:
    text = text.strip()
    if match := _XLSX_SCOPE.fullmatch(text):
        text = match[2]
    if not _PERIOD.match(text):
        return None
    if month := _PERIOD_MONTH.fullmatch(text):
        number = _MONTH_NUMBERS.get(month[1].casefold())
        year = int(month[2])
        if number is not None and year > 0:
            return date(year, number, 1), date(year, number, monthrange(year, number)[1])
    dates = [parse_date(part) for part in _DATE.findall(text)]
    if len(dates) == 2 and dates[0] is not None and dates[1] is not None and dates[0] <= dates[1]:
        return dates[0], dates[1]
    return None


def _period_candidate(text: str) -> bool:
    return (
        _PERIOD.match(text.strip()) is not None or _XLSX_SCOPE.fullmatch(text.strip()) is not None
    )


def _source_groups(
    file_format: str, observations: tuple[Observation, ...], extraction: dict, category: str
) -> tuple[list[Observation], list[Observation]]:
    if file_format == "xlsx":
        amounts = [item for item in observations if item.amount_role == "total"]
        template = _XLSX_ARTICLES.get(category)
        if (
            len(amounts) != 1
            or template is None
            or not isinstance(amounts[0].locator, SheetLocator)
            or amounts[0].locator.range != template[0]
        ):
            return [], []
        sheet = amounts[0].locator.sheet
        articles = [
            item
            for item in observations
            if isinstance(item.locator, SheetLocator)
            and item.locator.sheet == sheet
            and item.locator.range == "A1"
            and " ".join(item.raw_text.casefold().replace("ё", "е").split()) == template[1]
        ]
        # Prevent a scope match from an unrelated sheet.
        if any(
            item.locator.sheet != sheet
            for item in observations
            if _period_candidate(item.raw_text) or _contract(item.raw_text) is not None
        ):
            return [], []
        return amounts, articles

    allocation = extraction.get("category_evidence", {})
    if allocation.get("financial_usable") is not True:
        return [], []
    statements = {
        entry["text"].strip()
        for entry in allocation.get("statements", ())
        if entry.get("decision_effect") == "evidence"
        and category in entry.get("positive_categories", ())
        and entry.get("text")
    }
    articles = [item for item in observations if any(text in item.raw_text for text in statements)]
    amounts = [item for item in observations if _TOTAL_CANDIDATE.search(item.raw_text)]
    if len(amounts) != 1 or not _CURRENT_TOTAL.fullmatch(amounts[0].raw_text.strip()):
        return [], []
    return amounts, articles


def _bind_component(
    file: InputFile,
    observations: tuple[Observation, ...],
    extraction: dict,
    category: str,
    scope: Scope,
    decision_rules,
) -> tuple[Component, list[Evidence]] | None:
    prediction = extraction["prediction"]
    amount = decision_rules.parse_amount(prediction.get("amount"))
    if amount is None or amount != amount.quantize(Decimal("0.01")):
        return None
    start, end, issue = decision_rules.document_interval(prediction)
    if issue or start is None or end is None:
        return None
    amount_slots, article_slots = _source_groups(file.format, observations, extraction, category)
    contract_slots = [item for item in observations if _contract(item.raw_text) is not None]
    period_slots = [item for item in observations if _period_candidate(item.raw_text)]
    located_amount = amount_slots[0].amount if len(amount_slots) == 1 else None
    if located_amount is None and file.format == "pdf" and len(amount_slots) == 1:
        cash = _PDF_MONEY.search(amount_slots[0].raw_text)
        if cash:
            located_amount = decision_rules.parse_amount(cash[1])
    groups = (amount_slots, contract_slots, period_slots, article_slots)
    if (
        len(amount_slots) != 1
        or located_amount != amount
        or not all(groups)
        or not all(_contract(item.raw_text) == scope.contract_number for item in contract_slots)
        or not all(
            _period(item.raw_text, decision_rules.parse_date) == (start, end)
            for item in period_slots
        )
    ):
        return None

    money = _money(amount)
    article = _ARTICLES[category][0] or category
    fields = (
        ("amount", money, "RUB"),
        ("contract", scope.contract_number, None),
        ("period", Period(start=start.isoformat(), end=end.isoformat()), None),
        ("article", article, None),
    )
    evidence = [
        Evidence(
            id=f"{file.id}-{kind}-{index}",
            document_id=file.id,
            kind=kind,
            raw_value=slot.raw_text,
            normalized_value=value,
            unit=unit,
            method=f"v32_prediction_bound_to_native_{file.format}",
            locator=slot.locator,
        )
        for (kind, value, unit), slots in zip(fields, groups, strict=True)
        for index, slot in enumerate(slots, 1)
    ]
    return Component(
        amount=money,
        amount_refs=[item.id for item in evidence if item.kind == "amount"],
        contract_refs=[item.id for item in evidence if item.kind == "contract"],
        period_refs=[item.id for item in evidence if item.kind == "period"],
        article_refs=[item.id for item in evidence if item.kind == "article"],
        relation_reason="Сумма, договор, период и назначение найдены в документе.",
    ), evidence


def process(run: StoredRun, upload_folder: Path) -> CheckJob:
    """Process an addressed report and anchor v3.2 findings to saved originals."""
    from bench.e2e_v32_20261114 import decision_rules, document_identity
    from bench.e2e_v32_20261114 import run as v32

    files = {item.id: item for item in map(InputFile.from_manifest, run.documents)}
    report = files[run.report_document_id]
    requested_scope = Scope.model_validate(run.scope) if run.scope is not None else None
    if requested_scope is not None and requested_scope.report_row_locator is not None:
        return _failure(run, "v32_scope_unsupported", "Адаптер v3.2 сверяет КФЗ целиком.")
    if report.format not in {"xlsx", "pdf"}:
        return _failure(run, "v32_report_format", "Адаптер v3.2 ожидает КФЗ XLSX или PDF.")
    try:
        tags = v32.runtime.api("/api/tags", timeout=10)
    except (OSError, URLError, ValueError):
        return _failure(run, "v32_model_unavailable", "Локальная Ollama недоступна.")
    digests = [
        item.get("digest") for item in tags.get("models", ()) if item.get("name") == v32.MODEL
    ]
    if digests != [_MODEL_DIGEST]:
        return _failure(run, "v32_model_unavailable", "Закреплённая модель v3.2 недоступна.")

    with TemporaryDirectory(prefix="doccheck-v32-") as temp:
        missing_scan_amounts = set()
        scan_scope_evidence = []
        folder = Path(temp)
        report_entry = report.v32_entry(folder, "report")
        source_path = upload_folder / report.id
        if report.format == "xlsx" and not _safe_office(source_path):
            return _failure(run, "v32_report_unreadable", "Файл КФЗ не удалось прочитать.")
        report_path = Path(report_entry["path"])
        copyfile(source_path, report_path)
        if report.format == "xlsx":
            extracted_report = v32.extract_report(report_entry)
            if extracted_report.get("error"):
                return _failure(run, "v32_report_unreadable", "Не удалось прочитать КФЗ.")
            prediction = extracted_report["prediction"]
            inferred = Scope(
                report_document_id=report.id,
                contract_number=prediction["contract_number"],
                period_start=prediction["period_start"],
                period_end=prediction["period_end"],
                report_row_locator=None,
            )
            report_evidence = {
                item["category"]: _report_evidence(report, item["category"], item)
                for item in prediction["rows"]
            }
        else:
            v32.verify_source(report_entry)
            native_report = read_native_document(report_path, "pdf")
            if not native_report.observations and {
                issue.code for issue in native_report.issues
            } <= {"no_native_text"}:
                scan = read_scan(report_path, "pdf")
                parsed_scan = parse_scan_report(scan.observations) if not scan.issues else None
                if parsed_scan is None:
                    return _failure(
                        run,
                        "v32_pdf_scope_unavailable",
                        "OCR не подтвердил договор, период или адреса сумм в скане КФЗ.",
                    )
                inferred = Scope(
                    report_document_id=report.id,
                    contract_number=parsed_scan.contract,
                    period_start=parsed_scan.start.isoformat(),
                    period_end=parsed_scan.end.isoformat(),
                    report_row_locator=parsed_scan.row,
                )
                report_evidence = {
                    category: Evidence(
                        id=f"{report.id}-{category}-reported",
                        document_id=report.id,
                        kind="reported_value",
                        raw_value=item.raw_text,
                        normalized_value=_money(item.amount),
                        unit="RUB",
                        method="ocr_table_grid",
                        locator=item.locator,
                    )
                    for category, item in read_scan_amounts(
                        report_path, parsed_scan.row, scan.observations
                    ).items()
                }
                scan_scope_evidence = [
                    Evidence(
                        id=f"{report.id}-ocr-cutoff",
                        document_id=report.id,
                        kind="period",
                        raw_value=parsed_scan.cutoff_source.raw_text,
                        normalized_value=Period(start=None, end=parsed_scan.end.isoformat()),
                        unit=None,
                        method="ocr",
                        locator=parsed_scan.cutoff_source.locator,
                    ),
                    Evidence(
                        id=f"{report.id}-ocr-contract",
                        document_id=report.id,
                        kind="contract",
                        raw_value=parsed_scan.contract_source.raw_text,
                        normalized_value=parsed_scan.contract,
                        unit=None,
                        method="ocr",
                        locator=parsed_scan.contract_source.locator,
                    ),
                ]
                missing_scan_amounts = set(v32.CATEGORY_CODES.values()) - report_evidence.keys()
                v32.verify_source(report_entry)
            elif native_report.issues:
                return _failure(
                    run,
                    "v32_pdf_scope_unavailable",
                    "Для PDF КФЗ нужны адресуемые реквизиты и суммы.",
                )
            else:
                parsed = _read_pdf_report(report, native_report.observations, decision_rules)
                if parsed is None:
                    return _failure(
                        run,
                        "v32_pdf_scope_ambiguous",
                        "Не удалось однозначно определить договор, период и суммы в PDF КФЗ.",
                    )
                inferred, report_evidence = parsed
        scope = inferred
        if requested_scope is not None and (
            requested_scope.contract_number,
            requested_scope.period_start,
            requested_scope.period_end,
        ) != (inferred.contract_number, inferred.period_start, inferred.period_end):
            return _failure(run, "v32_scope_mismatch", "Параметры задания не совпадают с КФЗ.")

        documents, extractions, hashes = {}, [], {report.digest: report.id}
        previous = {}
        observations_by_id = {}
        addressed_scans = {}
        artifact_root = v32.runtime.ART
        try:
            v32.runtime.ART = folder / "runtime"
            for file in files.values():
                if file.id == report.id:
                    continue
                original = hashes.setdefault(file.digest, file.id)
                if original != file.id:
                    documents[file.id] = _document(
                        file,
                        state="exclude",
                        duplicate_of=original,
                        message="Точная копия уже учтённого файла.",
                    )
                    continue
                source_path = upload_folder / file.id
                if file.format not in {"docx", "xlsx"} or _safe_office(source_path):
                    entry = file.v32_entry(folder, "primary")
                    copyfile(source_path, entry["path"])
                    native = read_native_document(Path(entry["path"]), file.format)
                    if file.format == "xlsx" and any(
                        issue.code == "formula_cache_mismatch" for issue in native.issues
                    ):
                        documents[file.id] = _document(
                            file,
                            state="needs_review",
                            reason_code="formula_cache_mismatch",
                            message="Сохранённое значение формулы не совпадает с пересчитанным.",
                        )
                        observations_by_id[file.id] = native.observations
                        continue
                    if any(
                        issue.code in {"native_read_error", "encrypted_pdf"}
                        for issue in native.issues
                    ):
                        message = "Структуру исходного документа не удалось прочитать полностью."
                    else:
                        observations_by_id[file.id] = (
                            () if file.format == "pdf" and native.issues else native.observations
                        )
                        if file.format in {"png", "pdf"} and not native.observations:
                            ocr = read_scan(Path(entry["path"]), file.format)
                            if not ocr.issues:
                                addressed_scans[file.id] = ocr.observations
                        extracted = v32.extract_primary(entry, previous)
                        if not extracted.get("error"):
                            # The configured model schema supplies no counterparty proof.
                            extracted["prediction"].pop("counterparty", None)
                            extractions.append(extracted)
                            continue
                        message = "Не удалось извлечь данные из первичного документа."
                else:
                    message = "Структуру файла Office не удалось прочитать."
                documents[file.id] = _document(
                    file, state="parse_error", message=message, technical_error=True
                )
        finally:
            v32.runtime.ART = artifact_root

        # Check all non-byte-duplicate candidates before v3.2 can collapse them
        # using model totals. The identity number and both scope fields come from
        # the submitted file, and no issuer distinction is assumed for this slice.
        identity_groups = defaultdict(list)
        for file_id, observations in observations_by_id.items():
            native_text = "\n".join(item.raw_text for item in observations)
            identity = document_identity.resolve_own_number(native_text)
            number = identity["resolved_number"] if identity["status"] == "resolved" else None
            contracts = {
                value for item in observations if (value := _contract(item.raw_text)) is not None
            }
            periods = {
                _period(item.raw_text, decision_rules.parse_date)
                for item in observations
                if _period_candidate(item.raw_text)
            }
            if number and len(contracts) == len(periods) == 1 and None not in periods:
                identity_groups[number, next(iter(contracts)), next(iter(periods))].append(file_id)
        native_conflicts = {
            file_id for group in identity_groups.values() if len(group) > 1 for file_id in group
        }
        comparison = decision_rules.reconcile(
            extractions,
            [
                {"category": category, "reported_amount": source.normalized_value}
                for category, source in report_evidence.items()
            ]
            + [
                {"category": category, "reported_amount": None}
                for category in sorted(missing_scan_amounts)
            ],
            scope.contract_number,
            scope.period_start,
            scope.period_end,
            completeness={"status": "unknown", "basis": "worker"},
        )
        conflicted_sources = native_conflicts | {
            reason["id"]
            for row in comparison["rows"]
            for reason in row["reasons"]
            if reason["reason"] in _IDENTITY_CONFLICTS
        }
        by_id = {item["id"]: item for item in extractions}
        evidence, rows = list(scan_scope_evidence), []
        for item in comparison["rows"]:
            category = item["category"]
            code, label = _ARTICLES[category]
            reported = report_evidence.get(category)
            if reported is not None:
                evidence.append(reported)
            components = []
            for file_id in item["source_ids"]:
                if file_id in conflicted_sources:
                    continue
                file = files[file_id]
                bound = _bind_component(
                    file,
                    observations_by_id[file_id],
                    by_id[file_id],
                    category,
                    scope,
                    decision_rules,
                )
                if bound is None:
                    continue
                component, sources = bound
                components.append(component)
                evidence.extend(sources)
                documents[file_id] = _document(file)
            calculation = Calculation(
                policy_id="v32-source-backed-sum",
                operation="sum",
                formula="Сумма фактически привязанных документов.",
                components=components,
            )
            completeness = Completeness(
                state="unknown",
                basis="none",
                reason="Полнота загруженного комплекта не установлена.",
                evidence_refs=[],
            )
            observed, _ = calculation.admitted_sum(unit="RUB", completeness=completeness)
            reasons = [
                Reason(code="completeness_unknown", message=completeness.reason, evidence_refs=[])
            ]
            if reported is None:
                reasons.append(
                    Reason(
                        code="ocr_report_amount_unconfirmed",
                        message="OCR не подтвердил сумму этой статьи в выбранной строке КФЗ.",
                        evidence_refs=[],
                    )
                )
            relevant_conflicts = any(
                decision_rules.normalize_category(by_id[file_id]["prediction"].get("category"))
                in (None, category)
                for file_id in conflicted_sources
                if file_id in by_id
            )
            if relevant_conflicts:
                reasons.append(
                    Reason(
                        code="source_identity_conflict",
                        message="Документы с конфликтом идентичности требуют проверки.",
                        evidence_refs=[],
                    )
                )
            if not components or len(components) != len(item["source_ids"]):
                reasons.append(
                    Reason(
                        code="source_not_bound",
                        message="Для части документов не подтверждены адреса доказательств.",
                        evidence_refs=[],
                    )
                )
            rows.append(
                ResultRow(
                    id=category,
                    label=label,
                    indicator_code=code,
                    unit="RUB",
                    reported_value=reported.normalized_value if reported else None,
                    reported_evidence_refs=[reported.id] if reported else [],
                    expected_value=None,
                    observed_evidence_sum=observed,
                    delta=None,
                    status="unverified",
                    completeness=completeness,
                    calculation=calculation,
                    reasons=reasons,
                    root_issue_id=None,
                    derived_mismatch=False,
                )
            )

    excluded = {item["id"]: item["reason"] for item in comparison["excluded_documents"]}
    for file_id, file in files.items():
        if file_id == report.id or file_id in documents:
            continue
        exclusion = excluded.get(file_id)
        if file_id in conflicted_sources:
            documents[file_id] = _document(
                file,
                state="needs_review",
                reason_code="source_identity_conflict",
                message="Среди документов есть совпадающие реквизиты. Требуется проверка.",
            )
        elif exclusion == "different_contract":
            documents[file_id] = _document(
                file,
                state="needs_review",
                reason_code=exclusion,
                message="По данным v3.2 указан другой договор.",
            )
        elif exclusion == "outside_period":
            documents[file_id] = _document(
                file,
                state="needs_review",
                reason_code=exclusion,
                message="По данным v3.2 документ вне периода сверки.",
            )
        else:
            documents[file_id] = _document(
                file, state="needs_review", message="Доказательства требуют ручной проверки."
            )
    # An OCR address alone cannot admit a model-predicted amount. It does let a
    # reviewer open the actual contract text rather than an ungrounded quotation.
    for file_id, source_items in addressed_scans.items():
        file = files[file_id]
        document = documents[file_id]
        if document.decision.state != "needs_review":
            continue
        contract = select_scan_contract(source_items)
        if contract is None or contract[0] != scope.contract_number:
            continue
        _, item = contract
        source = Evidence(
            id=f"{file.id}-ocr-contract",
            document_id=file.id,
            kind="contract",
            raw_value=item.raw_text,
            normalized_value=scope.contract_number,
            unit=None,
            method="ocr",
            locator=item.locator,
        )
        evidence.append(source)
        document.decision.evidence_refs.append(source.id)
    documents[report.id] = _document(report, report=True)
    documents[report.id].decision.evidence_refs.extend(item.id for item in scan_scope_evidence)
    result = CheckResult(
        schema_version=RESULT_SCHEMA_VERSION,
        run_id=str(run.id),
        synthetic=False,
        scope=scope,
        versions=Versions(
            code_revision=_VERSION,
            rules_version=_VERSION,
            ml_module_version=_VERSION,
            ml_policy_version=None,
            model_revision=_MODEL_DIGEST,
        ),
        documents=[documents[file_id] for file_id in files],
        evidence=evidence,
        rows=rows,
        summary=Summary(
            counts=StatusCounts(verified=0, discrepancy=0, unverified=len(rows)),
            primary_issues=[],
            conclusion="Полнота комплекта не установлена. Проверьте доступные подтверждения.",
        ),
    )
    status = (
        "completed_with_issues" if any(file.errors for file in result.documents) else "completed"
    )
    return CheckJob(run_id=str(run.id), status=status, result=result, error=None)
