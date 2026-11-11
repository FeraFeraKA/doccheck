"""Generate the explicitly synthetic DocCheck evidence PDFs and page previews.

Requires reportlab, pdfplumber, Pillow and Poppler's pdftoppm. Run from any directory:
    python scripts/generate_demo_documents.py --font /path/to/Arial.ttf

The font argument is optional: common Arial/DejaVuSans paths are tried. This
generator never reads user documents. Values are UI demonstration examples,
not expected answers for an evaluation dataset or the application contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pdfplumber
from PIL import Image
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


PAGE_WIDTH, PAGE_HEIGHT = 480, 640
SAMPLES = (
    ("materials", "01", "Материалы", "123 500,00", "15.11.2026"),
    ("services", "02", "Услуги", "48 000,00", "20.11.2026"),
)


def select_font(override: str | None) -> Path:
    if override:
        candidate = Path(override)
        if not candidate.is_file():
            raise FileNotFoundError(f"Font not found: {candidate}")
        return candidate
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Provide --font with a Cyrillic-capable TrueType font")


def draw_pdf(path: Path, number: str, item: str, amount: str, date: str) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=1)
    pdf.setTitle(f"DocCheck - синтетический демо-акт {number}")
    pdf.setAuthor("DocCheck synthetic demo generator")
    pdf.setSubject("Синтетический пример интерфейса. Не первичный документ.")

    left, right = 38, PAGE_WIDTH - 38
    ink = colors.HexColor("#172B2A")
    muted = colors.HexColor("#667472")
    rule = colors.HexColor("#D8E3DF")

    pdf.setFillColor(ink)
    pdf.setFont("DemoBold", 22)
    pdf.drawString(left, PAGE_HEIGHT - 62, f"ДЕМО-АКТ № {number}")
    pdf.setFont("DemoRegular", 12)
    pdf.setFillColor(muted)
    pdf.drawString(left, PAGE_HEIGHT - 84, "Синтетический документ")

    pdf.setStrokeColor(rule)
    pdf.setLineWidth(0.7)
    pdf.line(left, PAGE_HEIGHT - 108, right, PAGE_HEIGHT - 108)
    pdf.setFillColor(ink)
    pdf.setFont("DemoRegular", 11)
    pdf.drawString(left, PAGE_HEIGHT - 134, "Договор: DEMO-001")
    pdf.drawString(left, PAGE_HEIGHT - 154, f"Дата: {date}")

    table_top = PAGE_HEIGHT - 198
    pdf.setFillColor(colors.HexColor("#F3F6F5"))
    pdf.rect(left, table_top - 34, right - left, 34, fill=1, stroke=0)
    pdf.setFillColor(ink)
    pdf.setFont("DemoBold", 11)
    pdf.drawString(left + 12, table_top - 22, "Наименование")
    pdf.drawRightString(right - 12, table_top - 22, "Сумма, ₽")
    pdf.setFont("DemoRegular", 12)
    pdf.drawString(left + 12, table_top - 64, item)
    pdf.drawRightString(right - 12, table_top - 64, amount)
    pdf.line(left, table_top - 84, right, table_top - 84)

    pdf.setFont("DemoBold", 14)
    pdf.drawString(left + 12, table_top - 119, "Итого:")
    pdf.drawRightString(right - 12, table_top - 119, amount)

    pdf.setFillColor(muted)
    pdf.setFont("DemoRegular", 10)
    pdf.drawString(left, PAGE_HEIGHT - 372, "Суммы и реквизиты созданы для демонстрации интерфейса.")
    pdf.drawString(left, PAGE_HEIGHT - 390, "Этот файл не подтверждает реальные расходы.")
    pdf.line(left, 64, right, 64)
    pdf.setFont("DemoRegular", 9)
    pdf.drawString(left, 45, "DocCheck · синтетический пример")
    pdf.drawRightString(right, 45, "Страница 1 из 1")
    pdf.showPage()
    pdf.save()


def inspect_and_render(path: Path, amount: str, renderer: str) -> dict[str, object]:
    with pdfplumber.open(path) as document:
        if len(document.pages) != 1:
            raise ValueError(f"Expected exactly one page: {path.name}")
        page = document.pages[0]
        text = page.extract_text() or ""
        if "Синтетический документ" not in text or "DEMO-001" not in text:
            raise ValueError(f"Synthetic identification missing: {path.name}")
        matches = page.search(amount, regex=False)
        if len(matches) != 2:
            raise ValueError(f"Expected item and total amount: {path.name}")
        # The lower occurrence is the total. Add a small padding for the UI box.
        total = sorted(matches, key=lambda match: match["top"])[-1]
        normalized = [
            round((total["x0"] - 7) / page.width, 6),
            round((total["top"] - 5) / page.height, 6),
            round((total["x1"] + 7) / page.width, 6),
            round((total["bottom"] + 5) / page.height, 6),
        ]
        if not all(0 <= value <= 1 for value in normalized):
            raise ValueError("Locator must remain within the source page")
        subprocess.run([
            renderer, "-png", "-singlefile", "-scale-to-x", "960", "-scale-to-y", "-1",
            str(path), str(path.with_suffix("")),
        ], check=True)
        with Image.open(path.with_suffix(".png")) as preview:
            preview_size = list(preview.size)
        return {
            "synthetic": True,
            "page": 1,
            "page_size_points": [PAGE_WIDTH, PAGE_HEIGHT],
            "preview_size_pixels": preview_size,
            "bbox": normalized,
            "text": amount,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", help="Cyrillic-capable regular TrueType font")
    parser.add_argument("--bold-font", help="Matching bold TrueType font (optional)")
    parser.add_argument("--renderer", default=shutil.which("pdftoppm"), help="Path to Poppler pdftoppm (defaults to PATH)")
    args = parser.parse_args()
    if not args.renderer:
        raise FileNotFoundError("Provide --renderer or add Poppler pdftoppm to PATH")
    regular = select_font(args.font)
    bold_candidates = (regular.with_name("arialbd.ttf"), regular.with_name("DejaVuSans-Bold.ttf"))
    bold = Path(args.bold_font) if args.bold_font else next((p for p in bold_candidates if p.is_file()), regular)
    pdfmetrics.registerFont(TTFont("DemoRegular", str(regular)))
    pdfmetrics.registerFont(TTFont("DemoBold", str(bold)))

    target = Path(__file__).resolve().parents[1] / "frontend/src/demo/assets"
    target.mkdir(parents=True, exist_ok=True)
    locators = {}
    for slug, number, item, amount, date in SAMPLES:
        destination = target / f"{slug}.pdf"
        draw_pdf(destination, number, item, amount, date)
        locators[slug] = inspect_and_render(destination, amount, args.renderer)
    (target / "locators.json").write_text(json.dumps(locators, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(locators, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
