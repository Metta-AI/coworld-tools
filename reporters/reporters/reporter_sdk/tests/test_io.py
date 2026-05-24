"""Tests for env-var URI accessors and the URI I/O surface.

Covers the public ``ReporterInputs`` / ``load_reporter_inputs`` accessors
and the ``read_uri`` / ``write_uri`` HTTP retry contract. The HTTP tests
patch the real ``requests`` module so they don't touch the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from reporter_sdk import io as sdk_io
from reporter_sdk import (
    ReporterInputs,
    load_reporter_inputs,
    read_json,
    read_uri,
    write_uri,
)


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)  # type: ignore[arg-type]


def _install_request_stub(
    monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    iterator = iter(responses)

    def fake_request(method: str, url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"method": method, "url": url, **kwargs})
        return next(iterator)

    monkeypatch.setattr(sdk_io.requests, "request", fake_request)
    monkeypatch.setattr(sdk_io.time, "sleep", lambda _seconds: None)
    return calls


# ---------- env vars ----------


def test_load_reporter_inputs_reads_both_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", "file:///tmp/bundle.zip")
    monkeypatch.setenv("COGAME_REPORT_URI", "file:///tmp/out.zip")
    inputs = load_reporter_inputs()
    assert isinstance(inputs, ReporterInputs)
    assert inputs.episode_bundle_uri == "file:///tmp/bundle.zip"
    assert inputs.report_uri == "file:///tmp/out.zip"


def test_load_reporter_inputs_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in ("COGAME_EPISODE_BUNDLE_URI", "COGAME_REPORT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        load_reporter_inputs()


# ---------- file:// I/O ----------


def test_read_uri_file_scheme(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    assert read_uri(p.as_uri()) == b"hello"


def test_write_uri_file_scheme_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.bin"
    write_uri(target.as_uri(), b"payload", content_type="application/octet-stream")
    assert target.read_bytes() == b"payload"


def test_read_json_file_scheme(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"k": 1}')
    assert read_json(p.as_uri()) == {"k": 1}


# ---------- HTTP retry policy ----------


def test_read_uri_http_success_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(200, b"hello")])
    assert read_uri("https://example.test/path") == b"hello"
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"


@pytest.mark.parametrize("transient_status", [429, 500, 502, 503, 504])
def test_read_uri_retries_on_transient_status(
    monkeypatch: pytest.MonkeyPatch, transient_status: int
) -> None:
    calls = _install_request_stub(
        monkeypatch,
        [
            FakeResponse(transient_status),
            FakeResponse(transient_status),
            FakeResponse(200, b"ok"),
        ],
    )
    assert read_uri("https://example.test/path") == b"ok"
    assert len(calls) == 3


def test_read_uri_no_retry_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(404)])
    with pytest.raises(requests.HTTPError):
        read_uri("https://example.test/path")
    assert len(calls) == 1


def test_read_uri_retries_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(
        monkeypatch,
        [FakeResponse(503) for _ in range(sdk_io._HTTP_MAX_ATTEMPTS)],
    )
    with pytest.raises(requests.HTTPError):
        read_uri("https://example.test/path")
    assert len(calls) == sdk_io._HTTP_MAX_ATTEMPTS


def test_write_uri_http_put_sends_payload_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(200)])
    write_uri(
        "https://example.test/upload",
        b'{"ok": true}',
        content_type="application/json",
    )
    assert calls[0]["method"] == "PUT"
    assert calls[0]["data"] == b'{"ok": true}'
    assert calls[0]["headers"] == {"Content-Type": "application/json"}


def test_backoff_grows_exponentially_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleep delays follow 0.5, 1.0, 2.0, 4.0 between the 5 attempts (capped at 8)."""
    sleeps: list[float] = []
    monkeypatch.setattr(sdk_io.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        sdk_io.requests,
        "request",
        lambda *a, **kw: FakeResponse(503),
    )
    with pytest.raises(requests.HTTPError):
        read_uri("https://example.test/path")
    assert sleeps == [0.5, 1.0, 2.0, 4.0]


def test_unsupported_scheme_read_raises() -> None:
    with pytest.raises(ValueError, match="unsupported URI scheme"):
        read_uri("ftp://example.test/x")


def test_unsupported_scheme_write_raises() -> None:
    with pytest.raises(ValueError, match="unsupported URI scheme"):
        write_uri("ftp://example.test/x", b"x", content_type="text/plain")
