"""Tests for BundleReader and BundleInnerManifest.

Builds bundle zips in-memory and round-trips them through the reader.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from reporter_sdk import BundleInnerManifest, BundleReader


def _build_bundle(
    *,
    ereq_id: str = "ereq_test",
    status: str = "success",
    include: list[str] | None = None,
    files: dict[str, str] | None = None,
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    include = include if include is not None else ["results"]
    files = files if files is not None else {"results": "results.json"}
    manifest = {
        "ereq_id": ereq_id,
        "status": status,
        "include": include,
        "files": files,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for path, payload in (extra_entries or {}).items():
            zf.writestr(path, payload)
    return buf.getvalue()


def test_inner_manifest_parses_with_defaults() -> None:
    raw = {"ereq_id": "ereq_001"}
    m = BundleInnerManifest.model_validate(raw)
    assert m.ereq_id == "ereq_001"
    assert m.status == "success"
    assert m.include == []
    assert m.files == {}


def test_inner_manifest_allows_extra_fields() -> None:
    """Forward-compat: an ``episode_id`` carrier the bundler may add should
    not trip validation."""
    m = BundleInnerManifest.model_validate(
        {
            "ereq_id": "x",
            "episode_id": "ep_abc",  # not in the declared schema
        }
    )
    assert m.ereq_id == "x"


def test_bundle_reader_reads_required_token(tmp_path: Path) -> None:
    payload = _build_bundle(
        include=["results"],
        files={"results": "results.json"},
        extra_entries={"results.json": b'{"score": 7}'},
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(payload)
    with BundleReader(bundle_path.as_uri()) as br:
        assert br.read_json("results") == {"score": 7}
        assert br.inner_manifest().ereq_id == "ereq_test"


def test_bundle_reader_optional_returns_none_when_token_not_in_include(
    tmp_path: Path,
) -> None:
    """A token listed in ``files`` but absent from ``include`` is treated
    as filtered out — :meth:`read_*_optional` returns ``None``."""
    payload = _build_bundle(
        include=["results"],  # metadata not in include
        files={"results": "results.json", "metadata": "metadata.json"},
        extra_entries={
            "results.json": b"{}",
            "metadata.json": b'{"k": 1}',
        },
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(payload)
    with BundleReader(bundle_path.as_uri()) as br:
        assert br.read_json_optional("metadata") is None
        assert br.read_bytes_optional("metadata") is None


def test_bundle_reader_missing_token_raises(tmp_path: Path) -> None:
    payload = _build_bundle(
        include=["results"],
        files={"results": "results.json"},
        extra_entries={"results.json": b"{}"},
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(payload)
    with BundleReader(bundle_path.as_uri()) as br, pytest.raises(KeyError):
        br.read_json("nonexistent")


def test_bundle_reader_multi_file_token_raises(tmp_path: Path) -> None:
    """``files[token]`` being a dict (multi-file tokens like ``game_logs``)
    surfaces as ``TypeError``."""
    payload = _build_bundle(
        include=["game_logs"],
        files={"game_logs": {"slot_0": "logs/slot_0.txt"}},  # type: ignore[dict-item]
        extra_entries={"logs/slot_0.txt": b"hello"},
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(payload)
    with BundleReader(bundle_path.as_uri()) as br, pytest.raises(TypeError):
        br.read_bytes("game_logs")


def test_bundle_reader_read_bytes_for_binary_token(tmp_path: Path) -> None:
    """Binary tokens (e.g. Among Them's ``.bitreplay``) are read via
    :meth:`read_bytes`, which doesn't try to JSON-decode the payload."""
    binary = b"\x00\x01\x02BITWORLD"
    payload = _build_bundle(
        include=["replay"],
        files={"replay": "replay.bin"},
        extra_entries={"replay.bin": binary},
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(payload)
    with BundleReader(bundle_path.as_uri()) as br:
        assert br.read_bytes("replay") == binary
