import io
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.run_worker import run_document_worker
from doccheck_backend.v32_processor import V32Processor


def test_v32_worker_preserves_number_when_document_prediction_fails(database_url, tmp_path):
    qwen = pytest.importorskip("doccheck_ml.qwen")
    pytest.importorskip("bench.e2e_v32_20261114")

    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = "Договор № TEST-26"
    sheet["A4"] = "Период: 2026-01-01 — 2026-01-31. Этап 1."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    sheet["B7"], sheet["C7"] = "Общепроизводственные расходы", 1250
    sheet["A8"], sheet["C8"] = "Всего по отчету", "=SUM(C7:C7)"
    report, image = io.BytesIO(), io.BytesIO()
    book.save(report)
    Image.new("RGB", (32, 32), "white").save(image, format="PNG")

    seen = []

    def read_number(path):
        seen.append(Path(path))
        assert path.is_file()
        return {
            "adapter_sha256": "a" * 64,
            "model_sha256": "b" * 64,
            "policy_sha256": "c" * 64,
            "prediction": {"doc_number": "007-26", "verbatim_line": "Акт № 007-26"},
        }

    def read_document(*args, **kwargs):
        raise qwen.QwenPredictionError("test detail must stay out of the result")

    processor = V32Processor(read_document, read_number)
    engine = create_database_engine(database_url)
    try:
        with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
            submitted = client.post(
                "/api/v0/runs",
                headers={"Idempotency-Key": str(uuid4())},
                files=[
                    ("report", ("report.xlsx", report.getvalue())),
                    ("documents", ("act.png", image.getvalue())),
                    ("documents", ("duplicate.png", image.getvalue())),
                ],
            )
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            assert run_document_worker(engine, tmp_path, processor, once=True)
            state = client.get(f"/api/v0/runs/{run_id}").json()
            assert state["status"] == "completed_with_issues"
            response = client.get(f"/api/v0/runs/{run_id}/findings")
            assert response.status_code == 200
            result = response.json()
    finally:
        engine.dispose()

    assert len(seen) == 1 and not seen[0].exists()
    assert "test detail" not in response.text
    assert result["versions"]["model_revision"] == f"{'b' * 64}+lora:{'a' * 64}"
    assert sum(document["duplicate_of"] is not None for document in result["documents"]) == 1
    assert any(
        item["method"] == "qwen_proposal" and item["normalized_value"] == "007-26"
        for item in result["evidence"]
    )
    assert result["rows"][0]["reported_value"] == "1250.00"
    assert result["rows"][0]["status"] == "unverified"
