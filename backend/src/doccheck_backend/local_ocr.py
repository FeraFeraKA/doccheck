"""Bridge an explicitly configured offline OCR provider to original-page addresses."""

import json
import math
import os
import re
import subprocess
from collections import Counter
from contextlib import closing
from dataclasses import replace
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation

_MAX_PAGES = 25
_MAX_RENDER_PIXELS = 12_000_000


def read_scan(path: Path, file_format: str) -> NativeDocument:
    """Call a configured local provider; reject observations without original-page boxes."""
    setting = os.environ.get("DOCCHECK_OCR_PROVIDER", "")
    if not setting:
        return NativeDocument(issues=(NativeIssue("ocr_not_configured"),))
    module, separator, name = setting.partition(":")
    if (
        not separator
        or not name.isidentifier()
        or not all(part.isidentifier() for part in module.split("."))
    ):
        return NativeDocument(issues=(NativeIssue("ocr_configuration_error"),))
    try:
        provider = getattr(import_module(module), name)
        document = provider(path, file_format)
        if not isinstance(document, NativeDocument):
            raise TypeError("OCR provider must return a NativeDocument")
        for observation in document.observations:
            locator = observation.locator
            if not isinstance(locator, PageLocator) or locator.bbox is None:
                raise ValueError("missing original-page bounding box")
            if file_format == "png" and locator.page != 1:
                raise ValueError("PNG must have one page")
            PageLocator.model_validate(locator.model_dump())
            if not observation.raw_text.strip():
                raise ValueError("empty OCR observation")
        return document
    except Exception:
        # A third-party local reader may fail with backend-specific exceptions.
        # Its exception text can contain document text and local paths.
        return NativeDocument(issues=(NativeIssue("ocr_read_error"),))


def _model_path(setting: str) -> str:
    value = os.environ.get(setting)
    if not value:
        raise ValueError(f"{setting} must point to prepared local OCR weights")
    path = Path(value)
    if not (
        path.is_dir()
        and (path / "inference.yml").is_file()
        and (path / "inference.pdiparams").is_file()
        and ((path / "inference.json").is_file() or (path / "inference.pdmodel").is_file())
    ):
        raise ValueError(f"{setting} does not point to a local Paddle inference model")
    return str(path.resolve())


@lru_cache(maxsize=1)
def _paddle():
    detection = _model_path("DOCCHECK_PADDLE_DET_DIR")
    recognition = _model_path("DOCCHECK_PADDLE_REC_DIR")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_dir=detection,
        text_recognition_model_dir=recognition,
        lang="ru",
        ocr_version="PP-OCRv5",
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_side_len=3600,
        text_det_limit_type="max",
        text_recognition_batch_size=1,
    )


def _ocr_frame(image, page: int, engine) -> NativeDocument:
    import numpy as np

    width, height = image.size
    frames = list(engine.predict(np.ascontiguousarray(np.asarray(image)[:, :, ::-1])))
    if len(frames) != 1:
        return NativeDocument(issues=(NativeIssue("ocr_frame_unavailable", page=page),))
    frame = frames[0]
    observations, issues = [], []
    for index, (value, box, score) in enumerate(
        zip(frame["rec_texts"], frame["rec_boxes"], frame["rec_scores"], strict=True), 1
    ):
        left, top, right, bottom = map(float, box)
        if not value.strip():
            continue
        if (
            not all(math.isfinite(v) for v in (left, top, right, bottom, score))
            or not 0 <= left < right <= width
            or not 0 <= top < bottom <= height
            or not 0 <= score <= 1
        ):
            issues.append(NativeIssue("ocr_invalid_observation", page=page))
            continue
        observations.append(
            Observation(
                value,
                PageLocator(
                    kind="page",
                    page=page,
                    bbox=(left / width, top / height, right / width, bottom / height),
                    fragment_id=f"ocr-line-{index}",
                ),
                confidence=float(score),
            )
        )
    if not observations:
        issues.append(NativeIssue("ocr_no_text", page=page))
    return NativeDocument(tuple(observations), tuple(issues))


def read_paddle(path: Path, file_format: str) -> NativeDocument:
    """Use prepared PP-OCRv5 assets without changing the source orientation."""
    from PIL import Image

    engine = _paddle()
    if file_format == "png":
        with Image.open(path) as source:
            if source.width * source.height > _MAX_RENDER_PIXELS:
                return NativeDocument(issues=(NativeIssue("ocr_image_too_large", page=1),))
            return _ocr_frame(source.convert("RGB"), 1, engine)
    if file_format != "pdf":
        return NativeDocument(issues=(NativeIssue("ocr_unsupported_format"),))

    import pypdfium2

    observations, issues = [], []
    with pypdfium2.PdfDocument(path) as pdf:
        if len(pdf) > _MAX_PAGES:
            return NativeDocument(issues=(NativeIssue("ocr_page_limit"),))
        for index in range(len(pdf)):
            with closing(pdf[index]) as page:
                width, height = page.get_size()
                # PDFium's default render applies intrinsic page rotation.
                # No post-render crop, orientation or unwarp is applied.
                scale = min(4.0, 3300 / max(width, height))
                with closing(page.render(scale=scale)) as bitmap:
                    result = _ocr_frame(bitmap.to_pil().convert("RGB"), index + 1, engine)
            observations.extend(result.observations)
            issues.extend(result.issues)
    return NativeDocument(tuple(observations), tuple(issues))


def _position_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _overlap(left: PageLocator, right: PageLocator) -> float:
    if left.page != right.page or left.bbox is None or right.bbox is None:
        return 0
    x0, y0, x1, y1 = left.bbox
    u0, v0, u1, v1 = right.bbox
    area = max(0, min(x1, u1) - max(x0, u0)) * max(0, min(y1, v1) - max(y0, v0))
    union = (x1 - x0) * (y1 - y0) + (u1 - u0) * (v1 - v0) - area
    return area / union if union else 0


def _windows_frame(
    path: Path, page: int, helper: Path, executable: Path
) -> tuple[Observation, ...]:
    # The path is passed as an argument to the bundled helper, never executable text.
    result = subprocess.run(
        [
            str(executable),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-ImagePath",
            str(path),
        ],
        capture_output=True,
        timeout=45,
        check=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    payload = json.loads(result.stdout)
    width, height = payload["width"], payload["height"]
    if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0:
        raise ValueError("invalid Windows OCR frame dimensions")
    observations = []
    for index, line in enumerate(payload["lines"], 1):
        if not line["words"]:
            continue
        groups = []
        words = sorted(line["words"], key=lambda word: word["box"][0])
        for word in words:
            x0, y0, x1, y1 = word["box"]
            if not all(math.isfinite(x) for x in (x0, y0, x1, y1)):
                raise ValueError("non-finite Windows OCR box")
            if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
                raise ValueError("Windows OCR box outside the frame")
            prev = groups[-1][-1] if groups else None
            if prev and x0 - prev["box"][2] <= 1.5 * (y1 - y0):
                groups[-1].append(word)
            else:
                groups.append([word])
        for group_index, group in enumerate(groups, 1):
            x0 = min(word["box"][0] for word in group)
            y0 = min(word["box"][1] for word in group)
            x1 = max(word["box"][2] for word in group)
            y1 = max(word["box"][3] for word in group)
            observations.append(
                Observation(
                    " ".join(word["text"] for word in group),
                    PageLocator(
                        kind="page",
                        page=page,
                        bbox=(x0 / width, y0 / height, x1 / width, y1 / height),
                        fragment_id=f"winocr-{index}-{group_index}",
                    ),
                )
            )
    return tuple(observations)


_CONTEXT_CROP = re.compile(
    r"(?:^начало\s+[\dз]|^окончание\s+[\dз]|^\s*[\dз]+\s+этап|"
    r"^(?:контракт|договор)\b)",
    re.IGNORECASE,
)


_DATE_TRIGGER = re.compile(r"^(?:начало|окончание)\s+[\dз]", re.I)


def _lift_crop(
    fragments: list[Observation] | tuple[Observation, ...],
    image_size: tuple[int, int],
    bounds: tuple[int, int, int, int],
    page: int,
    fragment_id: str,
) -> PageLocator:
    left, top, right, bottom = bounds
    width, height = image_size
    boxes = [item.locator.bbox for item in fragments]
    return PageLocator(
        kind="page",
        page=page,
        bbox=(
            (left + min(box[0] for box in boxes) * (right - left)) / width,
            (top + min(box[1] for box in boxes) * (bottom - top)) / height,
            (left + max(box[2] for box in boxes) * (right - left)) / width,
            (top + max(box[3] for box in boxes) * (bottom - top)) / height,
        ),
        fragment_id=fragment_id,
    )


def _date_windows_crop(image, item: Observation, target, page, helper, executable):
    from PIL import Image, ImageOps

    x0, y0, x1, y1 = item.locator.bbox
    height = y1 - y0
    width = x1 - x0
    left = round(max(0, x1 + width * 0.11) * image.width)
    top = round(max(0, y0 - height * 0.45) * image.height)
    bottom = round(min(1, y1 + height * 0.42) * image.height)
    date_pattern = re.compile(r"^[\W_]*(\d{1,2})[\W_]+([а-яё]+)\s+(\d{4})(?:\s*г[^\w]*)?$", re.I)
    months = frozenset(
        "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
    )
    reads = {}
    for width_factor, scale in ((1.65, 4.5), (1.9, 4.5), (1.9, 3.0), (2.15, 3.6)):
        right = round(min(1, x1 + width * width_factor) * image.width)
        crop = ImageOps.grayscale(image.crop((left, top, right, bottom)))
        if min(crop.size) <= 0:
            continue
        scaled = crop.resize(
            (round(crop.width * scale), round(crop.height * scale)), Image.Resampling.BICUBIC
        )
        scaled.thumbnail((3500, 3500))
        scaled.save(target)
        fragments = _windows_frame(target, page, helper, executable)
        text = " ".join(part.raw_text for part in fragments)
        match = date_pattern.fullmatch(text)
        if match and match[2].casefold() in months and 1 <= int(match[1]) <= 31:
            key = tuple(part.casefold() for part in match.groups())
            location = _lift_crop(
                fragments,
                image.size,
                (left, top, right, bottom),
                page,
                f"winocr-date-{item.locator.fragment_id}",
            )
            reads.setdefault(key, []).append((text, location))
    if len(reads) != 1 or len(values := next(iter(reads.values()))) < 2:
        return None
    text, location = values[0]
    if any(_overlap(location, alternative) < 0.55 for _, alternative in values[1:]):
        return None
    return Observation(text, location, repeated_read=True)


def _context_windows_crops(
    page_image,
    raw: tuple[Observation, ...],
    target: Path,
    page: int,
    helper: Path,
    executable: Path,
) -> tuple[Observation, ...]:
    from PIL import Image

    proposals = [
        item
        for item in raw
        if _CONTEXT_CROP.search(item.raw_text) and item.locator.bbox is not None
    ]
    if len(proposals) > 16:
        return ()
    result = []
    for index, item in enumerate(proposals, 1):
        if _DATE_TRIGGER.search(item.raw_text):
            date_box = _date_windows_crop(page_image, item, target, page, helper, executable)
            if date_box is not None:
                result.append(date_box)
            continue
        x0, y0, x1, y1 = item.locator.bbox
        height = y1 - y0
        joined_context = bool(
            re.match(r"^(?:начало|окончание|контракт|договор)", item.raw_text, re.I)
        )
        width = x1 - x0
        left = max(0, round((x0 - height) * page_image.width))
        right = min(
            page_image.width,
            round(
                (x1 + max(width * 2.8, height * 19) if joined_context else x1 + height * 3)
                * page_image.width
            ),
        )
        top = max(0, round((y0 - height * 0.32) * page_image.height))
        bottom = min(page_image.height, round((y1 + height * 0.32) * page_image.height))
        local = page_image.crop((left, top, right, bottom))
        if min(local.size) <= 0:
            continue
        reads = []
        for factor in (2.7, 3.6):
            scaled = local.resize(
                (round(local.width * factor), round(local.height * factor)),
                Image.Resampling.LANCZOS,
            )
            scaled.thumbnail((3500, 3500))
            scaled.save(target)
            observations = _windows_frame(target, page, helper, executable)
            # One crop can contain two rows. Keep only words whose baseline intersects the trigger.
            fragments = [
                part
                for part in observations
                if y0 - height * 0.30
                <= (top + (part.locator.bbox[1] + part.locator.bbox[3]) * local.height / 2)
                / page_image.height
                <= y1 + height * 0.30
            ]
            if fragments:
                reads.append(sorted(fragments, key=lambda part: part.locator.bbox[0]))
        if len(reads) != 2:
            continue
        texts = [" ".join(part.raw_text for part in fragments) for fragments in reads]
        if len(Counter(_position_text(text) for text in texts)) != 1:
            continue
        locations = [
            _lift_crop(
                fragments,
                page_image.size,
                (left, top, right, bottom),
                page,
                f"winocr-context-{index}",
            )
            for fragments in reads
        ]
        if _overlap(*locations) < 0.55:
            continue
        result.append(Observation(texts[0], locations[0], repeated_read=True))
    return tuple(result)


def _repeated_full_frame_read(
    source: Observation, original: tuple[Observation, ...], verification: tuple[Observation, ...]
) -> bool:
    text = _position_text(source.raw_text)
    for frame in (original, verification):
        nearby = {
            _position_text(candidate.raw_text)
            for candidate in frame
            if _overlap(source.locator, candidate.locator) >= 0.55
        }
        if nearby != {text}:
            return False
    return True


def _read_windows_page(
    first: Path, second: Path, page: int, helper: Path, executable: Path
) -> tuple[Observation, ...]:
    original = _windows_frame(first, page, helper, executable)
    verification = _windows_frame(second, page, helper, executable)
    readings = tuple(
        replace(item, repeated_read=_repeated_full_frame_read(item, original, verification))
        for item in original
    )
    from PIL import Image

    with Image.open(first) as image:
        contexts = _context_windows_crops(
            image, readings, first.with_name("context.png"), page, helper, executable
        )
    return (*readings, *contexts)


def read_windows(path: Path, file_format: str) -> NativeDocument:
    """Reuse installed Windows OCR (Russian); publish same-engine repeat agreement only."""
    if os.name != "nt":
        return NativeDocument(issues=(NativeIssue("windows_ocr_unavailable"),))
    from PIL import Image

    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    helper = Path(__file__).with_name("windows_ocr.ps1")
    if not executable.is_file() or not helper.is_file():
        return NativeDocument(issues=(NativeIssue("windows_ocr_unavailable"),))

    with TemporaryDirectory(prefix="doccheck-winocr-") as temp:
        first = Path(temp) / "source.png"
        second = Path(temp) / "verification.png"
        if file_format == "png":
            with Image.open(path) as source:
                if source.width * source.height > _MAX_RENDER_PIXELS:
                    return NativeDocument(issues=(NativeIssue("ocr_image_too_large", page=1),))
                image = source.convert("RGB")
                image.thumbnail((3600, 3600))
                image.save(first)
                image.resize(
                    (max(1, round(image.width * 0.87)), max(1, round(image.height * 0.87))),
                    Image.Resampling.LANCZOS,
                ).save(second)
            return NativeDocument(_read_windows_page(first, second, 1, helper, executable))
        if file_format != "pdf":
            return NativeDocument(issues=(NativeIssue("ocr_unsupported_format"),))

        import pypdfium2

        observations = []
        with pypdfium2.PdfDocument(path) as pdf:
            if len(pdf) > _MAX_PAGES:
                return NativeDocument(issues=(NativeIssue("ocr_page_limit"),))
            for index in range(len(pdf)):
                with closing(pdf[index]) as page:
                    width, height = page.get_size()
                    scale = min(7.0, 3600 / max(width, height))
                    for target, factor in ((first, 1.0), (second, 0.87)):
                        with closing(page.render(scale=scale * factor)) as bitmap:
                            bitmap.to_pil().convert("RGB").save(target)
                observations.extend(
                    _read_windows_page(first, second, index + 1, helper, executable)
                )
    if not observations:
        return NativeDocument(issues=(NativeIssue("ocr_no_text"),))
    return NativeDocument(tuple(observations))
