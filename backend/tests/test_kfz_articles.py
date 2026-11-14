from decimal import Decimal
from uuid import uuid4

import numpy as np
import pytest
from bench.e2e_v32_20261114.articles import report_category
from bench.e2e_v32_20261114.classification import classify_source
from docx import Document
from openpyxl import Workbook
from PIL import Image

from doccheck_backend import scanned_report
from doccheck_backend.grounded_amounts import ground_document
from doccheck_backend.reconciliation_comparison import compare_observed_rubles


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Код статьи: 0400", "production_setup"),
        ("Пусконаладка новой производственной линии.", "production_setup"),
        ("Приобретение специальной технологической оснастки.", "special_tooling"),
        (
            "Приобретение специального оборудования для экспериментальных работ.",
            "research_equipment",
        ),
        (
            "Приобретено специальное оборудование для экспериментальных\nисследований.",
            "research_equipment",
        ),
        ("Специальные затраты на испытания партии.", "special_costs"),
        ("Код статьи: 0500\nПриобретение комплекта штампов.", "special_tooling"),
        ("Код статьи: 0600\nИзготовление специальной технологической оснастки.", None),
        ("Код статьи: 0400\nКод статьи: 0700", None),
        ("Код статьи: 0400 и 0700", None),
        ("Код статьи: 0400 или 0700", None),
        ("Код статьи: 0400 — 0700", None),
        ("Код статьи: 0400 (или 0700)", None),
        ("Код статьи: 0400; 0700", None),
        ("Код статьи: 0400/0700", None),
        ("Код статьи: 0400 (основная), 0700 (дополнительная)", None),
        ("Код статьи: 0400 (основная); 0700 (дополнительная)", None),
        ("Код статьи: 0400 (основная),\n0700 (дополнительная)", None),
        ("Коды статей: № 0400 (осн.);\n0700 (дополнительная)", None),
        ("Код статьи: 0400,\n0400,\n0400,\n0700", None),
        ("Код статьи: 0400 (основная), 700 (дополнительная)", None),
        ("Код статьи: 0400 (основная)\nДополнительная: 0700", None),
        ("Код статьи: 0400 (основная)\nКод дополнительной статьи: 0700", None),
        ("Код статьи: 0400 (основная), 0400 (повтор)", "production_setup"),
        ("Код статьи: 0600 — по другому договору.\nНазначение: расходы по проекту.", None),
        ("Код статьи: 0600; по другому контракту.", None),
        ("Код статьи: 0600\n— по другому контракту.", None),
        ("Код статьи: 0600.\nПо другому договору.", None),
        ("Код статьи: 0600. По другому договору.", None),
        ("Код статьи: 0600 (справочно)", None),
        ("Код статьи: 0600 (шаблон)", None),
        ("Код статьи: 0600 — для планового периода", None),
        ("Договор № OUR-123\nКод статьи: 0600 (по договору № ДРУГОЙ-777)", None),
        ("Договор: OUR-123\nКод статьи: 0600 (для контракта ДРУГОЙ-777)", None),
        ("Договор № OUR-123\nКод статьи: 0600 (по договору № OUR-123)", "research_equipment"),
        (
            "Код статьи: 0600\nНазначение: специальное оборудование для научных работ по договору.",
            "research_equipment",
        ),
        (
            "Код статьи: 0600 — для другого договора.\nСпециальные затраты на испытания.",
            "special_costs",
        ),
        ("Код статьи: 0400\nНазначение: затраты на оплату труда.", None),
        ("Материальные затраты на выполнение работ.", "materials"),
        ("Договор № OUR-123\nНазначение: материальные затраты по контракту № OTHER-123.", None),
        (
            "Договор № OUR-123\nНазначение: материальные затраты по контракту № OUR-123.",
            "materials",
        ),
        ("Назначение: специальные и материальные затраты.", None),
        ("Назначение: прочие прямые и специальные затраты.", None),
        ("Командировочные расходы по выполненным работам.", "travel"),
        ("Код статьи: 1100 — прочие прямые затраты.", "other_direct_costs"),
        ("Затраты по работам сторонних организаций.", "external_services"),
        ("Коммерческие (внепроизводственные) затраты.", "commercial_costs"),
        ("Начислены проценты по кредитам.", "loan_interest"),
        ("Административно-управленческие расходы.", "management_costs"),
        ("Код статьи: 0900 — административно-управленческие расходы.", None),
        ("Код статьи: 1300", None),
        ("Код статьи: 0600\nТехническое обслуживание административной сети.", None),
        ("Код статьи: 0600\nНазначение: техническое обслуживание сети бухгалтерии.", None),
        ("Код статьи: 0600 Назначение: поверка измерительных приборов.", None),
        (
            "Код статьи: 0400 — пусконаладка новой производственной линии\n"
            "Назначение: техническое обслуживание сети бухгалтерии.",
            None,
        ),
        (
            "Код статьи: 0400\nНазначение: пусконаладка новой производственной линии.",
            "production_setup",
        ),
        (
            "Техническое обслуживание административной сети и подготовка и освоение производства.",
            None,
        ),
        ("Код статьи: 1100\nСпециальные затраты на испытания.", None),
        ("Назначение: не проводилась подготовка и освоение производства.", None),
        ("Возврат средств за невыполненную подготовку и освоение производства.", None),
        ("Шаблон: специальные затраты.", None),
        ("Договор № 74/0600-47\nНазначение: расходы по проекту.", None),
    ],
)
def test_classifies_purpose_and_detects_conflicts(text, category):
    source = classify_source(text)
    assert source["category"] == category
    assert source["financial_usable"] == (category is not None)


@pytest.mark.parametrize(
    ("label", "code", "category"),
    [
        ("0600: специальное оборудование для научных работ", "", "research_equipment"),
        ("", "500", "special_tooling"),
        ("Специальные затраты", "0700", "special_costs"),
        ("Специальные затраты", "0600", None),
        ("Специальная технологическая оснастка <1>", "0600", None),
        ("Подготовка и освоение производства", "0400 / 0700", None),
        ("0400 или 0700", "", None),
        ("0400 — Подготовка и освоение производства, всего", "", "production_setup"),
        ("Материальные затраты", "", "materials"),
        ("Командировочные расходы", "1000", "travel"),
        ("Прочие прямые затраты", "1100", "other_direct_costs"),
        ("Прочие расходы", "", "other"),
        ("Прочие расходы", "1100", None),
        ("", "1200", "external_services"),
        ("Коммерческие затраты", "1400", "commercial_costs"),
        ("Проценты по кредитам", "1500", "loan_interest"),
        ("Административно-управленческие расходы", "1600", "management_costs"),
        ("Производственная себестоимость", "1300", "production_cost"),
        ("Пусковые затраты", "0401", "0401"),
        (
            "Себестоимость продукции (сумма строк 1300, 1400, 1500 <7>, 1600)",
            "1700",
            "product_cost",
        ),
    ],
)
def test_resolves_report_labels_and_numeric_codes(label, code, category):
    assert report_category(label, code) == category


def test_scanned_column_requires_a_code_consistent_with_the_label(monkeypatch):
    image = Image.new("L", (600, 150), 255)
    ink = np.zeros((150, 600), dtype=bool)
    xs, ys = [20, 210, 400, 580], [10, 100]
    for col in xs:
        ink[:, col] = True
    texts = {
        26: "Специальное оборудование для научных работ 060(",
        216: "Подготовка и освоение производства 0400 / 0700",
        406: "Итого",
    }
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda _, box, **kwargs: texts[box[0]])
    checked = []

    def numeric_read(_, box, code):
        checked.append((box[0], code))
        return code == "0600"

    monkeypatch.setattr(scanned_report, "_numeric_header_code", numeric_read)
    assert scanned_report._headers(image, ink, xs, ys) == {
        "0400": -1,
        "0600": 0,
        "0700": -1,
        "total": 2,
    }
    assert checked == [(26, "0600")]


def test_scanned_details_keep_separate_columns(monkeypatch):
    image = Image.new("L", (1000, 150), 255)
    ink = np.zeros((150, 1000), dtype=bool)
    xs, ys = [20, 210, 400, 585, 774, 970], [10, 100]
    for col in xs:
        ink[:, col] = True
    texts = {
        26: "Материальные затраты",
        216: "Прочие прямые затраты 1100",
        406: "0402 Затраты на подготовку и освоение новых видов продукции",
        591: "Себестоимость продукции (1700)",
        780: "Итого",
    }
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda _, box, **kwargs: texts[box[0]])
    assert scanned_report._headers(image, ink, xs, ys) == {
        "0100": 0,
        "1100": 1,
        "0402": 2,
        "1700": 3,
        "total": 4,
    }


@pytest.mark.parametrize(("second_read", "expected"), [("1 336,18", "1336.18"), ("1336,19", None)])
def test_ruled_amount_accepts_decimal_spacing_only_when_readings_agree(
    monkeypatch, second_read, expected
):
    readings = iter(("1 336, 18", second_read))
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda *args, **kwargs: next(readings))
    _, amount = scanned_report._read_amount(Image.new("L", (100, 100)), (0, 0, 100, 100))
    assert amount == (Decimal(expected) if expected is not None else None)


def test_xlsx_code_and_total_require_the_same_sheet(tmp_path):
    workbook = Workbook()
    unrelated = workbook.active
    unrelated.title = "Справочник"
    unrelated.append(["Код статьи", "0500"])
    act = workbook.create_sheet("Акт")
    act.append(["Договор № 74/22/26-47"])
    act.append(["Дата: 12.02.2026"])
    act.append(["Позиция", "Сумма, руб."])
    act.append(["Исполнено", Decimal("150.08")])
    act.append(["Итого", "=SUM(B4:B4)"])
    path = tmp_path / "act.xlsx"
    workbook.save(path)
    missing = ground_document(uuid4(), "doc", path, "xlsx", "a" * 64)
    assert missing.category is None
    assert missing.amount == "150.08"

    act.append(["Код статьи", 600])
    workbook.save(path)
    grounded = ground_document(uuid4(), "doc", path, "xlsx", "b" * 64)
    assert (grounded.category, grounded.amount) == ("research_equipment", "150.08")
    article = next(item for item in grounded.assertions if item.kind == "article")
    assert article.normalized_value == "0600"
    assert (article.locator.sheet, article.locator.range) == ("Акт", "B6")


@pytest.mark.parametrize("format_", ["xlsx", "docx"])
@pytest.mark.parametrize(
    ("code_value", "expected_category"),
    [
        ("0400\n0700", None),
        ("0700\n0400", None),
        ("0400 / 0700\n0600", None),
        ("0400 и 0700", None),
        ("0400 (основная), 0700 (дополнительная)", None),
        ("0400 (основная)\n0700 (дополнительная)", None),
        ("0400 — для другого договора", None),
        ("0400", "production_setup"),
        ("0400\n0400", "production_setup"),
    ],
)
def test_adjacent_article_field_requires_one_code(tmp_path, format_, code_value, expected_category):
    path = tmp_path / f"act.{format_}"
    paragraphs = ["Договор № 74/22/26-47", "Дата: 12.02.2026", "Итого: 150,08 руб."]
    if format_ == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Акт"
        for paragraph in paragraphs:
            sheet.append([paragraph])
        sheet.append(["Код статьи", code_value])
        workbook.save(path)
        expected_locator = {"kind": "sheet", "sheet": "Акт", "range": "B4"}
    else:
        document = Document()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        label, value = document.add_table(rows=1, cols=2).rows[0].cells
        label.text, value.text = "Код статьи", code_value
        document.save(path)
        expected_locator = {"kind": "table_cell", "table": 1, "row": 1, "cell": 2}

    grounded = ground_document(uuid4(), "doc", path, format_, "a" * 64)
    assert grounded.category == expected_category
    assert grounded.amount == "150.08"
    articles = [item for item in grounded.assertions if item.kind == "article"]
    if expected_category is None:
        assert not articles
    else:
        assert articles
        for article in articles:
            assert article.raw_value == article.normalized_value == "0400"
            assert article.locator.model_dump(exclude_none=True) == expected_locator


def test_unrelated_numeric_identifier_and_currency_heading_do_not_apply(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Договор № 74/22/26-47"])
    sheet.append(["Дата: 12.02.2026"])
    sheet.append(["Код статьи", "Не указан"])
    sheet.append(["Номер позиции", "Сумма, руб."])
    sheet.append([500, 30])
    sheet.append(["Услуга", "Сумма, USD"])
    sheet.append(["Итого", Decimal("150.08")])
    path = tmp_path / "act.xlsx"
    workbook.save(path)
    grounded = ground_document(uuid4(), "doc", path, "xlsx", "a" * 64)
    assert grounded.category is None
    assert grounded.amount is None


@pytest.mark.parametrize("second_code", [700, None, "—"])
def test_common_total_cannot_be_attributed_to_first_code_in_a_table(tmp_path, second_code):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Договор № 74/22/26-47"])
    sheet.append(["Дата: 12.02.2026"])
    sheet.append(["Код статьи", "Наименование", "Сумма, руб."])
    sheet.append([400, "Первая операция", Decimal("100.01")])
    sheet.append([])
    sheet.append([second_code, "Вторая операция", Decimal("200.15")])
    sheet.append(["Итого", None, "=SUM(C4:C6)"])
    path = tmp_path / "act.xlsx"
    workbook.save(path)
    grounded = ground_document(uuid4(), "doc", path, "xlsx", "a" * 64)
    assert grounded.category is None


@pytest.mark.parametrize("second_code", [None, "0400", "0700"])
def test_code_for_first_table_cannot_cover_an_unallocated_second_table(tmp_path, second_code):
    document = Document()
    for paragraph in ("Договор № DEMO-47", "Дата: 12.02.2026", "Итого: 300,00 руб."):
        document.add_paragraph(paragraph)

    def add_table(code, amount):
        heading = ["Наименование", "Сумма, руб."]
        values = ["Работы", amount]
        if code is not None:
            heading.insert(0, "Код статьи")
            values.insert(0, code)
        table = document.add_table(rows=2, cols=len(heading))
        for row, texts in zip(table.rows, (heading, values), strict=True):
            for cell, value in zip(row.cells, texts, strict=True):
                cell.text = value

    add_table("0400", "100,00")
    add_table(second_code, "200,00")
    path = tmp_path / "act.docx"
    document.save(path)
    grounded = ground_document(uuid4(), "doc", path, "docx", "a" * 64)
    assert grounded.amount == "300.00"
    assert grounded.category == ("production_setup" if second_code == "0400" else None)
    article_tables = {item.locator.table for item in grounded.assertions if item.kind == "article"}
    assert article_tables == ({1, 2} if second_code == "0400" else set())


@pytest.mark.parametrize(
    ("reported", "observed", "code", "detail"),
    [
        ("0.00", "0.00", "observed_match", "совпадает"),
        ("18.00", "17.99", "observed_difference", "0.01 ₽ больше"),
        ("17.99", "18.00", "observed_difference", "0.01 ₽ меньше"),
        (
            "100000000000000000000000000.00",
            "-0.01",
            "observed_difference",
            "100000000000000000000000000.01 ₽ больше",
        ),
    ],
)
def test_observed_comparison_is_exact(reported, observed, code, detail):
    reason = compare_observed_rubles(reported, observed, ["report", "source"])
    assert reason.code == code
    assert detail in reason.message
    assert reason.evidence_refs == ["report", "source"]
    assert compare_observed_rubles(reported, None, ["report"]) is None
