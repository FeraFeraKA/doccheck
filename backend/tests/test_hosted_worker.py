from hashlib import sha256
from http.client import IncompleteRead
from io import BytesIO
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from doccheck_backend.hosted_worker import HostedClient, _TransientDownloadError, main


def test_retries_truncated_or_unavailable_original(monkeypatch):
    monkeypatch.setattr("doccheck_backend.hosted_worker.time.sleep", lambda seconds: None)
    client = HostedClient("http://127.0.0.1:1234", "t" * 32)
    events = iter([HTTPError("", 503, "", {}, None), BytesIO(b"abc"), BytesIO(b"complete")])

    def request(*args, **kwargs):
        response = next(events)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "request", request)
    assert client._download_payload(uuid4(), "f" * 32, 8) == b"complete"


def test_exhausted_retry_leaves_lease_instead_of_writing_terminal_failure(monkeypatch):
    monkeypatch.setattr("doccheck_backend.hosted_worker.time.sleep", lambda seconds: None)
    client = HostedClient("http://127.0.0.1:1234", "t" * 32)
    claim = {
        "lease_id": str(uuid4()),
        "run_id": str(uuid4()),
        "documents": [
            {"id": "f" * 32, "size": 8, "sha256": sha256(b"complete").hexdigest()},
            {"id": "a" * 32, "size": 8, "sha256": sha256(b"complete").hexdigest()},
        ],
    }
    monkeypatch.setattr(client, "claim", lambda: claim)
    methods = []

    def request(method, *args, **kwargs):
        methods.append(method)
        return BytesIO(b"short")

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(_TransientDownloadError):
        client.process_one(lambda run, folder: pytest.fail("No complete original"))
    assert methods == ["GET", "GET", "GET"]


@pytest.mark.parametrize("once", [False, True])
def test_truncated_claim_response_preserves_polling_boundary(monkeypatch, once):
    args = ["hosted_worker", "--origin", "http://127.0.0.1:1234", "--processor", "test:process"]
    if once:
        args.append("--once")
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.setenv("DOCCHECK_HOSTED_WORKER_TOKEN", "t" * 32)
    monkeypatch.setattr("doccheck_backend.hosted_worker.import_module", lambda name: FakeModule)
    methods = []
    pauses = []
    monkeypatch.setattr("doccheck_backend.hosted_worker.time.sleep", pauses.append)

    class TruncatedResponse(BytesIO):
        status = 200

        def read(self, *_):
            raise IncompleteRead(b'{"lease_id":')

    def request(_client, method, path, **_kwargs):
        methods.append((method, path))
        if len(methods) == 1:
            return TruncatedResponse()
        # Stop the loop on the second iteration without processing any claims.
        raise HTTPError("", 401, "", {}, None)

    monkeypatch.setattr(HostedClient, "request", request)
    assert main() == 1
    assert methods == [("POST", "/claims")] * (1 if once else 2)
    assert pauses == ([] if once else [3])


class FakeModule:
    @staticmethod
    def process(*_args):
        pytest.fail("Incomplete claim must not reach the processor")
