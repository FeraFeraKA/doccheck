"""Expense articles and report rows shared by the v3.2 readers."""

import re

ADDITIONAL_ARTICLES = {
    "materials": ("0100", "Материальные затраты"),
    "production_setup": ("0400", "Затраты на подготовку и освоение производства"),
    "special_tooling": ("0500", "Затраты на специальную технологическую оснастку"),
    "research_equipment": ("0600", "Затраты на специальное оборудование для научных работ"),
    "special_costs": ("0700", "Специальные затраты"),
    "travel": ("1000", "Затраты на командировки"),
    "other_direct_costs": ("1100", "Прочие прямые затраты"),
    "external_services": (
        "1200", "Затраты по работам (услугам), выполняемым (оказываемым) сторонними организациями"
    ),
    "commercial_costs": ("1400", "Коммерческие (внепроизводственные) затраты"),
    "loan_interest": ("1500", "Проценты по кредитам"),
    "management_costs": ("1600", "Административно-управленческие расходы"),
}
EXPENSE_ARTICLES = {
    "payroll": ("0200", "Затраты на оплату труда"),
    "insurance": ("0300", "Страховые взносы"),
    "production_overhead": ("0800", "Общепроизводственные затраты"),
    "general_admin": ("0900", "Общехозяйственные затраты"),
    "other": (None, "Прочие расходы"),
    **ADDITIONAL_ARTICLES,
}
ARTICLE_CODES = {code: category for category, (code, _) in EXPENSE_ARTICLES.items() if code}
LEGACY_CODES = {"0200", "0300", "0800", "0900"}

_DETAIL_LABELS = {
    "0101": "Приобретение сырья, материалов и вспомогательных материалов",
    "0102": "Приобретение полуфабрикатов",
    "0103": "Возвратные отходы",
    "0104": "Приобретение комплектующих изделий",
    "0105": "Оплата работ и услуг сторонних организаций производственного характера",
    "0106": "Транспортно-заготовительные затраты",
    "0107": "Топливо на технологические цели",
    "0108": "Энергия на технологические цели",
    "0109": "Тара и упаковка",
    "0110": "Затраты на изделия собственного производства",
    "0201": "Основная заработная плата",
    "0202": "Дополнительная заработная плата",
    "0401": "Пусковые затраты",
    "0402": "Затраты на подготовку и освоение новых видов продукции",
}
REPORT_ROWS = {
    **EXPENSE_ARTICLES,
    **{code: (code, label) for code, label in _DETAIL_LABELS.items()},
    "production_cost": ("1300", "Производственная себестоимость"),
    "product_cost": ("1700", "Себестоимость продукции"),
    "total": (None, "Итого"),
}
REPORT_CODES = {code: category for category, (code, _) in REPORT_ROWS.items() if code}
_LABELS = {
    **{label.casefold(): category for category, (_, label) in REPORT_ROWS.items()},
    "оплата труда": "payroll",
    "страховые взносы на обязательное социальное страхование": "insurance",
    "общепроизводственные расходы": "production_overhead",
    "общехозяйственные расходы": "general_admin",
    "материальные расходы": "materials",
    "подготовка и освоение производства": "production_setup",
    "специальная технологическая оснастка": "special_tooling",
    "специальное оборудование для научных работ": "research_equipment",
    "затраты на специальное оборудование для научных (экспериментальных) работ": "research_equipment",
    "специальное оборудование для научных (экспериментальных) работ": "research_equipment",
    "затраты на специальное оборудование для экспериментальных работ": "research_equipment",
    "специальное оборудование для экспериментальных работ": "research_equipment",
    "специальные расходы": "special_costs",
    "командировочные расходы": "travel",
    "расходы на командировки": "travel",
    "прочие прямые расходы": "other_direct_costs",
    "затраты по работам сторонних организаций": "external_services",
    "работы и услуги сторонних организаций": "external_services",
    "коммерческие затраты": "commercial_costs",
    "коммерческие расходы": "commercial_costs",
    "внепроизводственные затраты": "commercial_costs",
    "административно-управленческие затраты": "management_costs",
    "всего по отчету": "total",
}
_LEADING_CODE = re.compile(r"^([0-9]{4})(?=$|[\s.:–—-])[\s.:–—-]*")
_TRAILING_CODE = re.compile(r"\s+(?:(?:\((?:статья калькуляции\s+)?([0-9]{4})\))|([0-9]{4}))$")
_TOTAL_SUFFIX = re.compile(r"[\s,:–—-]+(?:всего|в том числе)[.:]*$")
_COST_FORMULA = re.compile(
    r"^(производственная себестоимость|себестоимость продукции)"
    r"\s+\(сумма строк\s+[0-9, –—-]+\)$"
)
_FOOTNOTE = re.compile(r"\s*<[0-9]{1,2}>")
ARTICLE_CODE_TOKEN = re.compile(r"\b[0-9]{4}\b")


def report_category(label: str, code_cell: str = "") -> str | None:
    """Resolve a KФЗ label or explicit code, rejecting conflicting claims."""
    name = " ".join(_FOOTNOTE.sub("", label.casefold().replace("ё", "е")).split()).strip(" .:")
    codes = set()
    if re.fullmatch(r"[0-9]{3,4}", code_cell):
        codes.add(code_cell.zfill(4))
    if leading := _LEADING_CODE.match(name):
        codes.add(leading[1])
        name = name[leading.end():]
    if trailing := _TRAILING_CODE.search(name):
        trailing_code = trailing[1] or trailing[2]
        bare_label = name[:trailing.start()]
        if trailing[1] or _LABELS.get(_TOTAL_SUFFIX.sub("", bare_label).strip()):
            codes.add(trailing_code)
            name = bare_label
    if formula := _COST_FORMULA.fullmatch(name):
        name = formula[1]
    if codes:
        codes.update(ARTICLE_CODE_TOKEN.findall(name))
    elif ARTICLE_CODE_TOKEN.search(name):
        return None
    if code_cell and not re.fullmatch(r"[0-9]{3,4}", code_cell):
        return None
    category = _LABELS.get(_TOTAL_SUFFIX.sub("", name).strip())
    if not codes:
        return category
    if len(codes) != 1:
        return None
    by_code = REPORT_CODES.get(next(iter(codes)))
    return by_code if category is None or category == by_code else None
