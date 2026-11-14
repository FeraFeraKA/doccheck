from decimal import Decimal
from uuid import uuid4

import numpy as np
import pytest
from bench.e2e_v32_20261114.articles import report_category
from bench.e2e_v32_20261114.classification import classify_source
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
        ("Код статьи: 0600\nТехническое обслуживание административной сети.", None),
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
        ("Подготовка и освоение производства", "0400 / 0700", None),
        ("0400 или 0700", "", None),
        ("0400 — Подготовка и освоение производства, всего", "", "production_setup"),
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
    monkeypatch.setattr(
        scanned_report, "recognize_crop", lambda _, box, **kwargs: texts[box[0]]
    )
    checked = []

    def numeric_read(_, box, code):
        checked.append((box[0], code))
        return code == "0600"

    monkeypatch.setattr(scanned_report, "_numeric_header_code", numeric_read)
    assert scanned_report._headers(image, ink, xs, ys) == {
        "0400": -1, "0600": 0, "0700": -1, "total": 2,
    }
    assert checked == [(26, "0600")]


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


@pytest.mark.parametrize(
    ("reported", "observed", "code", "detail"),
    [
        ("0.00", "0.00", "observed_match", "совпадает"),
        ("18.00", "17.99", "observed_difference", "0.01 ₽ больше"),
        ("17.99", "18.00", "observed_difference", "0.01 ₽ меньше"),
        (
            "100000000000000000000000000.00", "-0.01",
            "observed_difference", "100000000000000000000000000.01 ₽ больше",
        ),
    ],
)
def test_observed_comparison_is_exact(reported, observed, code, detail):
    reason = compare_observed_rubles(reported, observed, ["report", "source"])
    assert reason.code == code
    assert detail in reason.message
    assert reason.evidence_refs == ["report", "source"]
    assert compare_observed_rubles(reported, None, ["report"]) is None
