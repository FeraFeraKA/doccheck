import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from generate import SOURCE, build
from openpyxl import load_workbook
from PIL import Image, ImageChops
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class NegativeFixtureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "variants"
        self.source_hashes = {
            path: sha256(path.read_bytes()).hexdigest() for path in (SOURCE / "inputs").iterdir()
        }
        build(self.output)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.cases = {case["id"]: case for case in manifest["cases"]}

    def test_manifest_hashes_and_originals(self):
        outputs = set()
        for case in self.cases.values():
            if "output_file" in case:
                source = SOURCE / case["source_file"]
                output = self.output / "inputs" / case["output_file"]
                self.assertEqual(case["source_sha256"], self.source_hashes[source])
                self.assertEqual(case["output_sha256"], sha256(output.read_bytes()).hexdigest())
                self.assertNotEqual(case["source_sha256"], case["output_sha256"])
                outputs.add(output)
        self.assertEqual(outputs, set((self.output / "inputs").iterdir()))
        self.assertEqual(
            self.source_hashes,
            {path: sha256(path.read_bytes()).hexdigest() for path in self.source_hashes},
        )

    def test_truncated_pdf_preserves_header_without_a_readable_pdf(self):
        source = SOURCE / self.cases["truncated_pdf"]["source_file"]
        variant = self.output / "inputs/truncated_act.pdf"
        self.assertEqual(len(PdfReader(source, strict=True).pages), 1)
        self.assertTrue(variant.read_bytes().startswith(b"%PDF-"))
        with self.assertRaises(PdfReadError):
            PdfReader(variant, strict=True)

    def test_empty_file_is_zero_bytes(self):
        self.assertEqual((self.output / "inputs/empty_act.pdf").stat().st_size, 0)

    def test_workbook_is_readable_without_required_worksheet(self):
        variant = self.output / "inputs/payroll_without_required_sheet.xlsx"
        case = self.cases["missing_worksheet"]
        original = load_workbook(SOURCE / case["source_file"], read_only=True)
        self.addCleanup(original.close)
        self.assertEqual(original.sheetnames, [case["required_sheet"]])

        modified = load_workbook(variant, read_only=True)
        self.addCleanup(modified.close)
        self.assertNotIn(case["required_sheet"], modified.sheetnames)
        self.assertEqual(modified.active["A1"].value, "ТЕХНИЧЕСКАЯ ФИКСТУРА")
        self.assertIsNone(modified.active["C8"].value)

    def test_links_to_existing_partial_sum_expectation(self):
        case = self.cases["equal_partial_sum"]
        source = (SOURCE / case["expectations_file"]).read_bytes()
        self.assertEqual(sha256(source).hexdigest(), case["expectations_sha256"])
        expectations = json.loads(source)
        row = next(row for row in expectations["rows"] if row["id"] == case["synthetic_row_id"])
        self.assertEqual(row["reported_amount"], row["available_subtotal"])
        self.assertEqual(row["completeness"], "incomplete")
        self.assertEqual(row["expected_status"], case["expected_status"])
        self.assertEqual(row["expected_amount"], case["expected_amount"])
        self.assertEqual(row["delta"], case["delta"])

    def test_png_rotation_and_noise_are_reproducible(self):
        repeated = self.output.with_name("repeated")
        build(repeated)
        expected_pixel_hashes = {
            "rotated_png": "9f4ff90f3aa47fd42bb979e3ae257d1846b0c7db0f23a76fec6e88b80b919149",
            "noisy_png": "beca712ee5dbff1b54cf854b3f5f67ff6e5d6320e909d775a2cc5cea285025f0",
        }
        for case_id, pixel_hash in expected_pixel_hashes.items():
            with self.subTest(case=case_id):
                case = self.cases[case_id]
                path = Path("inputs") / case["output_file"]
                with (
                    Image.open(SOURCE / case["source_file"]) as original,
                    Image.open(self.output / path) as variant,
                    Image.open(repeated / path) as next_variant,
                ):
                    self.assertEqual(variant.format, "PNG")
                    self.assertEqual(variant.size, (case["output_width"], case["output_height"]))
                    self.assertEqual(variant.mode, case["output_pixel_mode"])
                    self.assertEqual(variant.tobytes(), next_variant.tobytes())
                    self.assertEqual(sha256(variant.tobytes()).hexdigest(), pixel_hash)
                    self.assertEqual(case["output_pixel_sha256"], pixel_hash)
                    if case_id == "rotated_png":
                        self.assertEqual(variant.size, (original.height, original.width))
                        restored = variant.transpose(Image.Transpose.ROTATE_270)
                        self.assertEqual(restored.tobytes(), original.tobytes())
                    else:
                        self.assertEqual(variant.size, original.size)
                        self.assertIsNotNone(ImageChops.difference(original, variant).getbbox())
