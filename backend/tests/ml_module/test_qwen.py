"""Synthetic CPU-only tests; no model, MLX import, network or real OCR data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from doccheck_ml import qwen


class PredictionTests(unittest.TestCase):
    def test_null_and_literal_values_are_preserved(self):
        for number in (None, "КЛ-0007", "KL-0007", "0"):
            value = {"doc_number": number, "verbatim_line": None}
            self.assertEqual(qwen._parse_prediction(json.dumps(value), "stop"), value)

    def test_invalid_schema_is_never_returned_as_a_proposal(self):
        invalid = [None, "[]", "{}", '"number"', '{"doc_number":17,"verbatim_line":null}',
                   '{"doc_number":null,"verbatim_line":true}',
                   '{"doc_number":null,"verbatim_line":null,"confidence":1}']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(qwen.QwenPredictionError):
                qwen._parse_prediction(raw, "stop")

    def test_truncation_is_rejected_even_when_json_looks_complete(self):
        with self.assertRaisesRegex(qwen.QwenPredictionError, "token limit"):
            qwen._parse_prediction('{"doc_number":"42","verbatim_line":"№ 42"}', "length")

    def test_malformed_response_is_not_exposed_in_exception(self):
        with self.assertRaises(qwen.QwenPredictionError) as caught:
            qwen._parse_prediction("SYNTHETIC PRIVATE TEXT", "stop")
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_prompt_matches_frozen_training_policy(self):
        # Hash is from the original shared prompt, not an expected model answer.
        self.assertEqual(qwen.sha256(qwen.PROMPT.encode()).hexdigest(),
                         "5117a11659b6af8398664ca494cebb32601034a301547f32ea1a4297a76bd5f0")


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.model_dir = self.root / "base"
        self.model_dir.mkdir()
        for name in qwen.MODEL_FILES:
            (self.model_dir / name).write_bytes(b"synthetic local model fixture")
        self.image = self.root / "crop.png"
        self.image.write_bytes(b"synthetic image handled by fake image decoder")
        self.model = MagicMock()
        self.model.trainable_parameters.return_value = {"adapter": "restored"}
        self.processor = SimpleNamespace(
            image_processor=SimpleNamespace(min_pixels=0, max_pixels=0), tokenizer=object(),
        )
        self.runtime = SimpleNamespace(
            mx=MagicMock(), flatten=MagicMock(return_value=[]),
            load=MagicMock(return_value=(self.model, self.processor)),
            restore=MagicMock(), template=MagicMock(return_value="synthetic prompt"),
            grammar=MagicMock(return_value=object()), image=MagicMock(),
            generate=MagicMock(return_value=SimpleNamespace(
                text='{"doc_number":"КЛ-0007","verbatim_line":"№ КЛ-0007"}',
                finish_reason="stop",
            )),
        )
        crop = self.runtime.image.open.return_value.__enter__.return_value
        crop.format = "PNG"
        crop.n_frames = 1
        self.runtime_patch = patch.object(qwen, "_runtime", return_value=self.runtime)
        self.runtime_factory = self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

    def reader(self, adapter=None):
        return qwen.QwenReader(qwen.QwenConfig(self.model_dir, adapter))

    def test_init_has_no_filesystem_or_runtime_side_effects(self):
        qwen.QwenReader(qwen.QwenConfig(self.root / "not-present"))
        self.runtime_factory.assert_not_called()

    def test_invalid_crop_is_rejected_before_loading(self):
        for path in (self.root / "missing.png", self.root, self.root / "remote.pdf"):
            with self.subTest(path=path), self.assertRaises(qwen.QwenInputError):
                self.reader().read(path)
        self.runtime_factory.assert_not_called()

    def test_missing_base_is_explicit_and_never_downloaded(self):
        (self.model_dir / "model.safetensors").unlink()
        with self.assertRaises(qwen.QwenUnavailableError):
            self.reader().read(self.image)
        self.runtime_factory.assert_not_called()

    def test_missing_adapter_never_silently_uses_base(self):
        with self.assertRaisesRegex(qwen.QwenUnavailableError, "requested LoRA"):
            self.reader(self.root / "missing.safetensors").read(self.image)
        self.runtime_factory.assert_not_called()
        self.runtime.generate.assert_not_called()

    def test_adapter_requires_its_configuration(self):
        adapter = self.root / "candidate.safetensors"
        adapter.write_bytes(b"synthetic adapter")
        with self.assertRaises(qwen.QwenUnavailableError):
            self.reader(adapter).read(self.image)
        self.runtime_factory.assert_not_called()

    def test_base_reads_lazily_reuses_model_and_records_provenance(self):
        reader = self.reader()
        result = reader.read(self.image)
        second = reader.read(self.image)
        self.runtime.load.assert_called_once_with(
            str(self.model_dir), trust_remote_code=False, local_files_only=True,
        )
        self.assertEqual(result["prediction"]["doc_number"], "КЛ-0007")
        self.assertIsNone(result["adapter_sha256"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["crop_sha256"], qwen._hash_file(self.image))
        self.assertEqual(result["request_sha256"], second["request_sha256"])
        self.assertEqual(self.processor.image_processor.max_pixels, 262144)
        self.runtime.restore.assert_not_called()
        self.assertNotIn("raw_response", result)
        self.assertNotIn("image", result)
        result["model_files_sha256"].clear()
        self.assertTrue(reader.read(self.image)["model_files_sha256"])

    def test_adapter_is_restored_and_verified_before_inference(self):
        adapter_dir = self.root / "adapter"
        adapter_dir.mkdir()
        adapter = adapter_dir / "adapters.safetensors"
        adapter.write_bytes(b"synthetic adapter")
        (adapter_dir / "adapter_config.json").write_text("{}")
        value = SimpleNamespace(shape=(2, 2))
        self.runtime.mx.load.return_value = {"layer.lora_a": value}
        self.runtime.flatten.return_value = [("layer.lora_a", value)]
        self.runtime.mx.array_equal.return_value.item.return_value = True
        result = self.reader(adapter_dir).read(self.image)
        self.runtime.restore.assert_called_once_with(
            self.model, checkpoint_path=str(adapter), verbose=False,
        )
        self.assertEqual(result["adapter_sha256"], qwen._hash_file(adapter))
        self.assertEqual(result["adapter_config_sha256"],
                         qwen._hash_file(adapter_dir / "adapter_config.json"))

    def test_restoration_mismatch_never_returns_a_base_prediction(self):
        adapter = self.root / "adapters.safetensors"
        adapter.write_bytes(b"synthetic adapter")
        (self.root / "adapter_config.json").write_text("{}")
        self.runtime.mx.load.return_value = {"layer.lora_a": SimpleNamespace(shape=(2, 2))}
        self.runtime.flatten.return_value = []
        reader = self.reader(adapter)
        with self.assertRaisesRegex(qwen.QwenUnavailableError, "restored exactly"):
            reader.read(self.image)
        self.runtime.generate.assert_not_called()
        self.assertIsNone(reader._loaded)

    def test_failed_load_is_not_cached_or_inferred(self):
        self.runtime.load.side_effect = RuntimeError("SYNTHETIC PRIVATE PATH")
        reader = self.reader()
        with self.assertRaises(qwen.QwenUnavailableError) as caught:
            reader.read(self.image)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertIsNone(reader._loaded)
        self.runtime.generate.assert_not_called()

    def test_image_decode_failure_never_calls_generate(self):
        self.runtime.image.open.side_effect = OSError("SYNTHETIC PRIVATE PATH")
        with self.assertRaises(qwen.QwenInputError) as caught:
            self.reader().read(self.image)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.runtime.generate.assert_not_called()

    def test_inference_failure_is_explicit_and_not_retried(self):
        self.runtime.generate.side_effect = RuntimeError("SYNTHETIC PRIVATE TEXT")
        with self.assertRaises(qwen.QwenPredictionError) as caught:
            self.reader().read(self.image)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual(self.runtime.generate.call_count, 1)


class RuntimeTests(unittest.TestCase):
    def test_version_mismatch_fails_before_importing_model_libraries(self):
        with patch.object(qwen.metadata, "version", return_value="0.0"):
            with self.assertRaisesRegex(qwen.QwenUnavailableError, "pinned versions"):
                qwen._runtime()

    def test_missing_runtime_has_actionable_error(self):
        with patch.object(qwen.metadata, "version", side_effect=qwen.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(qwen.QwenUnavailableError, "optional MLX"):
                qwen._runtime()

    def test_import_and_init_do_not_import_heavy_runtime_or_change_environment(self):
        code = """
import os, sys
before = dict(os.environ)
from pathlib import Path
from doccheck_ml.qwen import QwenConfig, QwenReader
QwenReader(QwenConfig(Path('missing')))
assert dict(os.environ) == before
assert not any(k == 'mlx' or k.startswith('mlx.') or k.startswith('mlx_vlm')
               or k.startswith('transformers') for k in sys.modules)
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, env=dict(os.environ), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
