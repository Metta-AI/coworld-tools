from __future__ import annotations

import pytest

from werecog import make_game
from werecog import WerecogMission
from werecog.variants import (
    HIDDEN_VARIANT_NAMES,
    WEREWOLF_MAFIA_MECHANICS,
    parse_variants,
    resolve_variant_selection,
    variant_dependency_graph,
)


def test_parse_variants_resolves_full_dependency_tree() -> None:
    names = resolve_variant_selection(["full"]).configured_names()
    assert names[-1] == "full"
    assert WEREWOLF_MAFIA_MECHANICS == tuple(name for name in names if name != "full")
    assert len(names) == len(set(names))


def test_parse_variants_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown variant"):
        parse_variants(["does_not_exist"])


def test_make_game_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown variant"):
        make_game("werewolf_mafia", num_agents=12, max_steps=120, variants=["does_not_exist"])


def test_variant_dependency_graph_matches_expected_tree_edges() -> None:
    edges = set(variant_dependency_graph(["full"]))
    assert ("full", "hunt", "required") in edges
    assert ("hunt", "meetings", "required") in edges
    assert ("voting", "meetings", "required") in edges
    assert ("render", "voting", "required") in edges


def test_werewolf_mafia_mechanics_exclude_timing_stress_variants() -> None:
    assert "short_night" not in WEREWOLF_MAFIA_MECHANICS
    assert "long_night" not in WEREWOLF_MAFIA_MECHANICS
    assert "short_day" not in WEREWOLF_MAFIA_MECHANICS


def test_hidden_mechanics_request_requires_explicit_surface() -> None:
    assert "meetings" in HIDDEN_VARIANT_NAMES
    assert "full" not in HIDDEN_VARIANT_NAMES


def test_hidden_mechanics_request_clears_default_full_variant() -> None:
    mission = WerecogMission.create(8, 120).with_variants(["meetings"])
    assert mission.default_variant is None


def test_meetings_variant_auto_enables_roles() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=120, variants=["meetings"])
    assert {"alive", "vote_token", "day_phase", "night_phase", "day_vote_open", "night_hunt_open"}.issubset(
        set(env.game.resource_names)
    )
    assert "villager" in env.game.resource_names
    assert "werewolf" in env.game.resource_names
    assert "meeting_bell" in env.game.objects
    assert "accusation" not in env.game.resource_names


def test_full_variant_matches_default_mechanics_surface() -> None:
    default_env = make_game("werewolf_mafia", num_agents=12, max_steps=180)
    explicit_env = make_game(
        "werewolf_mafia",
        num_agents=12,
        max_steps=180,
        variants=list(WEREWOLF_MAFIA_MECHANICS),
    )

    assert default_env.game.resource_names == explicit_env.game.resource_names
    assert set(default_env.game.objects.keys()) == set(explicit_env.game.objects.keys())
    assert default_env.game.actions.actions() == explicit_env.game.actions.actions()
