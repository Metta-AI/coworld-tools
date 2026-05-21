"""Among Them summarizer reporter.

Phase 1 (skeleton) only: loads its env-supplied URIs and writes a valid
D12 zip containing a single empty `render.txt`. Reads no input bytes
yet — the binary `.bitreplay` parser and the results / metadata
consumption land in later phases.

See DESIGN.md (this directory) for the full specification and phase
plan. The inline primitives in this file (`ReporterInputs`,
`read_uri` / `write_uri`, `write_deterministic_zip`) are the same
SDK-extraction candidates currently inlined in
`paint_arena_summarizer.py`; they are kept inline here until a second
concrete reporter exists and the `reporter_sdk` extraction pass picks
them up.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

# ---------- inline primitives (SDK extraction candidates) ----------


class ReporterInputs(BaseModel):
    results_uri: str
    replay_uri: str
    episode_metadata_uri: str
    report_output_uri: str
    reporter_id: str


def load_reporter_inputs() -> ReporterInputs:
    return ReporterInputs(
        results_uri=os.environ["COGAME_RESULTS_URI"],
        replay_uri=os.environ["COGAME_REPLAY_URI"],
        episode_metadata_uri=os.environ["COGAME_EPISODE_METADATA_URI"],
        report_output_uri=os.environ["COGAME_REPORT_OUTPUT_URI"],
        reporter_id=os.environ["COGAME_REPORTER_ID"],
    )


_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
_HTTP_MAX_ATTEMPTS = 5


def _file_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def read_uri(uri: str) -> bytes:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        return _file_path_from_uri(uri).read_bytes()
    if scheme in ("http", "https"):
        return _http_request_with_retry("GET", uri).content
    raise ValueError(f"unsupported URI scheme {scheme!r} for read: {uri}")


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        path = _file_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    if scheme in ("http", "https"):
        _http_request_with_retry(
            "PUT", uri, data=payload, headers={"Content-Type": content_type}
        )
        return
    raise ValueError(f"unsupported URI scheme {scheme!r} for write: {uri}")


def _http_request_with_retry(
    method: str,
    uri: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    delay = 0.5
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        resp = requests.request(method, uri, data=data, headers=headers, timeout=30)
        if resp.status_code < 400:
            return resp
        if (
            resp.status_code not in _HTTP_RETRY_STATUSES
            or attempt == _HTTP_MAX_ATTEMPTS
        ):
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")  # loop above either returns or raises


def read_json(uri: str) -> Any:
    return json.loads(read_uri(uri).decode("utf-8"))


# Pinned zip-entry mtime for byte-identical determinism (D12). Anything other
# than a fixed value would make reruns over identical inputs differ in the
# zip's local-file headers.
_DETERMINISTIC_ZIP_MTIME = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a zip with pinned mtimes for byte-identical reruns (D12).

    Entry order is preserved as given. Each entry's date_time is pinned to
    _DETERMINISTIC_ZIP_MTIME so two invocations over identical inputs produce
    byte-identical output.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=_DETERMINISTIC_ZIP_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buf.getvalue()


# ---------- zip assembly (phase 1: render.txt only) ----------


def build_zip_bytes() -> bytes:
    """Phase 1: emit only an empty `render.txt`.

    Per D12 an empty `render.txt` (or its absence) is a valid output
    signalling "ran successfully, nothing inline to render." The
    reporter contract is satisfied; later phases will add
    `summary.html`, `stats.json`, and `events.parquet`.
    """
    return write_deterministic_zip([("render.txt", b"")])


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    payload = build_zip_bytes()
    write_uri(inputs.report_output_uri, payload, content_type="application/zip")
    print(
        f"[{inputs.reporter_id}] wrote zip to {inputs.report_output_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
