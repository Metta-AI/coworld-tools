"""Tests for write_deterministic_zip and stable_json."""

from __future__ import annotations

import io
import zipfile

from reporter_sdk import MTIME_SENTINEL, stable_json, write_deterministic_zip


def test_pinned_mtime_on_every_entry() -> None:
    payload = write_deterministic_zip([("a.txt", b"hello"), ("b/c.txt", b"world")])
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            assert info.date_time == MTIME_SENTINEL


def test_byte_identical_across_calls() -> None:
    entries = [("a.txt", b"x"), ("b.txt", b"y")]
    assert write_deterministic_zip(entries) == write_deterministic_zip(entries)


def test_entry_order_preserved() -> None:
    payload = write_deterministic_zip(
        [("z.txt", b"z"), ("a.txt", b"a"), ("m.txt", b"m")]
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert [i.filename for i in zf.infolist()] == ["z.txt", "a.txt", "m.txt"]


def test_stable_json_sorts_keys_and_compacts() -> None:
    assert stable_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_stable_json_byte_identical_across_dict_orderings() -> None:
    a = {"x": 1, "y": 2, "z": 3}
    b = {"z": 3, "x": 1, "y": 2}
    assert stable_json(a) == stable_json(b)
