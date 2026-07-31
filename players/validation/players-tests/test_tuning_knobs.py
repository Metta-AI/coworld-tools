"""Tests for players.player_sdk.tuning.knobs.

Ported 1:1 from the embedded smoke test of the original ``swgy_knobs.py``
(sm-policies scripted stack) — the numbered scenarios there map onto the
functions below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pytest

from players.player_sdk.tuning import (
    KnobCoercionError,
    Knobs,
    RoleKnob,
    UnknownKnobError,
    build,
    by_role,
    parse_role_knob,
    split_prefixed,
)


@dataclass(frozen=True)
class Demo(Knobs):
    threshold: int = 10
    weight: float = 1.5
    enabled: bool = True
    falloff: Literal["linear", "inverse_square", "step"] = "linear"
    ttl: int | None = None
    weights: tuple[float, ...] = ()
    tags: frozenset[int] = frozenset()
    hp_buffer_miner: int = 10
    hp_buffer_aligner: int = 12
    hp_buffer_scout: int = 5


def test_basic_string_coercion_across_types():
    cfg = Demo.from_kwargs(
        {
            "threshold": "42",
            "weight": "3.14",
            "enabled": "false",
            "falloff": "inverse_square",
            "ttl": "100",
            "weights": "7,6,5,4,3",
            "tags": "1,2,3",
        }
    )
    assert cfg.threshold == 42
    assert cfg.weight == 3.14
    assert cfg.enabled is False
    assert cfg.falloff == "inverse_square"
    assert cfg.ttl == 100
    assert cfg.weights == (7.0, 6.0, 5.0, 4.0, 3.0)
    assert cfg.tags == frozenset({1, 2, 3})


def test_optional_none_strings():
    assert Demo.from_kwargs({"ttl": "none"}).ttl is None
    assert Demo.from_kwargs({"ttl": ""}).ttl is None
    assert Demo.from_kwargs({"ttl": "NULL"}).ttl is None
    assert Demo.from_kwargs({"ttl": "200"}).ttl == 200


def test_bool_typo_rejected():
    with pytest.raises(KnobCoercionError):
        Demo.from_kwargs({"enabled": "maybe"})


def test_literal_validation_rejected():
    with pytest.raises(KnobCoercionError, match="exponential"):
        Demo.from_kwargs({"falloff": "exponential"})


def test_unknown_kwargs_warn_by_default(capsys):
    cfg = Demo.from_kwargs({"threshold": "1", "made_up_knob": "9"}, log_prefix="[demo] ")
    assert cfg.threshold == 1
    err = capsys.readouterr().err
    assert "made_up_knob" in err
    assert "[demo] " in err


def test_unknown_kwargs_raise():
    with pytest.raises(UnknownKnobError):
        Demo.from_kwargs({"made_up_knob": "9"}, on_unknown="raise")


def test_unknown_kwargs_ignore_is_silent(capsys):
    cfg = Demo.from_kwargs({"made_up_knob": "9"}, on_unknown="ignore")
    assert cfg == Demo()
    assert capsys.readouterr().err == ""


def test_layering_kwargs_on_base():
    base = Demo(threshold=99, weight=2.0, enabled=False)
    cfg = build(Demo, {"weight": "5.5"}, base=base)
    assert cfg.threshold == 99
    assert cfg.weight == 5.5
    assert cfg.enabled is False


def test_empty_kwargs_return_base_or_defaults():
    base = Demo(threshold=99)
    assert build(Demo, {}, base=base) is base
    assert build(Demo, None, base=base) is base
    assert build(Demo) == Demo()


def test_split_prefixed_routes_nested_config_kwargs():
    matched, rest = split_prefixed({"nav__a": "1", "nav__b": "2", "phase": "51"}, "nav__")
    assert matched == {"a": "1", "b": "2"}
    assert rest == {"phase": "51"}


def test_by_role_hit_and_miss():
    cfg = Demo()
    assert by_role(cfg, "hp_buffer", "miner") == 10
    assert by_role(cfg, "hp_buffer", "aligner") == 12
    with pytest.raises(AttributeError) as exc_info:
        by_role(cfg, "hp_buffer", "scrambler")
    # The error message lists the valid suffixes.
    assert "miner" in str(exc_info.value) and "aligner" in str(exc_info.value)
    assert by_role(cfg, "hp_buffer", "scrambler", default=99) == 99


def test_to_dict_and_diff_from_defaults():
    cfg = Demo.from_kwargs(
        {"threshold": "42", "enabled": "false", "ttl": "100", "weights": "7,6", "tags": "1,2,3"}
    )
    full = cfg.to_dict()
    assert full["threshold"] == 42
    assert full["enabled"] is False
    assert full["tags"] == frozenset({1, 2, 3})
    diff = cfg.diff_from_defaults()
    assert diff["threshold"] == 42
    assert "hp_buffer_miner" not in diff  # equals default → not in diff
    assert "weights" in diff  # changed from () → in diff
    assert diff["ttl"] == 100  # changed from default None
    assert "ttl" not in Demo(threshold=1).diff_from_defaults()


def test_with_overrides_preserves_untouched_fields():
    cfg = Demo.from_kwargs({"threshold": "42", "tags": "1,2,3"})
    cfg2 = cfg.with_overrides(threshold=999)
    assert cfg2.threshold == 999
    assert cfg2.weight == cfg.weight
    assert cfg2.tags == cfg.tags


def test_round_trip_to_dict_then_build():
    cfg = Demo.from_kwargs({"threshold": "42", "weights": "7,6,5", "ttl": "100"})
    rebuilt = build(Demo, cfg.to_dict())
    assert rebuilt == cfg


def test_build_on_plain_non_knobs_dataclass():
    @dataclass(frozen=True)
    class Plain:
        a: int = 1
        b: str = "hi"

    p = build(Plain, {"a": "5"})
    assert p.a == 5 and p.b == "hi"


def test_idiomatic_split_then_build_pattern():
    raw_kwargs = {
        "threshold": "77",
        "nav__teammate_spacing": "3",
        "nav__heuristic_mode": "manhattan",
    }
    nav_kwargs, leftover = split_prefixed(raw_kwargs, "nav__")
    assert nav_kwargs == {"teammate_spacing": "3", "heuristic_mode": "manhattan"}
    main_cfg = Demo.from_kwargs(leftover)
    assert main_cfg.threshold == 77


def test_role_knob_for_role_default_fallback():
    rk: RoleKnob[int] = RoleKnob(default=5, by_role={"scrambler": 1})
    assert rk.for_role("scrambler") == 1
    assert rk.for_role("aligner") == 5
    assert rk.for_role(None) == 5


def test_role_knob_from_dict_forms():
    rk = RoleKnob.from_dict({"default": 5, "by_role": {"scrambler": 1, "aligner": 4}})
    assert rk.default == 5 and rk.by_role == {"scrambler": 1, "aligner": 4}
    rk = RoleKnob.from_dict(7)  # bare scalar wraps to default
    assert rk.default == 7 and rk.by_role == {}
    with pytest.raises(KnobCoercionError):
        RoleKnob.from_dict({"aligner": 5})  # missing 'default' key is ambiguous


def test_parse_role_knob_bare_flat_key():
    kw = {"heart_topup_target": "5"}
    rk = parse_role_knob(kw, "heart_topup_target", default=1, type_=int)
    assert rk.default == 5 and rk.by_role == {} and kw == {}


def test_parse_role_knob_bare_and_suffixed_compose():
    kw = {
        "heart_topup_target": "5",
        "heart_topup_target__scrambler": "1",
        "heart_topup_target__aligner": "4",
        "unrelated": "x",
    }
    rk = parse_role_knob(kw, "heart_topup_target", default=99, type_=int)
    assert rk.default == 5
    assert rk.by_role == {"scrambler": 1, "aligner": 4}
    assert kw == {"unrelated": "x"}


def test_parse_role_knob_suffixed_only_falls_back_to_default():
    kw = {"heart_topup_target__scrambler": "1"}
    rk = parse_role_knob(kw, "heart_topup_target", default=5, type_=int)
    assert rk.default == 5 and rk.by_role == {"scrambler": 1}
    assert kw == {}


def test_parse_role_knob_nested_dict_form():
    kw = {"heart_topup_target": {"default": 5, "by_role": {"scrambler": 1}}}
    rk = parse_role_knob(kw, "heart_topup_target", default=99, type_=int)
    assert rk.default == 5 and rk.by_role == {"scrambler": 1}
    assert kw == {}


def test_parse_role_knob_consume_false_leaves_kwargs():
    kw = {"heart_topup_target": "5", "heart_topup_target__scrambler": "1"}
    rk = parse_role_knob(kw, "heart_topup_target", default=1, type_=int, consume=False)
    assert rk.default == 5 and rk.by_role == {"scrambler": 1}
    assert kw == {"heart_topup_target": "5", "heart_topup_target__scrambler": "1"}


def test_parse_role_knob_type_none_passthrough():
    kw = {"foo": "raw_string"}
    rk = parse_role_knob(kw, "foo", default="default_string")
    assert rk.default == "raw_string"
