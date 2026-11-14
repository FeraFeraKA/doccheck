"""Generate a synthetic raster-only Russian KФЗ and native supporting acts."""

import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from PIL import Image, ImageDraw, ImageFont

SYNTHETIC_CONTRACT = "74/963210/26-47"
SYNTHETIC_AMOUNTS = ("1350,00", "315,00", "240,00", "180,00", "2085,00")
DISTRACTOR_AMOUNTS = ("2900,00", "660,00", "520,00", "100,00", "4180,00")


def require_raster_ocr():
    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract is required for the raster KФЗ fixture")
    installed = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10, check=True
    )
    if not {"rus", "eng"} <= set(installed.stdout.splitlines()):
        pytest.skip("Tesseract rus and eng data are required for the raster KФЗ fixture")
    try:
        ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        pytest.skip("DejaVu Sans is required to generate the raster KФЗ fixture")


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
    draw.text((100, 245), "Синтетический документ. Суммы: руб.", fill="black", font=heading_font)

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


def write_kfz_with_breakdown(
    path: Path, contract: str, period: tuple[str, str], row: ScanRow
) -> Path:
    """Draw merged article headings and real nested columns on a synthetic scan."""
    widths = (230, 300, 260, 160, 176, 176, 180, 250, 160, 176, 176, 180, 340, 245, 340, 175)
    xs = [70]
    for width in widths:
        xs.append(xs[-1] + width)
    image = Image.new("RGB", (xs[-1] + 70, 1000), "white")
    draw = ImageDraw.Draw(image)
    title = ImageFont.truetype("DejaVuSans.ttf", 40)
    heading = ImageFont.truetype("DejaVuSans.ttf", 23)
    amount = ImageFont.truetype("DejaVuSans.ttf", 28)
    draw.text((70, 45), "Синтетическая карточка учёта фактических затрат", fill="black", font=title)
    draw.text((70, 114), f"Договор № {contract}", fill="black", font=title)
    draw.text((70, 179), f"Отчетный период: {_display_period(period)}", fill="black", font=title)
    draw.text((70, 238), "Суммы: руб.", fill="black", font=heading)
    ys = (280, 395, 516, 640, 760, 855)
    for y in ys:
        draw.line((xs[0], y, xs[-1], y), fill="black", width=4)

    def band(index, tracks, labels, font=heading):
        top, bottom = ys[index : index + 2]
        for col in tracks:
            draw.line((xs[col], top, xs[col], bottom), fill="black", width=4)
        for start, end, text in labels:
            draw.multiline_text(
                ((xs[start] + xs[end]) // 2, (top + bottom) // 2),
                text,
                fill="black",
                font=font,
                spacing=5,
                align="center",
                anchor="mm",
            )

    major = (0, 1, 2, 7, 12, 13, 14, 15, 16)
    band(
        0,
        major,
        (
            (0, 1, "Этап"),
            (1, 2, "Период"),
            (2, 7, "Затраты на оплату труда 0200"),
            (7, 12, "Страховые взносы 0300"),
            (12, 13, "Общепроизводственные\nрасходы 0800"),
            (13, 14, "Трудоёмкость\n(человеко-часы)"),
            (14, 15, "Общехозяйственные\nрасходы 0900"),
            (15, 16, "Итого"),
        ),
    )
    band(
        1,
        sorted((*major, 3, 6, 8, 11)),
        (
            (2, 3, "Затраты на оплату\nтруда, всего"),
            (3, 6, "Заработная плата по ведомости"),
            (6, 7, "Резерв\nотпусков"),
            (7, 8, "Страховые\nвзносы, всего"),
            (8, 11, "Заработная плата и взносы"),
            (11, 12, "Резерв\nотпусков"),
        ),
    )
    band(
        2,
        range(len(xs)),
        (
            (3, 4, "Всего"),
            (4, 5, "Основная\nзаработная\nплата"),
            (5, 6, "Дополнительная\nзаработная\nплата"),
            (8, 9, "Всего"),
            (9, 10, "Дополнительная\nзаработная\nплата"),
            (10, 11, "Основная\nзаработная\nплата"),
        ),
        font=ImageFont.truetype("DejaVuSans.ttf", 19),
    )
    payroll, insurance, overhead, general, total = row.amounts
    values = (
        f"{row.stage} этап, {row.year} г.",
        "",
        payroll,
        "997,15",
        "812,20",
        "184,95",
        "73,30",
        insurance,
        "338,80",
        "51,90",
        "286,90",
        "",
        overhead,
        "17,625",
        general,
        total,
    )
    band(3, range(len(xs)), ((i, i + 1, text) for i, text in enumerate(values)), font=amount)
    band(4, range(len(xs)), ())
    image.save(path)
    return path
