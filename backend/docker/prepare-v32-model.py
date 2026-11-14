"""Prepare the documented MLX base in a Compose volume before offline inference."""

from hashlib import file_digest
from os import environ
from pathlib import Path
from shutil import copyfile

from huggingface_hub import snapshot_download

REPOSITORY = "mlx-community/Qwen3.5-4B-MLX-4bit"
REVISION = "32f3e8ecf65426fc3306969496342d504bfa13f3"
WEIGHTS_SHA256 = "5fb9acd0246866381cf8c5c354c6db1019f6498eec4ccb4f5edcc71ffeacb2db"
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


def verify_weights(weights: Path) -> None:
    with weights.open("rb") as file:
        if file_digest(file, "sha256").hexdigest() != WEIGHTS_SHA256:
            raise SystemExit("Qwen MLX model.safetensors failed its SHA-256 check")


def main() -> None:
    model_dir = Path("/models/qwen")
    marker = model_dir / ".doccheck-model-revision"
    weights = model_dir / "model.safetensors"
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
                if name == weights.name:
                    verify_weights(partial)
                partial.replace(destination)
        missing = [name for name in FILES if not (model_dir / name).is_file()]
        if weights.is_file():
            verify_weights(weights)
        if missing:
            snapshot_download(
                REPOSITORY, revision=REVISION, allow_patterns=missing, local_dir=model_dir
            )
        if not all((model_dir / name).is_file() for name in FILES):
            raise SystemExit("The pinned Qwen MLX snapshot is incomplete")
        if weights.name in missing:
            verify_weights(weights)
        marker.write_text(f"{REVISION}\n", encoding="utf-8")
    else:
        verify_weights(weights)
    print(f"Prepared {REPOSITORY} @ {REVISION}", flush=True)


if __name__ == "__main__":
    main()
