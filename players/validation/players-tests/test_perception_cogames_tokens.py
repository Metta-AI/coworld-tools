"""Scenario tests for players.player_sdk.perception.cogames_tokens.

Ported 1:1 from the embedded smoke test of the original
``swgy_perception.py`` (sm-policies scripted stack) — which already drove
the parser through hand-rolled mock tokens, i.e. exactly the duck-typed
surface the module now declares as Protocols. A structural-conformance
test is added at the end.
"""

from __future__ import annotations

from players.player_sdk.perception.cogames_tokens import (
    Coordinate,
    ObservationLike,
    Perception,
    TagIndex,
    parse_observation,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    assert cond, f"FAIL {label}: {detail}"


# Minimal mock token stream. We only need feature.name,
# feature.normalization, location, value.
class _Feat:
    def __init__(self, name: str, normalization: float = 1.0):
        self.name = name
        self.normalization = normalization


class _Tok:
    def __init__(self, feature, location, value):
        self.feature = feature
        self.location = location
        self.value = value


class _Obs:
    def __init__(self, tokens):
        self.tokens = tokens


CENTER: Coordinate = (5, 5)
TEAM_TAG_IDS = frozenset({7, 8})  # team:cogs / team:clips style ids


def test_tags_accumulate_per_location() -> None:
    # 1. Tags accumulate per location.
    obs = _Obs([
        _Tok(_Feat("tag"), (5, 5), 7),       # own team tag at center
        _Tok(_Feat("tag"), (5, 5), 12),      # type:agent at center
        _Tok(_Feat("tag"), (3, 4), 7),       # teammate elsewhere
        _Tok(_Feat("tag"), None, 99),        # global tag => skipped
    ])
    p = parse_observation(obs, CENTER, TEAM_TAG_IDS)
    check(
        "1 tags by location",
        p.tags_by_location.get((5, 5)) == {7, 12} and p.tags_by_location.get((3, 4)) == {7},
    )
    check("1b own team tag", p.own_team_tag_ids == frozenset({7}))


def test_inventory_powered_reconstruction() -> None:
    # 2. Inventory at center, with powered reconstruction.
    # base inv:carbon=10 at center, plus inv:carbon:p1=2 with norm=255
    # -> total = 10 + 2*255 = 520.
    obs = _Obs([
        _Tok(_Feat("inv:carbon"), CENTER, 10),
        _Tok(_Feat("inv:carbon:p1", normalization=255.0), CENTER, 2),
        _Tok(_Feat("inv:oxygen"), (0, 0), 5),  # not center => ignored
    ])
    p = parse_observation(obs, CENTER, TEAM_TAG_IDS)
    check("2 inventory powered", p.inventory.get("carbon") == 520, f"got {p.inventory}")
    check("2b non-center inv ignored", "oxygen" not in p.inventory)
    # 10. Powered without :p suffix uses scale=1.
    p = parse_observation(_Obs([_Tok(_Feat("inv:heart"), CENTER, 7)]), CENTER, TEAM_TAG_IDS)
    check("10 unpowered inv", p.inventory.get("heart") == 7)


def test_team_resources_are_global() -> None:
    # 3. Team resources are global (location None).
    obs = _Obs([
        _Tok(_Feat("team:carbon"), None, 30),
        _Tok(_Feat("team:carbon:p1", normalization=255.0), None, 1),
        _Tok(_Feat("team:silicon"), (3, 3), 50),  # location => ignored
    ])
    p = parse_observation(obs, CENTER, TEAM_TAG_IDS)
    check("3 team_resources powered", p.team_resources.get("carbon") == 30 + 255)
    check("3b non-global team ignored", "silicon" not in p.team_resources)


def test_aoe_mask_semantics() -> None:
    # 4. AOE mask at center value 1 => in_friendly_aoe.
    obs = _Obs([
        _Tok(_Feat("aoe_mask"), CENTER, 1),
        _Tok(_Feat("aoe_mask"), (0, 0), 2),
        _Tok(_Feat("aoe_mask"), None, 1),  # global => ignored
    ])
    p = parse_observation(obs, CENTER, TEAM_TAG_IDS)
    check("4 in_friendly_aoe", p.in_friendly_aoe and p.aoe_by_location.get(CENTER) == 1)
    check("4b aoe other cells", p.aoe_by_location.get((0, 0)) == 2)
    # 5. AOE mask at center value 2 => NOT in_friendly_aoe (only 1 counts).
    p = parse_observation(_Obs([_Tok(_Feat("aoe_mask"), CENTER, 2)]), CENTER, TEAM_TAG_IDS)
    check("5 friendly aoe requires value 1", not p.in_friendly_aoe)


def test_global_scalar_features() -> None:
    # 6. last_action_move is GLOBAL (location is None).
    p = parse_observation(
        _Obs([_Tok(_Feat("last_action_move"), None, 1)]), CENTER, TEAM_TAG_IDS
    )
    check("6 move token global", p.has_move_token and p.move_succeeded)
    # 7. last_reward / episode_completion_pct globals.
    obs = _Obs([
        _Tok(_Feat("last_reward", normalization=10.0), None, 30),
        _Tok(_Feat("episode_completion_pct"), None, 47),
    ])
    p = parse_observation(obs, CENTER, TEAM_TAG_IDS)
    check("7 last_reward normalized", abs(p.last_reward - 3.0) < 1e-6)
    check("7b episode_completion_pct", p.episode_completion_pct == 47)


def test_empty_observation_defaults() -> None:
    # 8. Empty observation produces a default Perception.
    p = parse_observation(_Obs([]), CENTER, TEAM_TAG_IDS)
    check(
        "8 empty observation",
        p.tags_by_location == {} and p.inventory == {} and not p.in_friendly_aoe,
    )
    assert isinstance(p, Perception)


def test_tag_index() -> None:
    # 9. TagIndex.
    idx = TagIndex(["type:wall", "team:cogs", "team:clips", "type:hub"])
    check("9 tag get", idx.get("team:cogs") == 1 and idx.get("nonexistent") is None)
    check("9b tag has", idx.has("type:hub") and not idx.has("type:bogus"))
    check("9c team_tag_ids", idx.team_tag_ids == frozenset({1, 2}))
    ids = idx.ids_for_names(["team:cogs", "type:hub", "type:bogus"])
    check("9d ids_for_names drops missing", ids == frozenset({1, 3}))
    try:
        idx.require("missing")
    except KeyError:
        check("9e require raises", True)
    else:
        check("9e require raises", False)


def test_mocks_satisfy_the_protocol() -> None:
    # The duck-typed surface is a runtime-checkable Protocol; the same mock
    # shape the original smoke test used (and mettagrid's real observation
    # type) conforms structurally.
    obs = _Obs([_Tok(_Feat("tag"), (0, 0), 1)])
    assert isinstance(obs, ObservationLike)
