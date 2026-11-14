from hashlib import sha256
from io import BytesIO
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from doccheck_backend.hosted_worker import HostedClient, _TransientDownloadError


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
