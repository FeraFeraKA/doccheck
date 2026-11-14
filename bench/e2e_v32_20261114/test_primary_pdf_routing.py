"""Exercise modality selection on actual PDF pages and inspect model payloads."""

import base64
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from . import run, runtime


def _text_page(writer, text, *, invisible=False):
    page = writer.add_blank_page(300, 400)
    resources = page["/Resources"]
    resources[NameObject("/Font")] = DictionaryObject({
        NameObject("/F1"): DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }),
    })
    contents = DecodedStreamObject()
    mode = 3 if invisible else 0
    contents.set_data(f"BT /F1 10 Tf {mode} Tr 10 250 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = contents
    return page


def _raster_page(writer, fill):
    image_pdf = BytesIO()
    with Image.new("RGB", (300, 400), fill) as image:
        image.save(image_pdf, format="PDF", resolution=72)
    return writer.add_page(PdfReader(image_pdf).pages[0])


class PrimaryPdfRoutingTest(unittest.TestCase):
    def test_native_only_and_raster_only_keep_their_request_shapes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for kind in ("native", "scan"):
                with self.subTest(kind=kind):
                    path = root / f"{kind}.pdf"
                    writer = PdfWriter()
                    if kind == "native":
                        _text_page(writer, "Short native text")
                    else:
                        _raster_page(writer, "green")
                    writer.write(path)

                    with patch.object(runtime, "ART", root / "runtime"), patch.object(
                        runtime, "api"
                    ) as api:
                        api.side_effect = [
                            {"message": {"content": json.dumps({"amount": None})}},
                            {"models": []},
                        ]
                        record = run.extract_primary({"id": kind, "path": str(path)}, {})

                    self.assertIsNone(record["error"])
                    self.assertEqual(record["input_kind"], kind)
                    message = api.call_args_list[0].args[1]["messages"][0]
                    if kind == "native":
                        self.assertEqual(record["raster_pages"], ())
                        self.assertIn("Short native text", message["content"])
                        self.assertNotIn("images", message)
                    else:
                        self.assertEqual(record["raster_pages"], (1,))
                        self.assertEqual(len(message["images"]), 1)

    def test_mixed_document_sends_text_and_only_its_raster_pages_in_order(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "mixed.pdf"
            writer = PdfWriter()
            _text_page(writer, "Native source page 1")
            raster_with_overlay = _raster_page(writer, "red")
            overlay = _text_page(writer, "Digital overlay longer than forty characters on a raster page.")
            raster_with_overlay.merge_page(overlay)
            del writer.pages[-1]
            _text_page(writer, "Short native page 3")
            _raster_page(writer, "blue")
            writer.write(path)

            with patch.object(runtime, "ART", root / "runtime"), patch.object(runtime, "api") as api:
                api.side_effect = [
                    {"message": {"content": json.dumps({"amount": None})}},
                    {"models": []},
                ]
                entry = {"id": "mixed", "path": str(path), "role": "primary"}
                record = run.extract_primary(entry, {})

            self.assertIsNone(record["error"])
            self.assertEqual(record["input_kind"], "mixed")
            self.assertEqual(record["raster_pages"], (2, 4))
            self.assertIsNone(record["source_native_text"])
            model_path, body = api.call_args_list[0].args
            self.assertEqual(model_path, "/api/chat")
            message = body["messages"][0]
            self.assertIn(
                "Страница 1\nNative source page 1\n"
                "Страница 2\nПриложение 1 (изображение)\n"
                "Страница 3\nShort native page 3\n"
                "Страница 4\nПриложение 2 (изображение)",
                message["content"],
            )
            self.assertNotIn("Digital overlay", message["content"])
            self.assertEqual(len(message["images"]), 2)
            for encoded, primary_channel in zip(message["images"], (0, 2)):
                with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                    pixel = image.getpixel((0, 0))
                    self.assertGreater(pixel[primary_channel], 250)
                    self.assertLess(sum(pixel) - pixel[primary_channel], 5)

    def test_short_native_text_is_read_and_invisible_text_is_not_sent_as_text(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            writer = PdfWriter()
            _text_page(writer, "Short title")
            _text_page(writer, "Invisible text only", invisible=True)
            path = root / "short.pdf"
            writer.write(path)

            pages = runtime.prepare_pdf_pages(path, root / "output")
            self.assertEqual([(page.number, page.text) for page in pages], [
                (1, "Short title"), (2, None),
            ])
            self.assertIsNone(pages[0].image)
            self.assertTrue(pages[1].image.is_file())


if __name__ == "__main__":
    unittest.main()
