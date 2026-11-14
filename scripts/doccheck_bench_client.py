"""Measure a protected DocCheck run and verify its returned source fragments."""

import base64
import io
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def client(port: int):
    state = Path(
        os.environ.get("DOCCHECK_PILOT_HOME", Path.home() / "doccheck-data/pilot")
    )
    credentials = (state / "access").read_text().strip()
    encoded = base64.b64encode(credentials.encode()).decode()
    context = ssl.create_default_context(cafile=str(state / "localhost.crt"))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    origin = f"https://localhost:{port}"

    def request(path: str, data=None, headers=None, *, binary: bool = False):
        req = urllib.request.Request(
            origin + path,
            data=data,
            headers={"Authorization": "Basic " + encoded, **(headers or {})},
        )
        with opener.open(req, timeout=125) as response:
            content = response.read()
            return response.status, content if binary else json.loads(content)

    return request


def upload(request, files: list[tuple[str, Path]], fields: dict[str, str]) -> str:
    boundary = "doccheck-" + uuid4().hex
    data = io.BytesIO()
    for key, value in fields.items():
        data.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    for role, path in files:
        name = path.name.replace('"', "_")
        data.write(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{role}"; '
                f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            ).encode()
        )
        data.write(path.read_bytes())
        data.write(b"\r\n")
    data.write(f"--{boundary}--\r\n".encode())
    _, response = request(
        "/api/v0/runs",
        data.getvalue(),
        {
            "Idempotency-Key": str(uuid4()),
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
    )
    return response["run_id"]


def run(
    request, files: list[tuple[str, Path]], fields: dict[str, str], output: Path
) -> None:
    started = time.monotonic()
    run_id = upload(request, files, fields)
    print("queued", run_id, len(files), flush=True)
    endpoint = f"/api/v0/runs/{run_id}"
    previous = None
    for _ in range(950):
        _, state = request(endpoint)
        if state["status"] != previous:
            previous = state["status"]
            print(run_id, previous, round(time.monotonic() - started, 2), flush=True)
        if previous not in {"queued", "processing"}:
            break
        time.sleep(2)
    else:
        raise TimeoutError("Worker is not completing the run")

    timing = {
        "seconds": round(time.monotonic() - started, 2),
        "files": len(files),
        "run_id": run_id,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    if state["status"] != "failed":
        _, findings = request(endpoint + "/findings")
        for evidence in findings["evidence"]:
            if evidence["kind"] not in {"amount", "reported_value"}:
                continue
            path = f"{endpoint}/documents/{evidence['document_id']}/fragments/{evidence['id']}"
            _, verified = request(path)
            if verified != evidence:
                raise ValueError(
                    "An addressed amount differed from its source fragment"
                )
        _, workbook = request(endpoint + "/exports/xlsx", binary=True)
        if not workbook.startswith(b"PK"):
            raise ValueError("The run did not return an XLSX workbook")
        (output / "findings.json").write_text(
            json.dumps(findings, ensure_ascii=False, indent=2)
        )
        (output / "findings.xlsx").write_bytes(workbook)

    # Mark completion only after validating and storing all requested artifacts.
    temp = output / "timing.json.tmp"
    temp.write_text(json.dumps(timing))
    temp.replace(output / "timing.json")


def original(output: Path) -> None:
    from bench.e2e_v32_20261114.run import safe_manifest

    repo = Path(__file__).resolve().parents[1]
    request = client(8443)
    if request("/health")[1]["status"] != "ok":
        raise RuntimeError("The protected pilot is unavailable")
    (package,) = safe_manifest(repo / "bench/e2e_v32_20261114/case-manifest.json")
    files = [("report", repo / package["report"]["path"])]
    files.extend(("documents", repo / doc["path"]) for doc in package["documents"])
    scope = package["scope"]
    fields = {
        key: scope[key] for key in ("contract_number", "period_start", "period_end")
    }
    fields["report_row_locator"] = json.dumps(
        {
            "kind": "page",
            "page": 1,
            "fragment_id": f"kfz-stage-{scope['stage']}-{scope['year']}",
        }
    )
    run(request, files, fields, output)


if __name__ == "__main__":
    os.umask(0o077)
    original(Path(sys.argv[1]))
