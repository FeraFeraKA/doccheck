"""Pull approved synthetic work over HTTPS and run its processor locally."""

import argparse
import hashlib
import hmac
import http.client
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Issue
from doccheck_backend.run_worker import RunProcessor, StoredRun

_LOG = logging.getLogger(__name__)
_FILE_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_FILE_LIMIT = 2 * 1024**2
_RESULT_LIMIT = 1024**2


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _TransientDownloadError(RuntimeError):
    """The current lease can expire and be reclaimed."""


class HostedClient:
    def __init__(self, origin: str, token: str) -> None:
        address = urlsplit(origin)
        if (
            not address.hostname
            or address.username is not None
            or address.password is not None
            or address.path
            or address.query
            or address.fragment
            or (
                address.scheme != "https"
                and not (address.scheme == "http" and address.hostname == "127.0.0.1")
            )
        ):
            raise ValueError("Worker needs an HTTPS origin or local 127.0.0.1 test")
        if not 32 <= len(token) <= 256 or not token.isascii():
            raise ValueError("Missing valid worker token")
        self._origin = origin
        self._token = token
        self._opener = build_opener(ProxyHandler({}), _NoRedirects())

    def request(self, method: str, path: str, *, body: bytes | None = None):
        return self._opener.open(
            Request(
                self._origin + "/api/worker/v1" + path,
                method=method,
                headers={
                    "Authorization": "Bearer " + self._token,
                    "Content-Type": "application/json",
                },
                data=body,
            ),
            timeout=10,
        )

    def claim(self) -> dict | None:
        with self.request("POST", "/claims", body=b"") as response:
            if response.status == 204:
                return None
            content = response.read(64 * 1024 + 1)
            if len(content) > 64 * 1024:
                raise ValueError("Worker claim too large")
            claim = json.loads(content)
            if not isinstance(claim, dict):
                raise ValueError("Invalid worker claim")
            return claim

    def download(self, claim: dict, folder: Path) -> None:
        documents = claim["documents"]
        if not 2 <= len(documents) <= 9:
            raise ValueError("Invalid document count")
        lease = UUID(claim["lease_id"])
        for document in documents:
            identifier = document["id"]
            size = document["size"]
            digest = document["sha256"]
            if (
                not _FILE_ID.fullmatch(identifier)
                or not _DIGEST.fullmatch(digest)
                or type(size) is not int
                or not 0 < size <= _FILE_LIMIT
            ):
                raise ValueError("Invalid document manifest")
            payload = self._download_payload(lease, identifier, size)
            if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), digest):
                raise ValueError("Document integrity check failed")
            with (folder / identifier).open("xb") as output:
                output.write(payload)

    def _download_payload(self, lease: UUID, identifier: str, size: int) -> bytes:
        for attempt in range(3):
            try:
                with self.request("GET", f"/claims/{lease}/files/{identifier}") as response:
                    payload = response.read(size + 1)
                if len(payload) > size:
                    raise ValueError("Document exceeds recorded size")
                if len(payload) == size:
                    return payload
            except HTTPError as error:
                if error.code in {404, 409}:
                    raise _TransientDownloadError("Hosted original or lease disappeared") from None
                if error.code not in {408, 429, 500, 502, 503, 504}:
                    raise
            except (OSError, http.client.HTTPException):
                pass
            if attempt < 2:
                time.sleep(attempt + 1)
        raise _TransientDownloadError("Retryable failure while downloading hosted original")

    def process_one(self, process: RunProcessor) -> bool:
        claim = self.claim()
        if claim is None:
            return False
        lease = UUID(claim["lease_id"])
        run_id = UUID(claim["run_id"])
        with TemporaryDirectory(prefix="doccheck-hosted-") as directory:
            folder = Path(directory)
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(self._process, claim, folder, run_id, process)
                while not result.done():
                    try:
                        result.result(timeout=15)
                    except TimeoutError:
                        with self.request("POST", f"/claims/{lease}/heartbeat", body=b""):
                            pass
                    else:
                        break
                outcome = result.result()
            body = outcome.model_dump_json().encode()
            if len(body) > _RESULT_LIMIT:
                body = self._failure(run_id).model_dump_json().encode()
            try:
                with self.request("PUT", f"/claims/{lease}/result", body=body):
                    pass
            except HTTPError:
                raise
            except (TimeoutError, URLError, http.client.HTTPException):
                # A response may be lost after the server commits. Reuse the exact result.
                with self.request("PUT", f"/claims/{lease}/result", body=body):
                    pass
        return True

    def _process(self, claim: dict, folder: Path, run_id: UUID, process: RunProcessor) -> CheckJob:
        try:
            self.download(claim, folder)
            return process(StoredRun(run_id, claim["scope"], claim["documents"]), folder)
        except _TransientDownloadError:
            # Let the server reassign the generation when the last heartbeat expires.
            raise
        except Exception as error:
            _LOG.warning("Hosted processing failed (%s)", type(error).__name__)
            return self._failure(run_id)

    @staticmethod
    def _failure(run_id: UUID) -> CheckJob:
        return CheckJob(
            run_id=str(run_id),
            status="failed",
            result=None,
            error=Issue(code="processing_failed", message="Не удалось обработать пакет."),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--processor", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    module, separator, function = args.processor.partition(":")
    if (
        not separator
        or not function.isidentifier()
        or not all(part.isidentifier() for part in module.split("."))
    ):
        parser.error("processor must be module:callable")
    client = HostedClient(args.origin, os.environ.get("DOCCHECK_HOSTED_WORKER_TOKEN", ""))
    process = getattr(import_module(module), function)
    if not callable(process):
        parser.error("processor must be module:callable")
    while True:
        try:
            claimed = client.process_one(process)
        except HTTPError as error:
            _LOG.error("Hosted worker request failed (HTTP %s)", error.code)
            if args.once or error.code in (401, 403, 404):
                return 1
            claimed = False
        except (OSError, ValueError, http.client.HTTPException, _TransientDownloadError):
            _LOG.error("Hosted worker request failed")
            if args.once:
                return 1
            # A claim may have committed before its response was lost. Poll
            # again after the usual delay and let the unreceived lease expire.
            claimed = False
        if args.once:
            return 0
        if not claimed:
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
