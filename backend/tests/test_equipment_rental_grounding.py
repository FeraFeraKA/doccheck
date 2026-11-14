from pathlib import Path
from uuid import uuid4

import pytest

from doccheck_backend import grounded_amounts
from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import NativeDocument, Observation


def _purpose(text, page, bbox):
    return Observation(text, PageLocator(kind="page", page=page, bbox=bbox))


@pytest.mark.parametrize(
    ("right", "following_page", "following_left", "following_top", "method", "category"),
    [
        (1.0, 1, 0.12, 0.26, "ocr", "production_overhead"),
        (0.86, 1, 0.12, 0.26, "ocr", None),
        (1.0, 2, 0.12, 0.26, "ocr", None),
        (1.0, 1, 0.26, 0.26, "ocr", None),
        (1.0, 1, 0.12, 0.52, "ocr", None),
        (1.0, 1, 0.12, 0.26, "native", None),
    ],
)
def test_clipped_rental_requires_two_addressed_ocr_lines(
    monkeypatch, right, following_page, following_left, following_top, method, category
):
    purpose = [
        _purpose(
            "Передача измерительных приборов во временное пользован",
            1,
            (0.12, 0.22, right, 0.24),
        ),
        _purpose(
            "для выполнения работ по проекту 17.",
            following_page,
            (following_left, following_top, 0.70, following_top + 0.02),
        ),
    ]
    document = NativeDocument(tuple(purpose))
    monkeypatch.setattr(grounded_amounts, "_read_observations", lambda *_: (document, method, ()))

    source = grounded_amounts.ground_document(
        uuid4(), "synthetic-act", Path("temporary_equipment.pdf"), "pdf", "a" * 64
    )
    articles = [assertion for assertion in source.assertions if assertion.kind == "article"]

    assert source.category == category
    assert [article.locator for article in articles] == (
        [line.locator for line in purpose] if category else []
    )
    assert {article.normalized_value for article in articles} == ({"0800"} if category else set())


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            "Наименование услуг: аренда специализированного стенда для выполнения работ этапа 9.",
            "production_overhead",
        ),
        ("Аренда специализированного оборудования для административной группы.", "general_admin"),
        ("Аренда специализированного оборудования.", None),
        ("Аренда оборудования для выполнения работ проекта 17.", None),
        (
            "Аренда специализированного стенда для выполнения работ этапа 9 "
            "и административного сопровождения.",
            None,
        ),
        (
            "Аренда измерительного стенда для административных и производственных работ.",
            None,
        ),
        (
            "Если согласована аренда специализированного стенда для выполнения работ этапа 9.",
            None,
        ),
        (
            "Аренда специализированного оборудования для выполнения работ проекта 17. "
            "Услуги по настоящему акту не оказывались.",
            None,
        ),
        ("Цитата: «Аренда специализированного оборудования для выполнения работ этапа 9».", None),
        (
            "Аренда измерительных приборов для выполнения работ этапа 9. "
            "Одновременно оказано административное сопровождение.",
            None,
        ),
    ],
)
def test_direct_rental_uses_an_affirmed_purpose(text, category):
    line = _purpose(text, 1, (0.12, 0.22, 0.88, 0.24))

    resolved, evidence = grounded_amounts._category((line,), text)

    assert resolved == category
    assert evidence == ([line] if category else [])
