"""Synthetic reproductions of the three unresolved PR #8 findings.

These assertions describe the required behavior, not the current defects.
NRT-92 audits the existing module without changing its runtime; expected failures
keep the known limitations visible. Remove the corresponding decorator when a
runtime fix is assigned: an unexpected success must not silently remain ignored.
"""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from doccheck_ml import DocumentInput, process_documents


class ModuleAuditRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "synthetic-audit.txt"

    def _process(
        self, texts: tuple[str, ...], prediction: dict[str, str] | None = None
    ) -> dict[str, object]:
        self.source.write_text("\n".join(texts), encoding="utf-8")
        lines = [
            {"text": text, "page": 1, "line": index}
            for index, text in enumerate(texts, 1)
        ]
        document = DocumentInput(
            id="synthetic-audit",
            source_path=self.source,
            source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            acquisition="native",
            lines=lines,
            prediction=prediction or {},
        )
        result = process_documents([document], synthetic=True)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["inference_performed"])
        return result

    @unittest.expectedFailure
    def test_contract_reference_date_does_not_replace_document_date(self) -> None:
        # https://github.com/VCyberPunk2077/doccheck/pull/8#discussion_r4557864144
        result = self._process((
            "Акт № 17 по договору № CT-001 от 01.03.2026",
            "Дата документа: 12.11.2026",
        ))
        record = result["records"][0]
        self.assertEqual(record["source_facts"]["date"], "2026-11-12")
        self.assertEqual(record["facts"]["date"], "2026-11-12")
        self.assertEqual(record["fact_evidence"]["date"], [
            {"text": "Дата документа: 12.11.2026", "page": 1, "line": 2},
        ])

    @unittest.expectedFailure
    def test_truncated_native_number_requires_manual_review(self) -> None:
        # https://github.com/VCyberPunk2077/doccheck/pull/8#discussion_r4557864155
        result = self._process(("Акт № 17...",))
        number = result["records"][0]["number"]
        self.assertIsNone(number["usable_value"])
        self.assertTrue(number["manual_review_required"])
        self.assertIn(
            "synthetic-audit", result["review_queue"]["number_review_document_ids"]
        )

    def _assert_negative_total(
        self, texts: tuple[str, ...], prediction: dict[str, str] | None = None
    ) -> None:
        result = self._process(texts, prediction)
        record = result["records"][0]
        self.assertEqual(record["source_facts"].get("amount"), "-100.00")
        self.assertEqual(record["facts"]["amount"], "-100.00")
        self.assertEqual(record["fact_evidence"]["amount"], [
            {"text": text, "page": 1, "line": index}
            for index, text in enumerate(texts, 1)
        ])

    @unittest.expectedFailure
    def test_same_line_negative_total_preserves_sign(self) -> None:
        # https://github.com/VCyberPunk2077/doccheck/pull/8#discussion_r4557864167
        self._assert_negative_total(("Итого: -100,00",))

    @unittest.expectedFailure
    def test_adjacent_line_negative_total_preserves_sign(self) -> None:
        # Same finding, with an explicitly adjacent value on the next line.
        self._assert_negative_total(("Итого", "-100,00"))

    @unittest.expectedFailure
    def test_negative_source_total_overrides_positive_model_proposal(self) -> None:
        # A model suggestion must not replace the printed sign of the total.
        self._assert_negative_total(("Итого: -100,00",), {"amount": "100.00"})


if __name__ == "__main__":
    unittest.main()
