"""Explicit synthetic smoke run and a local observation-manifest interface."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from .api import DocumentInput, InputError, process_documents


def demo() -> dict[str, object]:
    """A generated fixture only; no model, original dataset or external calls."""
    texts = ["Акт оказанных услуг", "№ DEMO-0042 от 12.11.2026",
             "Исполнитель: ООО Синтетический пример", "Итого: 123,45"]
    with TemporaryDirectory(prefix="doccheck-demo-") as folder:
        source = Path(folder) / "synthetic.txt"
        source.write_text("\n".join(texts), encoding="utf-8")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        lines = [{"text": text, "page": 1, "line": index}
                 for index, text in enumerate(texts, 1)]
        return process_documents([
            DocumentInput("demo-a", source, digest, "native", lines),
            DocumentInput("demo-copy", source, digest, "native", lines),
        ], synthetic=True)


def load_manifest(path: Path) -> tuple[list[DocumentInput], bool]:
    """Resolve only files inside the manifest folder, including symlink targets."""
    root = path.resolve().parent
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict)
            or set(payload) != {"schema_version", "synthetic", "documents"}
            or payload["schema_version"] != "doccheck-ml-input/1"
            or type(payload["synthetic"]) is not bool
            or not isinstance(payload["documents"], list)):
        raise InputError("Invalid doccheck-ml-input/1 manifest")
    documents = []
    required = {"id", "source_path", "source_sha256", "acquisition", "lines"}
    for row in payload["documents"]:
        if (not isinstance(row, dict) or not required <= set(row)
                or set(row) - required - {"prediction"}
                or not isinstance(row["source_path"], str)
                or not row["source_path"]):
            raise InputError("Invalid document manifest entry")
        relative = Path(row["source_path"])
        source = (root / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(root):
            raise InputError("Source must stay within the manifest directory")
        documents.append(DocumentInput(**{**row, "source_path": source}))
    return documents, payload["synthetic"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Run a visibly synthetic CPU example")
    process = commands.add_parser("process", help="Process local source observations")
    process.add_argument("--manifest", type=Path, required=True)
    process.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "demo":
            print(json.dumps(demo(), ensure_ascii=False, indent=2))
            return 0
        documents, synthetic = load_manifest(args.manifest)
        result = process_documents(documents, synthetic=synthetic)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
        print(json.dumps({"status": result["status"],
                          "documents": len(result["records"]),
                          "file_errors": len(result["errors"])}))
        return 2 if result["errors"] else 0
    except (InputError, OSError, ValueError):
        # Detailed input/result contents belong in the worker's local storage.
        print("Invalid input, unavailable file or existing output", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
