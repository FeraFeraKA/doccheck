"""Queue a synthetic package from an explicitly pinned local manifest."""

import argparse
import json
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from starlette.datastructures import FormData, UploadFile

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.uploads import store_run

_FILE_LIMIT = 2 * 1024**2


class SyntheticFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sha256: str


class SyntheticPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    synthetic: Literal[True]
    report: SyntheticFile
    documents: list[SyntheticFile]


def seed(settings: Settings, manifest: Path, expected: str, key: UUID) -> UUID:
    if not settings.public_demo or settings.hosted_worker_digest is None:
        raise ValueError("Synthetic worker queue is disabled")
    with manifest.open("rb") as handle:
        content = handle.read(16 * 1024 + 1)
    if len(content) > 16 * 1024 or sha256(content).hexdigest() != expected:
        raise ValueError("Synthetic package manifest digest mismatch")
    package = SyntheticPackage.model_validate(json.loads(content))
    if not 1 <= len(package.documents) <= 8:
        raise ValueError("Synthetic package has an invalid file count")
    root = manifest.parent.resolve(strict=True)
    files = [("report", package.report), *(("documents", file) for file in package.documents)]
    with ExitStack() as stack:
        uploads = []
        names = set()
        for field, file in files:
            path = root / file.name
            if path.parent != root or path.resolve(strict=True) != path or file.name in names:
                raise ValueError("Invalid synthetic package file")
            if path.suffix.lower() != (".xlsx" if field == "report" else ".docx"):
                raise ValueError("Invalid synthetic package file format")
            names.add(file.name)
            with path.open("rb") as handle:
                payload = handle.read(_FILE_LIMIT + 1)
            if len(payload) > _FILE_LIMIT or sha256(payload).hexdigest() != file.sha256:
                raise ValueError("Synthetic file digest mismatch")
            buffer = stack.enter_context(BytesIO(payload))
            uploads.append((field, UploadFile(buffer, size=len(payload), filename=file.name)))
        engine = create_database_engine(settings.database_url)
        stack.callback(engine.dispose)
        return store_run(
            engine, settings.upload_root, key, FormData(uploads), hosted_synthetic=True
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("manifest_sha256")
    parser.add_argument("request_id", type=UUID)
    args = parser.parse_args()
    print(seed(Settings.from_env(), args.manifest, args.manifest_sha256, args.request_id))


if __name__ == "__main__":
    main()
