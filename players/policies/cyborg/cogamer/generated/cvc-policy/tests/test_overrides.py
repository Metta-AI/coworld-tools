"""Tests for the KEY=VALUE overrides parser."""

from __future__ import annotations

import pytest

from cvc_policy.overrides import parse_override, parse_variant_override


def test_parse_override_int() -> None:
    assert parse_override("num_agents=4") == ("num_agents", 4)


def test_parse_override_float() -> None:
    assert parse_override("ratio=0.5") == ("ratio", 0.5)


def test_parse_override_bool_true() -> None:
    assert parse_override("enabled=true") == ("enabled", True)


def test_parse_override_bool_false() -> None:
    assert parse_override("enabled=false") == ("enabled", False)


def test_parse_override_json_object() -> None:
    assert parse_override('config={"k":1}') == ("config", {"k": 1})


def test_parse_override_string_fallback() -> None:
    assert parse_override("name=foo") == ("name", "foo")


def test_parse_override_dashes_to_underscores() -> None:
    assert parse_override("num-agents=4") == ("num_agents", 4)


def test_parse_override_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_override("no_equals_sign")


def test_parse_override_negative_int() -> None:
    assert parse_override("offset=-3") == ("offset", -3)


def test_parse_variant_override_int() -> None:
    assert parse_variant_override("cargo_limit.limit=8") == ("cargo_limit", "limit", 8)


def test_parse_variant_override_dashes() -> None:
    assert parse_variant_override("cargo-limit.some-key=true") == (
        "cargo_limit",
        "some_key",
        True,
    )


def test_parse_variant_override_rejects_missing_dot() -> None:
    with pytest.raises(ValueError):
        parse_variant_override("no_dot=1")
