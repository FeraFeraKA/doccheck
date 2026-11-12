"""Public boundary tests use generated synthetic files, never a dataset."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from doccheck_ml import DocumentInput, InputError, process_documents
from doccheck_ml.cli import demo, load_manifest


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "source.txt"
        texts = ["Акт оказанных услуг", "№ ABCD-0017 от 12.11.2026",
                 "Исполнитель: ООО Синтетика", "Итого: 123,45"]
        source.write_text("\n".join(texts), encoding="utf-8")
        self.document = DocumentInput(
            "a", source, hashlib.sha256(source.read_bytes()).hexdigest(),
            "native", [{"text": text, "page": 1, "line": i}
                       for i, text in enumerate(texts, 1)],
        )

    def test_source_number_and_money_are_extracted_without_a_model(self):
        result = process_documents([self.document])
        record = result["records"][0]
        self.assertEqual(record["number"]["value"], "ABCD-0017")
        self.assertEqual(record["facts"]["amount"], "123.45")
        self.assertTrue(record["number"]["evidence"])
        self.assertFalse(result["inference_performed"])
        self.assertFalse(result["financial_reconciliation_performed"])

    def test_identical_bytes_are_grouped_without_deleting_files(self):
        result = process_documents([self.document, replace(self.document, id="copy")])
        self.assertEqual(result["groups"]["groups"], [["a", "copy"]])
        self.assertFalse(result["groups"]["files_deleted"])
        self.assertTrue(self.document.source_path.exists())

    def test_changed_bytes_cannot_reuse_old_observations(self):
        self.document.source_path.write_text("changed", encoding="utf-8")
        result = process_documents([self.document])
        self.assertEqual(result["errors"], [{"id": "a", "code": "source_changed"}])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["groups"]["groups"], [])
        self.assertEqual(result["status"], "partial")

    def test_one_missing_file_does_not_hide_successful_documents(self):
        missing = replace(self.document, id="missing", source_path=self.root / "missing")
        result = process_documents([missing, self.document])
        self.assertEqual([r["id"] for r in result["records"]], ["a"])
        self.assertEqual(result["errors"], [{"id": "missing", "code": "source_unavailable"}])

    def test_ocr_prefix_requires_independent_recheck(self):
        document = replace(self.document, acquisition="scan", prediction={"doc_number": "0017"})
        record = process_documents([document])["records"][0]
        self.assertEqual(record["number"]["value"], "ABCD-0017")
        self.assertIsNone(record["number"]["usable_value"])
        self.assertTrue(record["number"]["manual_review_required"])

    def test_absent_fields_stay_null(self):
        document = replace(self.document, lines=[])
        record = process_documents([document])["records"][0]
        self.assertIsNone(record["number"]["value"])
        self.assertIsNone(record["facts"]["amount"])

    def test_inputs_are_not_mutated(self):
        before = json.dumps(self.document.lines, sort_keys=True)
        process_documents([self.document])
        self.assertEqual(json.dumps(self.document.lines, sort_keys=True), before)

    def test_rejects_ambiguous_or_malformed_input(self):
        invalid = [
            replace(self.document, id=""),
            replace(self.document, source_sha256="arbitrary"),
            replace(self.document, acquisition=[]),
            replace(self.document, acquisition="ocr"),
            replace(self.document, prediction={"amount": 12.5}),
            replace(self.document, prediction={"expected_answer": "17"}),
            replace(self.document, lines=[{"text": "x", "page": 0}]),
            replace(self.document, lines=[{"text": "x", "bbox": [0, 0, 1, float("nan")]}]),
            replace(self.document, lines=[{"text": "x", "bbox": [1, 1, 0, 0]}]),
            replace(self.document, lines=[{"text": 12}]),
        ]
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(InputError):
                process_documents([document])
        with self.assertRaises(InputError):
            process_documents([self.document, self.document])

    def manifest(self, source="source.txt"):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "doccheck-ml-input/1", "synthetic": True,
            "documents": [{"id": "a", "source_path": source,
                           "source_sha256": self.document.source_sha256,
                           "acquisition": "native", "lines": self.document.lines}],
        }), encoding="utf-8")
        return path

    def test_manifest_resolves_under_its_own_folder(self):
        documents, synthetic = load_manifest(self.manifest())
        self.assertTrue(synthetic)
        self.assertEqual(documents[0].source_path, self.document.source_path.resolve())

    def test_manifest_rejects_parent_absolute_and_symlink_escapes(self):
        link = self.root / "outside"
        link.symlink_to(self.root.parent, target_is_directory=True)
        for source in ("../source.txt", str(self.document.source_path), "outside/source.txt"):
            with self.subTest(source=source), self.assertRaises(InputError):
                load_manifest(self.manifest(source))

    def test_cli_writes_result_and_preserves_existing_output(self):
        manifest = self.manifest()
        output = self.root / "result.json"
        command = [sys.executable, "-m", "doccheck_ml", "process",
                   "--manifest", str(manifest), "--output", str(output)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        original = output.read_bytes()
        self.assertTrue(json.loads(original)["synthetic"])
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(output.read_bytes(), original)
        self.assertNotIn("ABCD-0017", run.stdout + run.stderr + second.stderr)

    def test_demo_is_explicitly_synthetic(self):
        result = demo()
        self.assertTrue(result["synthetic"])
        self.assertEqual(len(result["records"]), 2)
        self.assertFalse(result["inference_performed"])


if __name__ == "__main__":
    unittest.main()
