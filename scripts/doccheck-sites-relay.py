"""Run Site trial requests on the isolated local synthetic worker over outbound HTTPS."""

import argparse
import base64
import json
import re
import time
from hashlib import file_digest, sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from doccheck_backend.contracts import CheckResult
from doccheck_backend.run_xlsx import export_check_result

_LOCAL_ORIGIN = "http://127.0.0.1:18743"
_JOB = re.compile(r"[0-9a-f-]{36}")
_TERMINAL = {"completed", "completed_with_issues", "failed"}
_MAX_RELAY_PAYLOAD = 3_500_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = build_opener(_NoRedirect())


def request(
    origin: str, route: str, *, token=None, payload=None, method="GET", binary=False
):
    headers = {"User-Agent": "DocCheck-Trial-Relay"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(origin + route, data=payload, headers=headers, method=method)
    with _opener.open(req, timeout=25) as response:
        content = response.read()
        return content if binary else json.loads(content)


def manifest_hashes(state: Path) -> set[str]:
    package = state / "package"
    manifest = json.loads((package / "inputs.json").read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True or len(manifest["files"]) != 23:
        raise ValueError("The trial relay requires the generated synthetic fixture")
    hashes = set()
    for entry in manifest["files"]:
        source = (package / entry["file"]).resolve(strict=True)
        if not source.is_relative_to((package / "inputs").resolve(strict=True)):
            raise ValueError("Unexpected trial fixture location")
        with source.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError("A trial fixture changed")
        hashes.add(digest)
    return hashes


def start_local(job: str) -> str:
    # The bridge retries transport without running the same public job again.
    # It does not use the private pilot or the general-purpose upload endpoint.
    submitted = request(_LOCAL_ORIGIN, "/api/v0/trial", method="POST", payload=b"")
    local_id = submitted["run_id"]
    if not _JOB.fullmatch(local_id):
        raise ValueError("The trial returned an invalid ID")
    print("Site trial accepted", job, flush=True)
    return local_id


def build_result(local_id: str, hosted_id: str, hashes: set[str]) -> dict | None:
    endpoint = f"/api/v0/runs/{local_id}"
    state = request(_LOCAL_ORIGIN, endpoint)
    status = state["status"]
    if status not in _TERMINAL:
        return None
    if status == "failed":
        return {"status": "failed"}
    findings = request(_LOCAL_ORIGIN, endpoint + "/findings")
    if (
        findings.get("synthetic") is not True
        or len(findings["documents"]) != 23
        or {doc["sha256"] for doc in findings["documents"]} != hashes
        or not findings["versions"].get("model_revision")
    ):
        raise ValueError("The local result does not match the synthetic fixture")
    findings["run_id"] = hosted_id
    originals = {}
    for doc in findings["documents"]:
        source = request(
            _LOCAL_ORIGIN, endpoint + "/documents/" + doc["id"], binary=True
        )
        if sha256(source).hexdigest() != doc["sha256"]:
            raise ValueError("A returned synthetic source changed")
        originals[doc["id"]] = base64.b64encode(source).decode("ascii")
    export = export_check_result(CheckResult.model_validate(findings))
    return {
        "status": status,
        "findings": findings,
        "originals": originals,
        "xlsx": base64.b64encode(export).decode("ascii"),
    }


def loop(origin: str, token: str, hashes: set[str]) -> None:
    hosted_id = local_id = None
    queued_at = 0.0
    backoff = 2
    while True:
        try:
            if hosted_id is None:
                value = request(origin, "/_worker/next", token=token)["job"]
                if isinstance(value, str) and _JOB.fullmatch(value):
                    hosted_id = value
                    queued_at = time.monotonic()
            if hosted_id is not None:
                if local_id is None:
                    request(
                        origin,
                        f"/_worker/{hosted_id}/started",
                        token=token,
                        method="POST",
                        payload=b"",
                    )
                    local_id = start_local(hosted_id)
                result = build_result(local_id, hosted_id, hashes)
                if result is None and time.monotonic() - queued_at > 180:
                    result = {"status": "failed"}
                if result is not None:
                    payload = json.dumps(result, ensure_ascii=False).encode()
                    if len(payload) > _MAX_RELAY_PAYLOAD:
                        raise ValueError(
                            "The synthetic payload exceeded the relay limit"
                        )
                    request(
                        origin,
                        f"/_worker/{hosted_id}/result",
                        token=token,
                        method="POST",
                        payload=payload,
                    )
                    print("Site trial saved", hosted_id, result["status"], flush=True)
                    hosted_id = local_id = None
            backoff = 2
        except (HTTPError, URLError, TimeoutError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            print("Trial relay connection", code, flush=True)
            if code in {404, 409}:
                hosted_id = local_id = None
            backoff = min(15, backoff * 2)
        time.sleep(backoff)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origin")
    parser.add_argument(
        "--state", type=Path, default=Path.home() / "doccheck-data/public-trial"
    )
    args = parser.parse_args()
    url = urlsplit(args.origin)
    if (
        url.scheme != "https"
        or not (url.hostname or "").endswith(".chatgpt.site")
        or url.path
        or url.query
        or url.fragment
        or url.username is not None
    ):
        parser.error("Use the exact deployed HTTPS Sites origin")
    token = (args.state / "relay-token").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{64}", token):
        parser.error("A configured relay credential is required")
    if request(_LOCAL_ORIGIN, "/health") != {
        "status": "ok",
        "database": "ok",
        "public_trial": True,
    }:
        parser.error("The isolated local trial origin is not available")
    if not request(args.origin, "/health").get("public_trial"):
        parser.error("The hosted public trial is not available")
    print("Trial relay ready", flush=True)
    loop(args.origin, token, manifest_hashes(args.state))


if __name__ == "__main__":
    main()
