"""Generate a synthetic raster-only Russian KФЗ and native supporting acts."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from docx import Document
from PIL import Image, ImageDraw, ImageFont

SYNTHETIC_CONTRACT = "74/963210/26-47"
SYNTHETIC_AMOUNTS = ("1350,00", "315,00", "240,00", "180,00", "2085,00")
DISTRACTOR_AMOUNTS = ("2900,00", "660,00", "520,00", "100,00", "4180,00")


@dataclass(frozen=True)
class ScanRow:
    stage: int
    year: int
    amounts: tuple[str, str, str, str, str]
    period: tuple[str, str] | None = None


def _display_date(value: str) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y")


def _display_period(period: tuple[str, str]) -> str:
    return " — ".join(map(_display_date, period))


def _scan_page(
    rows: tuple[ScanRow, ...], contract: str, period: tuple[str, str] | str | None
) -> Image.Image:
    image = Image.new("RGB", (2200, 1050), "white")
    title_font = ImageFont.truetype("DejaVuSans.ttf", 48)
    heading_font = ImageFont.truetype("DejaVuSans.ttf", 34)
    table_font = ImageFont.truetype("DejaVuSans.ttf", 30)
    draw = ImageDraw.Draw(image)
    draw.text((100, 35), "Карточка учёта фактических затрат", fill="black", font=title_font)
    draw.text((100, 112), f"Договор № {contract}", fill="black", font=heading_font)
    if isinstance(period, str):
        draw.text((100, 176), period, fill="black", font=heading_font)
    elif period is not None:
        draw.text(
            (100, 176),
            f"Отчетный период: {_display_period(period)}",
            fill="black",
            font=heading_font,
        )
    draw.text((100, 245), "Синтетический документ", fill="black", font=heading_font)

    columns = (100, 370, 815, 1070, 1315, 1585, 1855, 2100)
    labels = (
        "Этап",
        "Период",
        "Оплата труда\n0200",
        "Страховые\nвзносы\n0300",
        "Общепроизводственные\nрасходы\n0800",
        "Общехозяйственные\nрасходы\n0900",
        "Итого",
    )
    top = 340
    first = 506
    row_height = 140
    bottom = first + len(rows) * row_height
    bounds = (top, first, *(first + i * row_height for i in range(1, len(rows) + 1)), bottom + 45)
    for x in columns:
        draw.line((x, top, x, bottom + 45), fill="black", width=4)
    for y in bounds:
        draw.line((columns[0], y, columns[-1], y), fill="black", width=4)

    def cells(values: tuple[str, ...], y: int, *, header: bool) -> None:
        for index, value in enumerate(values):
            left = columns[index] + 14
            size = 20 if header and index in {4, 5} else 28 if header else 30
            font = ImageFont.truetype("DejaVuSans.ttf", size) if header else table_font
            draw.multiline_text((left, y), value, fill="black", font=font, spacing=8)

    cells(labels, top + 27, header=True)
    for index, row in enumerate(rows):
        dates = _display_period(row.period) if row.period is not None else ""
        cells(
            (f"{row.stage} этап, {row.year} г.", dates, *row.amounts),
            first + index * row_height + 51,
            header=False,
        )
    return image


def write_scanned_kfz(
    path: Path,
    pages: tuple[tuple[ScanRow, ...], ...],
    *,
    contract: str = SYNTHETIC_CONTRACT,
    period: tuple[str, str] | str | None = None,
    cover: bool = False,
) -> Path:
    """Every page is an embedded image. A cover carries no selection hints."""
    if not 1 <= len(pages) <= 4 or any(not 1 <= len(rows) <= 3 for rows in pages):
        raise ValueError("Expected one to four pages with one to three rows each")
    images = [_scan_page(rows, contract, period) for rows in pages]
    if cover:
        blank = Image.new("RGB", images[0].size, "white")
        cover_font = ImageFont.truetype("DejaVuSans.ttf", 52)
        ImageDraw.Draw(blank).text((100, 100), "Титульный лист", fill="black", font=cover_font)
        images.insert(0, blank)
    if path.suffix == ".pdf":
        images[0].save(path, save_all=True, append_images=images[1:], resolution=144, quality=94)
    elif path.suffix == ".png" and len(images) == 1:
        images[0].save(path)
    else:
        raise ValueError("Expected a PDF or a single-page PNG")
    return path


def write_support(
    path: Path,
    period: tuple[str, str],
    *,
    contract: str = SYNTHETIC_CONTRACT,
    number: str = "SYN-963210-1",
) -> Path:
    """A DOCX with its own number, contract, period, and one addressed amount."""
    document = Document()
    document.add_paragraph(f"Акт № {number}")
    document.add_paragraph(f"Договор № {contract}")
    document.add_paragraph(f"Период: {_display_period(period)}")
    document.add_paragraph("Общехозяйственные расходы")
    document.add_paragraph("Итого: 180,00 руб.")
    document.save(path)
    return path
