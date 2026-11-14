"""Translate the bounded v3.2 workflow into the saved result contract."""

import re
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

from doccheck_backend.contracts.locators import SheetLocator
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
from doccheck_backend.native_observations import Observation
from doccheck_backend.native_reader import read_native_document
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
_CONTRACT = re.compile(r"^Договор\s*№\s*(\S+?)\.?$", re.IGNORECASE)
_DATE = re.compile(r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?!\d)")
_PERIOD = re.compile(r"^Период\b", re.IGNORECASE)
_TOTAL_CANDIDATE = re.compile(
    r"\b(?:итого|всего|итоговая\s+сумма|стоимость\s+(?:услуг|работ|оказанных|выполненных))\b",
    re.IGNORECASE,
)
_CURRENT_TOTAL = re.compile(
    r"^(?:итого\s+|итоговая\s+)?стоимость\s+"
    r"(?:(?:оказанных|выполненных)(?:\s+в\s+этом\s+периоде)?\s+)?(?:услуг|работ)"
    r"\s*:\s*\d[\d \u00a0\u2009\u202f]*(?:[.,]\d{1,2})?\s*(?:руб\.?|₽)"
    r"(?:\.?\s+без\s+НДС)?\.?$",
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


def _same_contract(observation: Observation, contract: str) -> bool:
    match = _CONTRACT.fullmatch(observation.raw_text.strip())
    return match is not None and match[1] == contract


def _same_period(
    observation: Observation, dates: tuple[date, date], parse_date: Callable[[str], date | None]
) -> bool:
    if not _PERIOD.match(observation.raw_text.strip()):
        return False
    return tuple(parse_date(part) for part in _DATE.findall(observation.raw_text)) == dates


def _bind_component(
    file: InputFile,
    observations: tuple[Observation, ...],
    extraction: dict,
    category: str,
    scope: Scope,
    decision_rules,
) -> tuple[Component, list[Evidence]] | None:
    prediction = extraction["prediction"]
    allocation = extraction.get("category_evidence", {})
    if allocation.get("financial_usable") is not True:
        return None
    statements = {
        entry["text"].strip()
        for entry in allocation.get("statements", ())
        if entry.get("decision_effect") == "evidence"
        and category in entry.get("positive_categories", ())
        and entry.get("text")
    }
    amount = decision_rules.parse_amount(prediction.get("amount"))
    if amount is None or amount != amount.quantize(Decimal("0.01")):
        return None
    start, end, issue = decision_rules.document_interval(prediction)
    if issue or start is None or end is None:
        return None
    amount_slots = [item for item in observations if _TOTAL_CANDIDATE.search(item.raw_text)]
    contract_slots = [item for item in observations if _CONTRACT.fullmatch(item.raw_text.strip())]
    period_slots = [item for item in observations if _PERIOD.match(item.raw_text.strip())]
    article_slots = [
        item for item in observations if any(text in item.raw_text for text in statements)
    ]
    groups = (amount_slots, contract_slots, period_slots, article_slots)
    if (
        len(amount_slots) != 1
        or not _CURRENT_TOTAL.fullmatch(amount_slots[0].raw_text.strip())
        or amount_slots[0].amount != amount
        or not all(groups)
        or not all(_same_contract(item, scope.contract_number) for item in contract_slots)
        or not all(
            _same_period(item, (start, end), decision_rules.parse_date) for item in period_slots
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
            method="v32_prediction_bound_to_native_docx",
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
    """Process the supported XLSX case and anchor v3.2 findings to saved originals."""
    from bench.e2e_v32_20261114 import decision_rules, document_identity
    from bench.e2e_v32_20261114 import run as v32

    files = {item.id: item for item in map(InputFile.from_manifest, run.documents)}
    report = files[run.report_document_id]
    requested_scope = Scope.model_validate(run.scope) if run.scope is not None else None
    if requested_scope is not None and requested_scope.report_row_locator is not None:
        return _failure(run, "v32_scope_unsupported", "Адаптер v3.2 сверяет КФЗ целиком.")
    if report.format != "xlsx":
        return _failure(run, "v32_report_format", "Адаптер v3.2 ожидает КФЗ XLSX.")
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
        folder = Path(temp)
        report_entry = report.v32_entry(folder, "report")
        source_path = upload_folder / report.id
        if not _safe_office(source_path):
            return _failure(run, "v32_report_unreadable", "Файл КФЗ не удалось прочитать.")
        copyfile(source_path, report_entry["path"])
        extracted_report = v32.extract_report(report_entry)
        if extracted_report.get("error"):
            return _failure(run, "v32_report_unreadable", "Адаптер не смог прочитать шаблон КФЗ.")
        prediction = extracted_report["prediction"]
        inferred = Scope(
            report_document_id=report.id,
            contract_number=prediction["contract_number"],
            period_start=prediction["period_start"],
            period_end=prediction["period_end"],
            report_row_locator=None,
        )
        scope = requested_scope or inferred
        if (scope.contract_number, scope.period_start, scope.period_end) != (
            inferred.contract_number,
            inferred.period_start,
            inferred.period_end,
        ):
            return _failure(run, "v32_scope_mismatch", "Параметры задания не совпадают с КФЗ.")

        documents, extractions, hashes = {}, [], {report.digest: report.id}
        previous = {}
        observations_by_id = {}
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
                if file.format == "docx" and _safe_office(source_path):
                    entry = file.v32_entry(folder, "primary")
                    copyfile(source_path, entry["path"])
                    native = read_native_document(Path(entry["path"]), "docx")
                    if any(issue.code == "native_read_error" for issue in native.issues):
                        message = "Структуру исходного документа не удалось прочитать полностью."
                    else:
                        extracted = v32.extract_primary(entry, previous)
                        if not extracted.get("error"):
                            # The configured model schema supplies no counterparty proof.
                            extracted["prediction"].pop("counterparty", None)
                            observations_by_id[file.id] = native.observations
                            extractions.append(extracted)
                            continue
                        message = "Не удалось извлечь данные из первичного документа."
                else:
                    message = "Адаптер ожидает читаемую первичку DOCX."
                documents[file.id] = _document(
                    file, state="parse_error", message=message, technical_error=True
                )
        finally:
            v32.runtime.ART = artifact_root

        benchmark_scope = {
            **scope.model_dump(include={"contract_number", "period_start", "period_end"}),
            "stage": prediction["stage"],
        }
        # Check all non-byte-duplicate candidates before v3.2 can collapse them
        # using model totals. The identity number and both scope fields come from
        # the submitted file, and no issuer distinction is assumed for this slice.
        identity_groups = defaultdict(list)
        for entry in extractions:
            number = document_identity.validate_number_evidence(entry)["number"]
            observations = observations_by_id[entry["id"]]
            contracts = [
                match[1]
                for item in observations
                if (match := _CONTRACT.fullmatch(item.raw_text.strip()))
            ]
            periods = [
                tuple(decision_rules.parse_date(part) for part in _DATE.findall(item.raw_text))
                for item in observations
                if _PERIOD.match(item.raw_text.strip())
            ]
            if number and len(set(contracts)) == len(set(periods)) == 1:
                period = periods[0]
                if len(period) == 2 and all(period):
                    identity_groups[number, contracts[0], period].append(entry["id"])
        native_conflicts = {
            file_id for group in identity_groups.values() if len(group) > 1 for file_id in group
        }
        comparison = v32.compare(
            {"scope": benchmark_scope, "completeness": {"status": "unknown", "basis": "worker"}},
            extracted_report,
            extractions,
        )
        conflicted_sources = native_conflicts | {
            reason["id"]
            for row in comparison["rows"]
            for reason in row["reasons"]
            if reason["reason"] in _IDENTITY_CONFLICTS
        }
        by_id = {item["id"]: item for item in extractions}
        report_rows = {item["category"]: item for item in prediction["rows"]}
        evidence, rows = [], []
        for item in comparison["rows"]:
            category = item["category"]
            code, label = _ARTICLES[category]
            reported = _report_evidence(report, category, report_rows[category])
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
                    reported_value=reported.normalized_value,
                    reported_evidence_refs=[reported.id],
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
    documents[report.id] = _document(report, report=True)
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
