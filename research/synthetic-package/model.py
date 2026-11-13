"""Invented fixture data. No original files, answer keys or application imports."""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
import random

DEFAULT_SEED = 890041
MARK = "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ — НЕ ДЛЯ БУХГАЛТЕРСКОГО УЧЕТА"
MONTHS = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
LABELS = {
    "payroll": "Оплата труда",
    "insurance": "Страховые взносы",
    "production_overhead": "Общепроизводственные расходы",
    "general_admin": "Общехозяйственные расходы",
    "other": "Прочие расходы",
}


def money(cents: int) -> str:
    return format(Decimal(cents) / Decimal(100), ".2f")


def shown(amount: str) -> str:
    return format(Decimal(amount), ",.2f").replace(",", " ").replace(".", ",")


def spreadsheet_period(period_start: str) -> str:
    start = date.fromisoformat(period_start)
    return f"{MONTHS[start.month - 1]} {start.year}"


def make_package(seed: int = DEFAULT_SEED) -> dict:
    rng = random.Random(seed)
    token = f"{seed:08d}"
    year = 2031 + seed % 7
    contract = f"SYN-{token}-КФ/47"
    company = f"ООО «Синтетическая лаборатория {token}»"
    docs = []

    def add(identifier, kind, fmt, category, month, *, acquisition="native", amount=None,
            scope="included", partial=False, items=None):
        cents = rng.randrange(140001, 8700000) if amount is None else amount
        day = calendar.monthrange(year, month)[1]
        number = f"SYN-{token}-{identifier.upper()}"
        record = {
            "id": identifier, "file": f"inputs/{identifier}.{fmt}", "kind": kind,
            "format": fmt, "acquisition": acquisition, "category": category,
            "number": number, "contract": contract if scope != "other_contract" else f"SYN-{token}-КФ/93",
            "date": date(year, month, day).isoformat(),
            "period_start": date(year, month, 1).isoformat(),
            "period_end": date(year, month, day).isoformat(),
            "company": company, "counterparty": f"ООО «Синтез Поставщик {token}-{len(docs)+1:02d}»",
            "tax_id": f"SYN-INN-{token}-{len(docs)+1:02d}",
            "amount": money(cents), "items": items or [{"label": "Объем по документу", "amount": money(cents)}],
            "scope": scope, "partial": partial,
        }
        docs.append(record)
        return record

    # Five consecutive months. No tax-rate assumptions: insurance is an explicit
    # fictional accrual statement, not a legal calculation or payroll deduction.
    for month in range(6, 11):
        # Keep the seeded monthly totals when grouping amounts into two accruals.
        salary = sum(rng.randrange(4100001, 9300000) for _ in range(2))
        allowance = rng.randrange(4100001, 9300000)
        payroll_total = salary + allowance
        items = [
            {"article_code": "9101", "label": "Начисление по окладу",
             "amount": money(salary), "basis": "Учебный табель"},
            {"article_code": "9102", "label": "Доплата за проект",
             "amount": money(allowance), "basis": "Учебное распоряжение"},
        ]
        add(f"02_payroll_{month:02d}", "Расчетная ведомость заработной платы", "xlsx", "payroll", month,
            items=items, amount=payroll_total)
        contributions = sum(rng.randrange(1200001, 2600000) for _ in range(3))
        insurance = add(
            f"03_insurance_{month:02d}", "Ведомость начисленных страховых взносов",
            "xlsx", "insurance", month, amount=contributions,
            items=[{"label": "Страховые взносы", "amount": money(contributions)}],
        )
        insurance.update(
            accrual_base=money(payroll_total),
            article_code="9201",
            comment="Учебные начисления за месяц",
        )
    add("04_act", "Акт оказанных услуг", "pdf", "production_overhead", 6)
    add("05_invoice_act", "Счет-акт", "pdf", "production_overhead", 7, acquisition="scan")
    add("06_memo", "Служебная записка", "docx", "production_overhead", 8)
    add("07_transfer", "Универсальный передаточный документ", "pdf", "production_overhead", 9)
    add("08_admin_act", "Акт оказанных услуг", "pdf", "general_admin", 6)
    original = add("09_admin_act", "Акт оказанных услуг", "pdf", "general_admin", 7, acquisition="scan")
    duplicate = dict(original, id="10_admin_copy", file="inputs/10_admin_copy.pdf", duplicate_of=original["id"])
    docs.append(duplicate)
    add("11_calculation", "Справка расчет", "docx", "general_admin", 8)
    add("12_communication", "Акт оказанных услуг связи", "png", "general_admin", 9, acquisition="scan")
    add("13_transfer", "Универсальный передаточный документ", "pdf", "general_admin", 9, scope="other_contract")
    add("14_admin_act", "Акт организационных услуг", "pdf", "general_admin", 11, scope="other_period")
    add("15_admin_act", "Акт оказанных услуг", "pdf", "general_admin", 10, partial=True)
    totals = {category: Decimal(0) for category in LABELS}
    for doc in docs:
        if doc["scope"] == "included" and not doc.get("duplicate_of"):
            totals[doc["category"]] += Decimal(doc["amount"])
    delta = Decimal(money(rng.randrange(17001, 79000)))
    rows = []
    for category, label in LABELS.items():
        reported = totals[category]
        status, reason = "verified", "complete_document_set"
        if category == "insurance":
            reported += delta
            status, reason = "discrepancy", "reported_total_differs"
        elif category == "general_admin":
            # Deliberately equal to the available subtotal. Equality alone must
            # never verify the missing part of October's supporting document.
            status, reason = "unverified", "partial_document_set"
        elif category == "other":
            reported = Decimal(money(rng.randrange(720001, 1800000)))
            status, reason = "unverified", "missing_supporting_documents"
        complete = status != "unverified"
        rows.append({
            "id": category, "label": label, "reported_amount": format(reported, ".2f"),
            "expected_status": status, "expected_amount": format(totals[category], ".2f") if complete else None,
            "available_subtotal": format(totals[category], ".2f") if category != "other" else None,
            "delta": format(reported - totals[category], ".2f") if complete else None,
            "completeness": "complete" if complete else "incomplete", "reason": reason,
            "included_documents": [d["id"] for d in docs if d["category"] == category and d["scope"] == "included" and not d.get("duplicate_of")],
            "excluded_documents": [d["id"] for d in docs if d["category"] == category and (d["scope"] != "included" or d.get("duplicate_of"))],
        })
    return {"synthetic": True, "schema_version": "fixture-1", "seed": seed,
            "contract": contract, "company": company, "period_start": f"{year}-06-01", "period_end": f"{year}-10-31",
            "documents": docs, "rows": rows}


def public_document(doc: dict) -> dict:
    """Explicit allowlist: no scenario labels, duplicate links or expectations."""
    fields = ("id", "file", "kind", "format", "acquisition", "category", "number", "contract",
              "date", "period_start", "period_end", "company", "counterparty", "tax_id", "amount", "items", "partial")
    public = {key: doc[key] for key in fields}
    if doc["format"] == "xlsx":
        public["period_label"] = spreadsheet_period(doc["period_start"])
    if doc["category"] == "insurance":
        public.update({key: doc[key] for key in ("accrual_base", "article_code", "comment")})
    return public


def public_report(package: dict) -> dict:
    return {**{k: package[k] for k in ("seed", "contract", "company", "period_start", "period_end")},
            "rows": [{k: row[k] for k in ("label", "reported_amount")} for row in package["rows"]]}
