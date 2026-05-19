from __future__ import annotations

from amongcogs.constants import CRITICAL_TIMER_RESOURCE, KILL_COOLDOWN_RESOURCE, MEETING_TIMER_RESOURCE
from amongcogs.game.timing import (
    FAST_INITIAL_KILL_COOLDOWN_STEPS,
    FAST_KILL_COOLDOWN_STEPS,
    RAPID_LIGHTS_SABOTAGE_TIMER_STEPS,
    RAPID_OXYGEN_SABOTAGE_TIMER_STEPS,
    RAPID_REACTOR_SABOTAGE_TIMER_STEPS,
    SHORT_MEETING_DURATION_STEPS,
)
from amongcogs.missions import AmongUsGame


def _mutation_delta(event, resource_name: str) -> int:
    for mutation in event.mutations:
        deltas = getattr(mutation, "deltas", None)
        if isinstance(deltas, dict) and resource_name in deltas:
            return int(deltas[resource_name])
    raise AssertionError(f"Expected {resource_name!r} delta in event {event.name!r}")


def test_short_meeting_variant_shortens_meeting_limits_and_events() -> None:
    mission = AmongUsGame.create(num_agents=8, max_steps=120).with_variants(["short_meeting"])
    env = mission.make_env()

    assert env.game.agents[0].inventory.limits["meeting_timer"].max == SHORT_MEETING_DURATION_STEPS
    assert _mutation_delta(env.game.events["crew_report_corpse"], MEETING_TIMER_RESOURCE) == (
        SHORT_MEETING_DURATION_STEPS
    )
    assert _mutation_delta(env.game.events["call_emergency_meeting"], MEETING_TIMER_RESOURCE) == (
        SHORT_MEETING_DURATION_STEPS
    )


def test_fast_kill_cooldown_variant_shortens_role_and_combat_cooldowns() -> None:
    mission = AmongUsGame.create(num_agents=8, max_steps=120).with_variants(["fast_kill_cooldown"])
    env = mission.make_env()

    assert env.game.agents[0].inventory.limits["kill_cooldown"].max == FAST_INITIAL_KILL_COOLDOWN_STEPS
    assert _mutation_delta(env.game.events["force_assign_impostor_role"], KILL_COOLDOWN_RESOURCE) == (
        FAST_INITIAL_KILL_COOLDOWN_STEPS
    )
    assert _mutation_delta(env.game.events["impostor_kill_nearby_crew"], KILL_COOLDOWN_RESOURCE) == (
        FAST_KILL_COOLDOWN_STEPS
    )


def test_rapid_critical_variant_shortens_sabotage_windows() -> None:
    mission = AmongUsGame.create(num_agents=8, max_steps=120).with_variants(["rapid_critical"])
    env = mission.make_env()

    assert env.game.objects["reactor_station"].inventory.default_limit == RAPID_REACTOR_SABOTAGE_TIMER_STEPS
    assert env.game.objects["oxygen_station"].inventory.default_limit == RAPID_OXYGEN_SABOTAGE_TIMER_STEPS
    assert env.game.objects["lights_station"].inventory.default_limit == RAPID_LIGHTS_SABOTAGE_TIMER_STEPS
    assert _mutation_delta(env.game.events["impostor_sabotage_reactor_intent"], CRITICAL_TIMER_RESOURCE) == (
        RAPID_REACTOR_SABOTAGE_TIMER_STEPS
    )
    assert _mutation_delta(env.game.events["impostor_sabotage_oxygen_intent"], CRITICAL_TIMER_RESOURCE) == (
        RAPID_OXYGEN_SABOTAGE_TIMER_STEPS
    )
    assert _mutation_delta(env.game.events["impostor_sabotage_lights_intent"], CRITICAL_TIMER_RESOURCE) == (
        RAPID_LIGHTS_SABOTAGE_TIMER_STEPS
    )
