"""Expense articles shared by the report readers and the source classifier."""

import re

ADDITIONAL_ARTICLES = {
    "production_setup": ("0400", "Затраты на подготовку и освоение производства"),
    "special_tooling": ("0500", "Затраты на специальную технологическую оснастку"),
    "research_equipment": ("0600", "Затраты на специальное оборудование для научных работ"),
    "special_costs": ("0700", "Специальные затраты"),
}
ARTICLE_CODES = {
    "0200": "payroll",
    "0300": "insurance",
    **{code: category for category, (code, _) in ADDITIONAL_ARTICLES.items()},
    "0800": "production_overhead",
    "0900": "general_admin",
}
LEGACY_CODES = {"0200", "0300", "0800", "0900"}
_LABELS = {
    "оплата труда": "payroll",
    "затраты на оплату труда": "payroll",
    "страховые взносы": "insurance",
    "страховые взносы на обязательное социальное страхование": "insurance",
    "общепроизводственные расходы": "production_overhead",
    "общепроизводственные затраты": "production_overhead",
    "общехозяйственные расходы": "general_admin",
    "общехозяйственные затраты": "general_admin",
    "прочие расходы": "other",
    "итого": "total",
    **{label.casefold(): category for category, (_, label) in ADDITIONAL_ARTICLES.items()},
    "подготовка и освоение производства": "production_setup",
    "специальная технологическая оснастка": "special_tooling",
    "специальное оборудование для научных работ": "research_equipment",
    "затраты на специальное оборудование для научных (экспериментальных) работ": "research_equipment",
    "специальное оборудование для научных (экспериментальных) работ": "research_equipment",
    "затраты на специальное оборудование для экспериментальных работ": "research_equipment",
    "специальное оборудование для экспериментальных работ": "research_equipment",
    "специальные расходы": "special_costs",
}
_LEADING_CODE = re.compile(r"^([0-9]{4})(?=$|[\s.:–—-])[\s.:–—-]*")
_TRAILING_CODE = re.compile(r"\s*\((?:статья калькуляции\s+)?([0-9]{4})\)$")
_TOTAL_SUFFIX = re.compile(r"[\s,:–—-]+(?:всего|в том числе)[.:]*$")
_CODE_TOKEN = re.compile(r"(?<![0-9])[0-9]{4}(?![0-9])")


def report_category(label: str, code_cell: str = "") -> str | None:
    """Resolve a KФЗ label or explicit code, rejecting conflicting claims."""
    name = " ".join(label.casefold().replace("ё", "е").split()).strip(" .:")
    codes = set()
    if re.fullmatch(r"[0-9]{3,4}", code_cell):
        codes.add(code_cell.zfill(4))
    if leading := _LEADING_CODE.match(name):
        codes.add(leading[1])
        name = name[leading.end():]
    if trailing := _TRAILING_CODE.search(name):
        codes.add(trailing[1])
        name = name[:trailing.start()]
    if codes:
        codes.update(_CODE_TOKEN.findall(name))
    elif _CODE_TOKEN.search(name):
        return None
    if not re.fullmatch(r"[0-9]{3,4}", code_cell) and _CODE_TOKEN.search(code_cell):
        return None
    category = _LABELS.get(_TOTAL_SUFFIX.sub("", name).strip())
    if not codes:
        return category
    if len(codes) != 1:
        return None
    by_code = ARTICLE_CODES.get(next(iter(codes)))
    return by_code if category is None or category == by_code else None
