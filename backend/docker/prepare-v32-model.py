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
MODEL_DIR = Path("/models/qwen")


def verify_weights() -> None:
    with (MODEL_DIR / "model.safetensors").open("rb") as file:
        if file_digest(file, "sha256").hexdigest() != WEIGHTS_SHA256:
            raise SystemExit("Qwen MLX model.safetensors failed its SHA-256 check")


def main() -> None:
    marker = MODEL_DIR / ".doccheck-model-revision"
    if not (
        marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == REVISION
        and all((MODEL_DIR / name).is_file() for name in FILES)
    ):
        source = Path(environ["DOCCHECK_QWEN_SNAPSHOT_DIR"]) / REVISION
        if source.is_dir():
            if not all((source / name).is_file() for name in FILES):
                raise SystemExit("The supplied Qwen MLX snapshot is incomplete")
            for name in FILES:
                copyfile(source / name, MODEL_DIR / name)
        else:
            snapshot_download(
                REPOSITORY, revision=REVISION, allow_patterns=FILES, local_dir=MODEL_DIR
            )
        if not all((MODEL_DIR / name).is_file() for name in FILES):
            raise SystemExit("The pinned Qwen MLX snapshot is incomplete")
        verify_weights()
        marker.write_text(f"{REVISION}\n", encoding="utf-8")
    else:
        verify_weights()
    print(f"Prepared {REPOSITORY} @ {REVISION}", flush=True)


if __name__ == "__main__":
    main()
