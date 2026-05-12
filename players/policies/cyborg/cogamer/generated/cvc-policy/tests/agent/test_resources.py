"""Focused behavior tests for cvc.agent.resources helpers."""

from __future__ import annotations

import pytest

from cvc_policy.agent.resources import (
    absolute_position,
    attr_int,
    attr_str,
    has_role_gear,
    heart_batch_target,
    heart_cap_for_role,
    heart_supply_capacity,
    inventory_signature,
    needs_emergency_mining,
    phase_name,
    resource_priority,
    resource_total,
    retreat_threshold,
    role_vibe,
    should_batch_hearts,
    team_can_afford_gear,
    team_can_refill_hearts,
    team_id,
    team_min_resource,
)
from cvc_policy.agent.types import (
    ELEMENTS,
    _EMERGENCY_RESOURCE_LOW,
    GEAR_COSTS,
    _HEART_BATCH_TARGETS,
    HP_THRESHOLDS,
)


def _shared_inventory(resource_value: int = 10, *, heart: int = 5, **overrides: int) -> dict[str, int]:
    inventory = {resource: resource_value for resource in ELEMENTS}
    inventory["heart"] = heart
    inventory.update(overrides)
    return inventory


def _one_short(costs: dict[str, int]) -> dict[str, int]:
    inventory = dict(costs)
    first_resource = next(iter(inventory))
    inventory[first_resource] -= 1
    return inventory


@pytest.mark.parametrize(("global_x", "global_y"), [(10, 20), (0, 0), (999, 888)])
def test_absolute_position_variants(make_state, global_x: int, global_y: int) -> None:
    assert absolute_position(make_state(global_x=global_x, global_y=global_y)) == (global_x, global_y)


@pytest.mark.parametrize(
    ("attributes", "name", "default", "expected"),
    [
        ({"hp": 42}, "hp", 0, 42),
        ({}, "missing", 0, 0),
        ({}, "missing", 99, 99),
        ({"hp": 0}, "hp", 99, 0),
        ({"hp": "7"}, "hp", 0, 7),
    ],
)
def test_attr_int_handles_defaults_and_coercion(
    make_semantic_entity,
    attributes: dict[str, object],
    name: str,
    default: int,
    expected: int,
) -> None:
    assert attr_int(make_semantic_entity(**attributes), name, default) == expected


@pytest.mark.parametrize(
    ("attributes", "name", "expected"),
    [
        ({"team": "team_0"}, "team", "team_0"),
        ({}, "missing", None),
        ({"hp": 42}, "hp", "42"),
    ],
)
def test_attr_str_handles_missing_and_coercion(
    make_semantic_entity,
    attributes: dict[str, object],
    name: str,
    expected: str | None,
) -> None:
    assert attr_str(make_semantic_entity(**attributes), name) == expected


@pytest.mark.parametrize(
    ("inventory", "role", "expected"),
    [
        ({"aligner": 1}, "aligner", True),
        ({"miner": 3}, "miner", True),
        ({}, "aligner", False),
        ({"miner": 0}, "miner", False),
        ({"scrambler": 1}, "miner", False),
    ],
)
def test_has_role_gear_requires_positive_matching_inventory(
    make_state,
    inventory: dict[str, int],
    role: str,
    expected: bool,
) -> None:
    assert has_role_gear(make_state(inventory=inventory), role) is expected


@pytest.mark.parametrize(
    ("inventory", "expected"),
    [
        ({}, 0),
        ({"carbon": 3, "oxygen": 2, "germanium": 1, "silicon": 4}, 10),
        ({"carbon": 5}, 5),
        ({"carbon": 1, "heart": 99, "miner": 1}, 1),
    ],
)
def test_resource_total_counts_only_elements(make_state, inventory: dict[str, int], expected: int) -> None:
    assert resource_total(make_state(inventory=inventory)) == expected


@pytest.mark.parametrize(
    ("team", "team_summary", "expected"),
    [
        ("team_0", ..., "team_0"),
        ("team_1", ..., "team_1"),
        ("team_1", None, "team_1"),
        ("", None, ""),
    ],
)
def test_team_id_prefers_team_summary(make_state, team: str, team_summary: object, expected: str) -> None:
    assert team_id(make_state(team=team, team_summary=team_summary)) == expected


@pytest.mark.parametrize(
    ("state_kwargs", "expected"),
    [
        ({"shared_inventory": _shared_inventory(10)}, 10),
        ({"shared_inventory": _shared_inventory(10, germanium=2)}, 2),
        ({"shared_inventory": _shared_inventory(0)}, 0),
        ({"team_summary": None}, 0),
        ({"shared_inventory": _shared_inventory(100, oxygen=3, germanium=50, silicon=7)}, 3),
    ],
)
def test_team_min_resource_uses_lowest_shared_element(
    make_state,
    state_kwargs: dict[str, object],
    expected: int,
) -> None:
    assert team_min_resource(make_state(**state_kwargs)) == expected


@pytest.mark.parametrize(
    ("state_kwargs", "expected"),
    [
        ({"shared_inventory": _shared_inventory(10, carbon=0)}, True),
        ({"shared_inventory": _shared_inventory(_EMERGENCY_RESOURCE_LOW)}, False),
        ({}, False),
        ({"team_summary": None}, False),
        ({"shared_inventory": _shared_inventory(10, silicon=0)}, True),
    ],
)
def test_needs_emergency_mining_triggers_only_when_team_is_low(
    make_state,
    state_kwargs: dict[str, object],
    expected: bool,
) -> None:
    assert needs_emergency_mining(make_state(**state_kwargs)) is expected


@pytest.mark.parametrize(
    ("state_kwargs", "resource_bias", "expected"),
    [
        (
            {"shared_inventory": _shared_inventory(0, carbon=1, germanium=2, oxygen=3, silicon=4)},
            "carbon",
            ["carbon", "germanium", "oxygen", "silicon"],
        ),
        (
            {"shared_inventory": _shared_inventory(5)},
            "silicon",
            ["silicon", "carbon", "germanium", "oxygen"],
        ),
        (
            {"shared_inventory": _shared_inventory(5)},
            "nonexistent",
            sorted(ELEMENTS),
        ),
        (
            {"team_summary": None},
            "silicon",
            ["silicon", "carbon", "germanium", "oxygen"],
        ),
    ],
)
def test_resource_priority_orders_by_amount_then_bias_then_name(
    make_state,
    state_kwargs: dict[str, object],
    resource_bias: str,
    expected: list[str],
) -> None:
    assert resource_priority(make_state(**state_kwargs), resource_bias=resource_bias) == expected


def test_inventory_signature_returns_sorted_tuple_pairs(make_state) -> None:
    signature = inventory_signature(make_state(inventory={"carbon": 5, "silicon": 3}))
    assert signature == tuple(sorted(signature))
    assert isinstance(signature, tuple)
    assert dict(signature)["carbon"] == 5
    assert dict(signature)["silicon"] == 3


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("aligner", "change_vibe_aligner"),
        ("miner", "change_vibe_miner"),
        ("scrambler", "change_vibe_scrambler"),
        ("scout", "change_vibe_scout"),
        ("wizard", "change_vibe_default"),
        ("", "change_vibe_default"),
    ],
)
def test_role_vibe_variants(role: str, expected: str) -> None:
    assert role_vibe(role) == expected


@pytest.mark.parametrize(
    ("role", "step", "inventory", "expected"),
    [
        ("aligner", 100, {"aligner": 1}, HP_THRESHOLDS["aligner"]),
        ("miner", 100, {}, HP_THRESHOLDS["miner"] + 10),
        ("aligner", 3_000, {"aligner": 1}, HP_THRESHOLDS["aligner"] + 15),
        ("scrambler", 3_000, {"scrambler": 1}, HP_THRESHOLDS["scrambler"] + 15),
        ("miner", 3_000, {"miner": 1}, HP_THRESHOLDS["miner"] + 10),
        ("scout", 3_000, {"scout": 1}, HP_THRESHOLDS["scout"]),
        ("aligner", 2_500, {"aligner": 1}, HP_THRESHOLDS["aligner"] + 15),
        ("aligner", 3_000, {}, HP_THRESHOLDS["aligner"] + 25),
    ],
)
def test_retreat_threshold_cases(
    make_state,
    role: str,
    step: int,
    inventory: dict[str, int],
    expected: int,
) -> None:
    assert retreat_threshold(make_state(step=step, inventory=inventory), role) == expected


@pytest.mark.parametrize(
    ("state_kwargs", "role", "expected"),
    [
        ({"hp": 1}, "miner", "retreat"),
        ({"hp": 100}, "aligner", "regear"),
        ({"hp": 100, "shared_inventory": _shared_inventory(0, heart=0)}, "aligner", "fund_gear"),
        ({"hp": 100, "shared_inventory": _shared_inventory(0, heart=0)}, "miner", "regear"),
        ({"inventory": {"aligner": 1, "heart": 0}}, "aligner", "hearts"),
        ({"inventory": {"scrambler": 1, "heart": 0}}, "scrambler", "hearts"),
        ({"inventory": {"miner": 1, "heart": 0, "carbon": 0}}, "miner", "economy"),
        ({"inventory": {"aligner": 1, "heart": 1}}, "aligner", "expand"),
        ({"inventory": {"scrambler": 1, "heart": 1}}, "scrambler", "pressure"),
        # Miner is always "economy" while mining — the deposit decision lives
        # in _should_deposit_resources (pressure.py), not in phase_name.
        ({"inventory": {"miner": 1, "carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10}}, "miner", "economy"),
        ({"inventory": {"scout": 1}}, "scout", "explore"),
    ],
)
def test_phase_name_scenarios(
    make_state,
    state_kwargs: dict[str, object],
    role: str,
    expected: str,
) -> None:
    assert phase_name(make_state(**state_kwargs), role) == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("aligner", _HEART_BATCH_TARGETS["aligner"]),
        ("scrambler", _HEART_BATCH_TARGETS["scrambler"]),
        ("miner", 0),
        ("scout", 0),
        ("wizard", 0),
    ],
)
def test_heart_batch_target_variants(make_state, role: str, expected: int) -> None:
    assert heart_batch_target(make_state(), role) == expected


@pytest.mark.parametrize("role", list(GEAR_COSTS))
def test_team_can_afford_gear_with_abundant_resources(make_state, role: str) -> None:
    assert team_can_afford_gear(make_state(shared_inventory=_shared_inventory(20)), role) is True


@pytest.mark.parametrize("role", list(GEAR_COSTS))
def test_team_cannot_afford_gear_with_zero_resources(make_state, role: str) -> None:
    assert team_can_afford_gear(make_state(shared_inventory=_shared_inventory(0, heart=0)), role) is False


@pytest.mark.parametrize(
    ("state_kwargs", "role", "expected"),
    [
        ({"shared_inventory": dict(GEAR_COSTS["aligner"])}, "aligner", True),
        ({"shared_inventory": _one_short(GEAR_COSTS["aligner"])}, "aligner", False),
        ({"team_summary": None}, "aligner", False),
        ({}, "wizard", True),
    ],
)
def test_team_can_afford_gear_edge_cases(
    make_state,
    state_kwargs: dict[str, object],
    role: str,
    expected: bool,
) -> None:
    assert team_can_afford_gear(make_state(**state_kwargs), role) is expected


@pytest.mark.parametrize(
    ("state_kwargs", "expected"),
    [
        ({"shared_inventory": _shared_inventory(10, heart=1)}, True),
        ({"shared_inventory": _shared_inventory(10, heart=10)}, True),
        ({"shared_inventory": _shared_inventory(7, heart=0)}, True),
        ({"shared_inventory": _shared_inventory(7, heart=0, carbon=6)}, False),
        ({"shared_inventory": _shared_inventory(0, heart=0)}, False),
        ({"team_summary": None}, False),
    ],
)
def test_team_can_refill_hearts_cases(make_state, state_kwargs: dict[str, object], expected: bool) -> None:
    assert team_can_refill_hearts(make_state(**state_kwargs)) is expected


@pytest.mark.parametrize(
    ("state_kwargs", "expected"),
    [
        ({"shared_inventory": _shared_inventory(14, heart=3)}, 5),
        ({"shared_inventory": _shared_inventory(21, heart=0)}, 3),
        ({"shared_inventory": _shared_inventory(0, heart=5)}, 5),
        ({"shared_inventory": _shared_inventory(100, heart=0, silicon=7)}, 1),
        ({"team_summary": None}, 0),
    ],
)
def test_heart_supply_capacity_cases(make_state, state_kwargs: dict[str, object], expected: int) -> None:
    assert heart_supply_capacity(make_state(**state_kwargs)) == expected


@pytest.mark.parametrize(
    ("state_kwargs", "role", "hub_position", "expected"),
    [
        ({"inventory": {"heart": 1}}, "aligner", None, False),
        ({"inventory": {"heart": 0}}, "aligner", (44, 44), False),
        ({"inventory": {"aligner": 1, "heart": _HEART_BATCH_TARGETS["aligner"]}}, "aligner", (44, 44), False),
        ({"inventory": {"aligner": 1, "heart": _HEART_BATCH_TARGETS["aligner"] + 5}}, "aligner", (44, 44), False),
        ({"inventory": {"aligner": 1, "heart": 1}}, "aligner", (50, 50), False),
        (
            {
                "inventory": {"aligner": 1, "heart": 1},
                "shared_inventory": _shared_inventory(0, heart=0),
            },
            "aligner",
            (44, 44),
            False,
        ),
        (
            {
                "inventory": {"aligner": 1, "heart": 1},
                "shared_inventory": _shared_inventory(10, heart=5),
            },
            "aligner",
            (44, 44),
            True,
        ),
        (
            {
                "inventory": {"aligner": 1, "heart": 1},
                "global_y": 45,
                "shared_inventory": _shared_inventory(10, heart=5),
            },
            "aligner",
            (44, 44),
            True,
        ),
        (
            {
                "inventory": {"aligner": 1, "heart": 1},
                "global_y": 46,
                "shared_inventory": _shared_inventory(10, heart=5),
            },
            "aligner",
            (44, 44),
            False,
        ),
        ({"inventory": {"miner": 1, "heart": 1}}, "miner", (44, 44), False),
    ],
)
def test_should_batch_hearts_cases(
    make_state,
    state_kwargs: dict[str, object],
    role: str,
    hub_position: tuple[int, int] | None,
    expected: bool,
) -> None:
    assert should_batch_hearts(make_state(**state_kwargs), role=role, hub_position=hub_position) is expected


# ---------------------------------------------------------------------------
# heart_cap_for_role: prefer discovered cap over the static default.
# ---------------------------------------------------------------------------


def test_heart_cap_for_role_uses_known_cap_when_present() -> None:
    assert heart_cap_for_role("aligner", known_cap=5) == 5
    assert heart_cap_for_role("scrambler", known_cap=4) == 4


def test_heart_cap_for_role_falls_back_to_default_when_unknown() -> None:
    assert heart_cap_for_role("aligner", known_cap=None) == 3
    assert heart_cap_for_role("scrambler", known_cap=None) == 2


def test_heart_cap_for_role_unknown_role_returns_zero_without_cap() -> None:
    assert heart_cap_for_role("miner", known_cap=None) == 0
    # Known cap still wins for roles without a default.
    assert heart_cap_for_role("miner", known_cap=7) == 7