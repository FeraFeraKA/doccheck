"""Build isolated technical QA variants from the public NRT-89 package."""

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "docs/synthetic/nrt-89"


def build(output: Path) -> None:
    manifest = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    source_index = json.loads((SOURCE / "inputs.json").read_text(encoding="utf-8"))
    if source_index["synthetic"] is not True:
        raise ValueError("Expected the public synthetic NRT-89 package")
    sources = {entry["id"]: entry for entry in source_index["files"]}

    variants = []
    for case in manifest["cases"]:
        if "output_file" not in case:
            expectations = SOURCE / case["expectations_file"]
            case["expectations_sha256"] = sha256(expectations.read_bytes()).hexdigest()
            continue
        source = sources[case["source_id"]]
        original = (SOURCE / source["file"]).read_bytes()
        original_hash = sha256(original).hexdigest()
        if original_hash != source["sha256"]:
            raise ValueError(f"Source SHA-256 mismatch: {source['id']}")

        match case["mutation"]:
            case "keep_pdf_header_and_first_object":
                end = original.index(b"endobj") + len(b"endobj")
                variant = original[:end] + b"\n"
            case "clear_bytes":
                variant = b""
            case "remove_required_worksheet":
                with BytesIO(original) as stream, BytesIO() as binary:
                    workbook = load_workbook(stream)
                    try:
                        placeholder = workbook.create_sheet("Синтетическая проверка")
                        placeholder["A1"] = "ТЕХНИЧЕСКАЯ ФИКСТУРА"
                        del workbook[case["required_sheet"]]
                        workbook.active = 0
                        workbook.save(binary)
                        variant = binary.getvalue()
                    finally:
                        workbook.close()
            case _:
                raise ValueError(f"Unknown mutation: {case['mutation']}")

        case.update(
            source_file=source["file"],
            source_sha256=original_hash,
            output_sha256=sha256(variant).hexdigest(),
        )
        variants.append((case["output_file"], variant))

    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    for filename, variant in variants:
        (inputs / filename).write_bytes(variant)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()
