from __future__ import annotations

from cogames.game import get_game
from cogames.variants import VariantRegistry
from amongcogs.game import (
    ALL_VARIANTS,
    AMONG_US_INTERFACE_VARIANTS,
    AMONG_US_MECHANICS,
    HIDDEN_VARIANTS,
    VARIANTS,
    among_us_mechanics,
    parse_variants,
    requires_explicit_mechanics_surface,
    resolved_variant_names,
)
from amongcogs.game.full import FullVariant
from amongcogs.missions import AmongUsGame
from amongcogs.runtime import GAMES, make_game


def _handler_names(handler) -> set[str]:
    if handler is None:
        return set()
    name = getattr(handler, "name", None)
    if name:
        return {name}
    names: set[str] = set()
    for child in getattr(handler, "handlers", []):
        names |= _handler_names(child)
    return names


def test_among_us_registers_metta_and_cogame_definitions() -> None:
    info = GAMES["amongcogs"]

    assert info["mission_class"].__name__ == "AmongUsGame"
    assert info["parse_variants"] is parse_variants
    assert info["policy_uri"] == "metta://policy/amongcogs_agent"
    assert "amongcogs.agent.amongcogs_agent" in info["policy_packages"]
    assert "amongcogs.agent.amongcogs_cyborg" in info["policy_packages"]

    game = get_game("amongcogs")
    assert [mission.full_name() for mission in game.missions] == ["amongcogs_ship.basic"]
    assert tuple(variant.name for variant in game.variant_registry.all()) == tuple(
        variant.name for variant in ALL_VARIANTS
    )


def test_among_us_parse_variants_preserves_explicit_requests() -> None:
    resolved = resolved_variant_names(["full"])
    assert resolved[-1] == "full"
    assert {"roles", "tasks", "vents", "station_events", "combat", "meetings", "win_conditions", "metrics"}.issubset(
        set(resolved)
    )
    assert len(resolved) == len(set(resolved))


def test_among_us_parse_variants_uses_local_variant_types() -> None:
    resolved = parse_variants(["full"])
    assert isinstance(resolved[-1], FullVariant)


def test_among_us_dependency_registry_builds_full_graph() -> None:
    registry = VariantRegistry([FullVariant()])
    edges = registry.build_dependency_graph()

    required_edges = {
        ("full", "roles", "required"),
        ("full", "tasks", "required"),
        ("full", "vents", "required"),
        ("full", "station_events", "required"),
        ("full", "combat", "required"),
        ("full", "meetings", "required"),
        ("full", "win_conditions", "required"),
        ("full", "metrics", "required"),
    }
    assert required_edges.issubset(set(edges))


def test_among_us_variant_constants_expose_interface_and_mechanics_only() -> None:
    assert AMONG_US_INTERFACE_VARIANTS == ("full",)
    assert [variant.name for variant in VARIANTS] == ["full"]
    assert [variant.name for variant in HIDDEN_VARIANTS] == [
        "roles",
        "tasks",
        "vents",
        "station_events",
        "combat",
        "meetings",
        "win_conditions",
        "metrics",
        "short_meeting",
        "fast_kill_cooldown",
        "rapid_critical",
    ]
    assert "full" not in AMONG_US_MECHANICS
    assert "short_meeting" not in AMONG_US_MECHANICS
    assert "fast_kill_cooldown" not in AMONG_US_MECHANICS
    assert "rapid_critical" not in AMONG_US_MECHANICS
    assert {
        "roles",
        "tasks",
        "vents",
        "station_events",
        "combat",
        "meetings",
        "win_conditions",
        "metrics",
    } == set(AMONG_US_MECHANICS)
    assert list(AMONG_US_MECHANICS) == among_us_mechanics()


def test_among_us_default_env_matches_full_variant_surface() -> None:
    default_env = make_game("amongcogs", num_agents=8, max_steps=180)
    full_env = make_game("amongcogs", num_agents=8, max_steps=180, variants=["full"])

    assert default_env.game.resource_names == full_env.game.resource_names
    assert set(default_env.game.objects) == set(full_env.game.objects)
    assert set(default_env.game.events) == set(full_env.game.events)
    assert default_env.game.actions.actions() == full_env.game.actions.actions()


def test_among_us_defaults_to_full_variant_mechanics() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=120)
    assert "sync_reactor_sabotage" in env.game.events
    assert "sync_oxygen_sabotage" in env.game.events
    assert "reactor_timer_tick" in env.game.events
    assert "oxygen_timer_tick" in env.game.events
    assert "impostor_kill_nearby_crew" in env.game.events
    assert "crew_report_corpse" in env.game.events
    assert "meeting_vote_target_0" in env.game.events
    assert "meeting_open_ballot" in env.game.events
    assert "crew_win_check" in env.game.events
    assert "impostor_win_parity_check" in env.game.events
    assert "reactor_vent" in env.game.objects
    assert "emergency_button" in env.game.objects
    assert "lights_station" in env.game.objects
    assert env.game.talk.enabled is True
    assert env.game.talk.max_length == 64
    assert env.game.talk.cooldown_steps == 1
    assert env.game.end_episode_on_game_stats == {"winner_declared": 1}
    assert env.label == "amongcogs_ship.basic"


def test_among_us_roles_variant_only_applies_role_slice() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=120, variants=["roles"])

    assert "force_assign_impostor_role" in env.game.events
    assert "force_assign_crew_roles" in env.game.events
    assert "sync_reactor_sabotage" not in env.game.events
    assert "impostor_kill_nearby_crew" not in env.game.events
    assert "crew_report_corpse" not in env.game.events
    assert "crew_win_check" not in env.game.events
    assert "meeting_vote_target_0" not in env.game.events
    assert "become_crew" in _handler_names(env.game.objects["crew_station"].on_use_handler)
    assert "complete_task" not in _handler_names(env.game.objects["wiring_station"].on_use_handler)
    assert env.label == "amongcogs_ship.basic.roles"


def test_among_us_meetings_variant_pulls_dependency_slices() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=120, variants=["meetings"])

    assert "crew_report_corpse" in env.game.events
    assert "call_emergency_meeting" in env.game.events
    assert "meeting_vote_target_0" in env.game.events
    assert "impostor_kill_nearby_crew" in env.game.events
    assert "force_assign_impostor_role" in env.game.events
    assert "sync_reactor_sabotage" not in env.game.events
    assert env.label == "amongcogs_ship.basic.meetings"


def test_hidden_mechanics_request_requires_explicit_surface() -> None:
    assert requires_explicit_mechanics_surface(["roles"])
    assert requires_explicit_mechanics_surface(["short_meeting"])
    assert not requires_explicit_mechanics_surface(["full"])


def test_hidden_mechanics_request_clears_default_full_variant() -> None:
    mission = AmongUsGame.create(num_agents=8, max_steps=120).with_variants(["roles"])
    assert mission.default_variant is None


def test_among_us_make_env_tracks_default_dependency_expansion_in_registry() -> None:
    mission = AmongUsGame.create(num_agents=8, max_steps=120)
    env = mission.make_env()

    assert mission._variant_registry is not None
    configured_names = mission._variant_registry.configured_names()
    assert set(configured_names) == {
        "roles",
        "tasks",
        "vents",
        "station_events",
        "combat",
        "meetings",
        "win_conditions",
        "metrics",
        "full",
    }
    assert configured_names.index("roles") < configured_names.index("combat")
    assert configured_names.index("combat") < configured_names.index("meetings")
    assert configured_names.index("tasks") < configured_names.index("station_events")
    assert configured_names.index("station_events") < configured_names.index("win_conditions")
    assert isinstance(mission._variant_registry.get("full"), FullVariant)
    assert env.label == "amongcogs_ship.basic"


def test_among_us_labels_only_requested_variants_not_registry_dependencies() -> None:
    env = make_game("amongcogs", num_agents=6, max_steps=120, variants=["short_meeting"])
    assert env.label.endswith(".short_meeting")
    assert ".meetings" not in env.label
    assert ".full" not in env.label
