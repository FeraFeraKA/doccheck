"""Prepare the documented MLX base in a Compose volume before offline inference."""

from hashlib import file_digest
from os import environ
from pathlib import Path
from shutil import copyfile
from urllib.request import urlopen

from huggingface_hub import snapshot_download

REPOSITORY = "mlx-community/Qwen3.5-4B-MLX-4bit"
REVISION = "32f3e8ecf65426fc3306969496342d504bfa13f3"
WEIGHTS_SHA256 = "5fb9acd0246866381cf8c5c354c6db1019f6498eec4ccb4f5edcc71ffeacb2db"
TOKENIZER_SHA256 = "87a7830d63fcf43bf241c3c5242e96e62dd3fdc29224ca26fed8ea333db72de4"
BASE_SHA256 = {"model.safetensors": WEIGHTS_SHA256, "tokenizer.json": TOKENIZER_SHA256}
LORA_RELEASE = "https://github.com/VCyberPunk2077/doccheck/releases/download/doccheck-lora-0000100"
LORA_CHECKPOINT = "0000100_adapters.safetensors"
LORA_SHA256 = {
    LORA_CHECKPOINT: "9fc6c4055f040d9698ea14b9594842cb1951b2c5de112d0dc8f6cd55a8b5deb2",
    "adapter_config.json": "04dae62af43bf149a4aaf02760ab181abe89e36bd9973046f86debd86e1ea100",
}
FILES = (
    "chat_template.jinja",
    "config.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "video_preprocessor_config.json",
    "vocab.json",
)


def verify_checksum(path: Path, name: str, expected: str) -> None:
    with path.open("rb") as file:
        if file_digest(file, "sha256").hexdigest() != expected:
            raise SystemExit(f"{name} failed its SHA-256 check")


def prepare_lora() -> None:
    directory = Path("/models/lora")
    filename = environ.get("DOCCHECK_LORA_FILENAME", LORA_CHECKPOINT)
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise SystemExit("DOCCHECK_LORA_FILENAME must be a filename")
    if filename != LORA_CHECKPOINT:
        if not all((directory / name).is_file() for name in (filename, "adapter_config.json")):
            raise SystemExit("Provide the custom LoRA checkpoint and adapter_config.json")
        return

    for name, expected in LORA_SHA256.items():
        path = directory / name
        if path.is_file():
            verify_checksum(path, name, expected)
            continue
        with urlopen(f"{LORA_RELEASE}/{name}", timeout=30) as response:
            contents = response.read()
        partial = path.with_suffix(path.suffix + ".downloading")
        partial.write_bytes(contents)
        verify_checksum(partial, name, expected)
        partial.replace(path)
    print(f"Prepared LoRA {filename}", flush=True)


def main() -> None:
    prepare_lora()
    model_dir = Path("/models/qwen")
    marker = model_dir / ".doccheck-model-revision"
    if not (
        marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == REVISION
        and all((model_dir / name).is_file() for name in FILES)
    ):
        source = Path(environ["DOCCHECK_QWEN_SNAPSHOT_DIR"]) / REVISION
        for name in FILES:
            destination = model_dir / name
            if (source / name).is_file() and not destination.is_file():
                partial = destination.with_suffix(destination.suffix + ".importing")
                copyfile(source / name, partial)
                if name in BASE_SHA256:
                    verify_checksum(partial, name, BASE_SHA256[name])
                partial.replace(destination)
        missing = [name for name in FILES if not (model_dir / name).is_file()]
        if missing:
            snapshot_download(
                REPOSITORY, revision=REVISION, allow_patterns=missing, local_dir=model_dir
            )
        if not all((model_dir / name).is_file() for name in FILES):
            raise SystemExit("The pinned Qwen MLX snapshot is incomplete")
    for name, expected in BASE_SHA256.items():
        verify_checksum(model_dir / name, name, expected)
    marker.write_text(f"{REVISION}\n", encoding="utf-8")
    print(f"Prepared {REPOSITORY} @ {REVISION}", flush=True)


if __name__ == "__main__":
    main()
