"""Export the JSON Schema from the installed backend models."""

import json
from pathlib import Path

from doccheck_backend.contracts import CheckJob

if __name__ == "__main__":
    path = Path(__file__).with_name("check-result.v1.schema.json")
    schema = json.dumps(CheckJob.model_json_schema(), ensure_ascii=False, indent=2)
    path.write_text(schema + "\n", encoding="utf-8")
