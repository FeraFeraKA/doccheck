"""Write the saved reconciliation result as an Excel report."""

import re
import textwrap
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import Cell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from doccheck_backend.contracts import CheckResult
from doccheck_backend.contracts.locators import Locator, PageLocator, ParagraphLocator, SheetLocator
from doccheck_backend.contracts.result import ResultRow

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_NON_XML_TEXT = re.compile(r"[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_STATUS_LABELS = {
    "verified": "Подтверждён",
    "discrepancy": "Расхождение",
    "unverified": "Не проверен",
}


class XlsxReportLimitError(ValueError):
    """A stored value cannot be represented without truncation in XLSX."""


def _append(sheet: Worksheet, *values: str | int | None) -> None:
    row = []
    for value in values:
        if isinstance(value, str):
            text = _NON_XML_TEXT.sub(lambda match: ascii(match[0])[1:-1], value)
            if len(text.encode("utf-16-le")) // 2 > 32_767:
                raise XlsxReportLimitError("cell text exceeds Excel limit")
            cell = Cell(sheet, value=text)
            cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            row.append(cell)
        else:
            row.append(value)
    sheet.append(row)


def _finish(sheet: Worksheet, header: int, widths: tuple[int, ...]) -> None:
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for cell in sheet[header][: len(widths)]:
        cell.fill = PatternFill(patternType="solid", fgColor="1C4649")
        cell.font = Font(bold=True, color="FFFFFF")
    last_column = get_column_letter(len(widths))
    sheet.freeze_panes = f"A{header + 1}"
    sheet.auto_filter.ref = f"A{header}:{last_column}{sheet.max_row}"


def _location(locator: Locator) -> str:
    if isinstance(locator, SheetLocator):
        return f"Лист «{locator.sheet}», {locator.range}"
    if isinstance(locator, ParagraphLocator):
        return f"Абзац {locator.paragraph}"
    if isinstance(locator, PageLocator):
        parts = [f"Страница {locator.page}"]
        if locator.line is not None:
            parts.append(f"строка {locator.line}")
        if locator.table_row is not None:
            parts.append(f"строка таблицы {locator.table_row}, столбец {locator.table_column}")
        if locator.fragment_id is not None:
            parts.append(f"фрагмент {locator.fragment_id}")
        if locator.bbox is not None:
            parts.append("координаты " + ", ".join(map(str, locator.bbox)))
        return "; ".join(parts)
    return f"Таблица {locator.table}, строка {locator.row}, ячейка {locator.cell}"


def _source_ids(row: ResultRow) -> str | None:
    references = list(row.completeness.evidence_refs)
    for component in row.calculation.components:
        references.extend(component.amount_refs)
        references.extend(component.contract_refs)
        references.extend(component.period_refs)
        references.extend(component.article_refs)
        references.extend(component.identity_refs)
    for reason in row.reasons:
        references.extend(reason.evidence_refs)
    return "\n".join(dict.fromkeys(references)) or None


def _compact_text(parts: list[str], detail_sheet: str) -> str | None:
    unique = list(dict.fromkeys(filter(None, parts)))
    text = "\n".join(unique)
    text = _NON_XML_TEXT.sub(lambda match: ascii(match[0])[1:-1], text)
    if len(text.encode("utf-16-le")) // 2 <= 32_767:
        return text or None
    return f"Подробности на листе «{detail_sheet}»."


def export_check_result(result: CheckResult) -> bytes:
    summary = result.summary
    if (
        max(
            len(result.rows) + 11,
            len(result.evidence) + 1,
            len(result.documents) + 1,
            len(summary.primary_issues) + 1,
            sum(len(row.calculation.components) for row in result.rows) + 1,
            sum(len(document.decision.evidence_refs) for document in result.documents) + 1,
        )
        > 1_048_576
    ):
        raise XlsxReportLimitError("too many worksheet rows")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Сверка"
    documents = {document.id: document for document in result.documents}
    source_keys = {evidence.id: f"S{number}" for number, evidence in enumerate(result.evidence, 1)}
    scope = result.scope
    _append(sheet, "Проверка", result.run_id)
    _append(sheet, "Тип данных", "Синтетические" if result.synthetic else "Рабочие")
    _append(sheet, "Договор", scope.contract_number)
    _append(sheet, "Период", scope.period_start, scope.period_end)
    _append(sheet, "КФЗ", documents[scope.report_document_id].name, scope.report_document_id)
    if scope.report_row_locator is not None:
        _append(sheet, "Адрес в КФЗ", _location(scope.report_row_locator))
    _append(sheet, "Подтверждено", summary.counts.verified)
    _append(sheet, "Расхождения", summary.counts.discrepancy)
    _append(sheet, "Не проверено", summary.counts.unverified)
    _append(sheet, "Заключение", summary.conclusion)
    _append(
        sheet,
        "ID строки",
        "Показатель",
        "Код",
        "Единица",
        "В КФЗ",
        "Ожидаемое значение",
        "Сумма по доступным источникам",
        "Дельта",
        "Статус",
        "Полнота",
        "Основание полноты",
        "Причины",
        "Политика",
        "Формула",
        "ID источников КФЗ",
        "ID связанных источников",
        "ID первичной ошибки",
    )
    headers = sheet.max_row
    for row in result.rows:
        _append(
            sheet,
            row.id,
            row.label,
            row.indicator_code,
            row.unit,
            row.reported_value,
            row.expected_value,
            row.observed_evidence_sum,
            row.delta,
            _STATUS_LABELS[row.status],
            row.completeness.state,
            row.completeness.reason,
            "\n".join(reason.message for reason in row.reasons) or None,
            row.calculation.policy_id,
            row.calculation.formula,
            "\n".join(row.reported_evidence_refs) or None,
            _source_ids(row),
            row.root_issue_id,
        )
    _finish(sheet, headers, (24, 42, 16, 12, 24, 24, 29, 22, 20, 17, 44, 44, 20, 40, 24, 28, 24))

    components = workbook.create_sheet("Слагаемые")
    _append(
        components,
        "ID строки",
        "Номер слагаемого",
        "Сумма",
        "Единица",
        "Основание связи",
        "ID доказательств суммы",
        "ID доказательств договора",
        "ID доказательств периода",
        "ID доказательств статьи",
        "ID доказательств идентичности",
    )
    for row in result.rows:
        for number, component in enumerate(row.calculation.components, 1):
            _append(
                components,
                row.id,
                number,
                component.amount,
                row.unit,
                component.relation_reason,
                "\n".join(component.amount_refs),
                "\n".join(component.contract_refs),
                "\n".join(component.period_refs),
                "\n".join(component.article_refs),
                "\n".join(component.identity_refs) or None,
            )
    _finish(components, 1, (24, 22, 24, 12, 58, 29, 29, 29, 29, 35))

    sources = workbook.create_sheet("Источники")
    _append(
        sources,
        "ID источника",
        "ID документа",
        "Документ",
        "Адрес",
        "Тип свидетельства",
        "Ключ источника в книге",
    )
    for evidence in result.evidence:
        _append(
            sources,
            evidence.id,
            evidence.document_id,
            documents[evidence.document_id].name,
            _location(evidence.locator),
            evidence.kind,
            source_keys[evidence.id],
        )
    _finish(sources, 1, (29, 32, 42, 61, 24, 40))

    files = workbook.create_sheet("Документы")
    _append(
        files,
        "ID документа",
        "Документ",
        "Роль",
        "Состояние",
        "Решение",
        "Основание",
        "Ошибки файла",
        "ID исходного документа",
        "Код причины решения",
        "Ключ оснований решения",
    )
    for number, document in enumerate(result.documents, 1):
        _append(
            files,
            document.id,
            document.name,
            "КФЗ" if document.role == "report" else "Первичный",
            document.parse_status,
            document.decision.state,
            document.decision.message,
            "\n".join(f"{error.id} · {error.code}: {error.message}" for error in document.errors)
            or None,
            document.duplicate_of,
            document.decision.reason_code,
            f"D{number}" if document.decision.evidence_refs else None,
        )
    _finish(files, 1, (32, 42, 16, 17, 17, 45, 45, 32, 28, 45))

    issues = workbook.create_sheet("Первичные замечания")
    _append(issues, "ID замечания", "Код", "Описание", "ID источников", "ID ошибок файлов")
    for issue in summary.primary_issues:
        _append(
            issues,
            issue.id,
            issue.code,
            issue.message,
            "\n".join(issue.evidence_refs) or None,
            "\n".join(issue.file_error_refs) or None,
        )
    _finish(issues, 1, (27, 27, 61, 32, 32))

    decision_sources = workbook.create_sheet("Основания решений")
    _append(decision_sources, "Ключ оснований решения", "Ключ источника в книге")
    for number, document in enumerate(result.documents, 1):
        for ref in document.decision.evidence_refs:
            _append(decision_sources, f"D{number}", source_keys[ref])
    _finish(decision_sources, 1, (30, 30))

    report = workbook.create_sheet("Отчёт", 0)
    report.sheet_view.showGridLines = False
    report.sheet_properties.pageSetUpPr.fitToPage = True
    report.page_setup.fitToWidth = 1
    report.page_setup.fitToHeight = 0
    report.page_setup.orientation = "landscape"
    _append(report, "ОТЧЁТ ПО ПРОВЕРКЕ")
    report.merge_cells("A1:F1")
    report["A1"].font = Font(bold=True, size=13)
    if result.synthetic:
        _append(report, "Тестовые данные")
    _append(
        report,
        "Показатель КФЗ",
        "Значение в КФЗ",
        "Ожидаемо по документам",
        "Расхождение",
        "Статус",
        "Пояснение",
    )
    header = report.max_row
    for cell in report[header]:
        cell.font = Font(bold=True)
    for row in result.rows:
        messages = [reason.message for reason in row.reasons if reason.message]
        if row.status == "unverified" and row.completeness.reason not in messages:
            messages.append(row.completeness.reason)
        if row.expected_value is None and row.observed_evidence_sum is not None:
            messages.append(f"По доступным документам: {row.observed_evidence_sum} {row.unit}")
        suffix = f" ({row.indicator_code})" if row.indicator_code else ""
        suffix += f" · {row.unit}"
        suffix = _NON_XML_TEXT.sub(lambda match: ascii(match[0])[1:-1], suffix)
        if len(suffix.encode("utf-16-le")) // 2 > 32_000:
            suffix = f" · {row.unit}"
        if len(suffix.encode("utf-16-le")) // 2 > 32_000:
            suffix = " · Единица на листе «Сверка»"
        label = _NON_XML_TEXT.sub(lambda match: ascii(match[0])[1:-1], row.label) + suffix
        if len(label.encode("utf-16-le")) // 2 > 32_767:
            available = 32_767 - len(("… " + suffix).encode("utf-16-le")) // 2
            clean_label = _NON_XML_TEXT.sub(lambda match: ascii(match[0])[1:-1], row.label)
            prefix = clean_label.encode("utf-16-le")[: max(0, available) * 2]
            label = prefix.decode("utf-16-le", errors="ignore") + "… " + suffix
        _append(
            report,
            label,
            row.reported_value,
            row.expected_value,
            row.delta,
            _STATUS_LABELS[row.status],
            _compact_text(messages, "Сверка"),
        )
    _append(report)
    _append(report, "Дополнительные проверки")
    report.cell(report.max_row, 1).font = Font(bold=True)
    for document in result.documents:
        if document.decision.state == "include" and not document.errors:
            continue
        messages = [document.decision.message, *(error.message for error in document.errors)]
        if len(document.decision.evidence_refs) <= 20:
            messages.extend(
                f"{documents[source.document_id].name} · {_location(source.locator)}"
                for ref in document.decision.evidence_refs
                if (source := next((item for item in result.evidence if item.id == ref), None))
            )
        else:
            messages.append("Источники решения приведены на листе «Основания решений».")
        state = {
            "exclude": "Исключён",
            "needs_review": "Требует проверки",
            "parse_error": "Ошибка чтения",
            "include": "Прочитан частично"
            if document.parse_status == "partial"
            else "Ошибка чтения",
        }.get(document.decision.state, document.decision.state)
        _append(
            report,
            state,
            document.name,
            None,
            None,
            None,
            _compact_text(messages, "Документы"),
        )
    for issue in summary.primary_issues:
        _append(report, "Замечание", None, None, None, None, issue.message)
    for column, width in enumerate((43, 24, 29, 22, 20, 70), 1):
        report.column_dimensions[get_column_letter(column)].width = width
    widths = (20, 11, 13, 10, 9, 33)
    for row_number in range(report.max_row, header, -1):
        values = [report.cell(row_number, column).value for column in range(1, 7)]
        lines = [
            [line for part in value.split("\n") for line in textwrap.wrap(part, width) or [""]]
            if isinstance(value, str)
            else []
            for value, width in zip(values, widths, strict=True)
        ]
        pages = max((len(cell_lines) + 23) // 24 for cell_lines in lines)
        if pages > 1:
            report.insert_rows(row_number + 1, pages - 1)
        for page in range(max(pages, 1)):
            for column, cell_lines in enumerate(lines, 1):
                portion = cell_lines[page * 24 : (page + 1) * 24]
                if not portion:
                    continue
                cell = report.cell(row_number + page, column)
                cell.value = values[column - 1] if len(cell_lines) <= 24 else "\n".join(portion)
                cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row in report.iter_rows(min_row=header + 1):
        height = max(
            (
                sum(len(textwrap.wrap(part, width)) or 1 for part in cell.value.split("\n"))
                if isinstance(cell.value, str)
                else 1
            )
            for cell, width in zip(row, widths, strict=True)
        )
        report.row_dimensions[row[0].row].height = max(18, min(360, height * 15))
    report.freeze_panes = f"A{header + 1}"
    report.print_title_rows = f"1:{header}"
    workbook.active = 0
    for detail in workbook.worksheets[1:]:
        detail.sheet_state = "hidden"

    with BytesIO() as output:
        workbook.save(output)
        return output.getvalue()
