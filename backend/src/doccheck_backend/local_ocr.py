"""Bridge an explicitly configured offline OCR provider to original-page addresses."""

import math
import os
from functools import lru_cache
from importlib import import_module
from pathlib import Path

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
            with pdf[index] as page:
                width, height = page.get_size()
                # PDFium's default render applies intrinsic page rotation.
                # No post-render crop, orientation or unwarp is applied.
                scale = min(4.0, 3300 / max(width, height))
                with page.render(scale=scale) as bitmap:
                    result = _ocr_frame(bitmap.to_pil().convert("RGB"), index + 1, engine)
            observations.extend(result.observations)
            issues.extend(result.issues)
    return NativeDocument(tuple(observations), tuple(issues))
