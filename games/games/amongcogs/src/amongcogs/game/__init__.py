"""Among Us variants.

Public variants stay focused on the launch-facing gameplay bundle.
Mechanic-building and timing-stress variants remain hidden, but are still
available for explicit CLI usage and targeted regression coverage.
"""

from __future__ import annotations

from cogames.core import CoGameMissionVariant
from cogames.variants import VariantRegistry
from amongcogs.constants import (
    ALIVE_RESOURCE,
    AGENT_ID_RESOURCE_PREFIX,
    COMMS_ALERT_RESOURCE,
    CORPSE_RESOURCE,
    CRITICAL_STATION_NAMES,
    CRITICAL_TIMER_RESOURCE,
    EJECTED_RESOURCE,
    INITIAL_KILL_COOLDOWN_STEPS,
    KILL_COOLDOWN_RESOURCE,
    LIGHTS_ALERT_RESOURCE,
    LIGHTS_CREW_VISION_RADIUS,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    MEETING_DISCUSSION_RESOURCE,
    MEETING_DISCUSSION_TIMER_RESOURCE,
    MEETING_DISCUSSION_TURNS,
    MEETING_DURATION_STEPS,
    MEETING_REPORTED_BODY_RESOURCE,
    MEETING_TIMER_RESOURCE,
    MEETING_TOKEN_COUNT,
    MEETING_TOKEN_RESOURCE,
    MAX_NAMED_VOTE_TARGETS,
    OXYGEN_ALERT_RESOURCE,
    REACTOR_ALERT_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    NORMAL_VISION_RADIUS,
    STATION_ONLINE_TAG,
    STATION_SABOTAGED_TAG,
    SYSTEM_COMMS_TAG,
    SYSTEM_LIGHTS_TAG,
    SYSTEM_OXYGEN_TAG,
    SYSTEM_REACTOR_TAG,
    TASK_ONLINE_TAG,
    TASK_PROGRESS_STEPS,
    TASK_PROGRESS_RESOURCE,
    TASK_RESOURCE,
    TASK_SABOTAGED_TAG,
    TASK_STATION_NAMES,
    TASK_STATION_TAG,
    VENT_COOLDOWN_RESOURCE,
    VENT_STATION_NAMES,
    VENT_STATION_TAG,
    VIBE_CALL_MEETING,
    VIBE_KILL,
    VIBE_REPORT,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_OXYGEN,
    VIBE_SABOTAGE_REACTOR,
    VIBE_VOTE_IMPOSTOR,
    VIBE_VOTE_SKIP,
    VOTE_IMPOSTOR_RESOURCE,
    VOTE_SKIP_RESOURCE,
    VOTE_TARGET_RESOURCE_PREFIX,
    VOTED_RESOURCE,
    WIN_REWARD_RESOURCE,
    agent_id_resource,
    crew_station_config,
    emergency_button_config,
    impostor_station_config,
    named_vote_target_count,
    security_station_config,
    task_station_config,
    vote_target_resource,
    vote_target_vibe,
)
from amongcogs.game.combat import CombatVariant
from amongcogs.game.full import FullVariant
from amongcogs.game.meetings import MeetingsVariant
from amongcogs.game.metrics import MetricsVariant
from amongcogs.game.roles import RolesVariant
from amongcogs.game.station_events import StationEventsVariant
from amongcogs.game.tasks import TasksVariant
from amongcogs.game.timing import FastKillCooldownVariant, RapidCriticalVariant, ShortMeetingVariant
from amongcogs.game.vents import VentsVariant
from amongcogs.game.win_conditions import WinConditionsVariant

__all__ = [
    "ALIVE_RESOURCE",
    "AGENT_ID_RESOURCE_PREFIX",
    "COMMS_ALERT_RESOURCE",
    "CORPSE_RESOURCE",
    "CRITICAL_STATION_NAMES",
    "CRITICAL_TIMER_RESOURCE",
    "EJECTED_RESOURCE",
    "INITIAL_KILL_COOLDOWN_STEPS",
    "KILL_COOLDOWN_RESOURCE",
    "LIGHTS_ALERT_RESOURCE",
    "LIGHTS_CREW_VISION_RADIUS",
    "MEETING_ACTIVE_RESOURCE",
    "MEETING_BALLOT_RESOURCE",
    "MEETING_DISCUSSION_RESOURCE",
    "MEETING_DISCUSSION_TIMER_RESOURCE",
    "MEETING_DISCUSSION_TURNS",
    "MEETING_DURATION_STEPS",
    "MEETING_REPORTED_BODY_RESOURCE",
    "MEETING_TIMER_RESOURCE",
    "MEETING_TOKEN_COUNT",
    "MEETING_TOKEN_RESOURCE",
    "MAX_NAMED_VOTE_TARGETS",
    "OXYGEN_ALERT_RESOURCE",
    "REACTOR_ALERT_RESOURCE",
    "ROLE_CREW",
    "ROLE_IMPOSTOR",
    "NORMAL_VISION_RADIUS",
    "STATION_ONLINE_TAG",
    "STATION_SABOTAGED_TAG",
    "SYSTEM_COMMS_TAG",
    "SYSTEM_LIGHTS_TAG",
    "SYSTEM_OXYGEN_TAG",
    "SYSTEM_REACTOR_TAG",
    "TASK_ONLINE_TAG",
    "TASK_PROGRESS_STEPS",
    "TASK_PROGRESS_RESOURCE",
    "TASK_RESOURCE",
    "TASK_SABOTAGED_TAG",
    "TASK_STATION_NAMES",
    "TASK_STATION_TAG",
    "VENT_COOLDOWN_RESOURCE",
    "VENT_STATION_NAMES",
    "VENT_STATION_TAG",
    "VIBE_CALL_MEETING",
    "VIBE_KILL",
    "VIBE_REPORT",
    "VIBE_SABOTAGE_COMMS",
    "VIBE_SABOTAGE_LIGHTS",
    "VIBE_SABOTAGE_OXYGEN",
    "VIBE_SABOTAGE_REACTOR",
    "VIBE_VOTE_IMPOSTOR",
    "VIBE_VOTE_SKIP",
    "VOTE_IMPOSTOR_RESOURCE",
    "VOTE_SKIP_RESOURCE",
    "VOTE_TARGET_RESOURCE_PREFIX",
    "VOTED_RESOURCE",
    "WIN_REWARD_RESOURCE",
    "agent_id_resource",
    "crew_station_config",
    "emergency_button_config",
    "impostor_station_config",
    "named_vote_target_count",
    "security_station_config",
    "task_station_config",
    "vote_target_resource",
    "vote_target_vibe",
    "CombatVariant",
    "FullVariant",
    "MeetingsVariant",
    "MetricsVariant",
    "RolesVariant",
    "StationEventsVariant",
    "TasksVariant",
    "VentsVariant",
    "WinConditionsVariant",
    "ALL_VARIANTS",
    "AMONG_US_INTERFACE_VARIANTS",
    "AMONG_US_MECHANICS",
    "HIDDEN_VARIANTS",
    "VARIANTS",
    "among_us_mechanics",
    "build_variant_registry",
    "create_variant",
    "parse_variants",
    "requires_explicit_mechanics_surface",
    "resolve_variants",
    "resolved_variant_names",
]

PUBLIC_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = (FullVariant,)
HIDDEN_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = (
    RolesVariant,
    TasksVariant,
    VentsVariant,
    StationEventsVariant,
    CombatVariant,
    MeetingsVariant,
    WinConditionsVariant,
    MetricsVariant,
    ShortMeetingVariant,
    FastKillCooldownVariant,
    RapidCriticalVariant,
)
ALL_VARIANT_TYPES = PUBLIC_VARIANT_TYPES + HIDDEN_VARIANT_TYPES

VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(variant_type() for variant_type in PUBLIC_VARIANT_TYPES)
HIDDEN_VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(variant_type() for variant_type in HIDDEN_VARIANT_TYPES)
ALL_VARIANTS: tuple[CoGameMissionVariant, ...] = (*VARIANTS, *HIDDEN_VARIANTS)
AMONG_US_INTERFACE_VARIANTS: tuple[str, ...] = tuple(variant.name for variant in VARIANTS)

_VARIANT_TYPES_BY_NAME = {variant.name: type(variant) for variant in ALL_VARIANTS}
HIDDEN_VARIANT_NAMES = frozenset(variant.name for variant in HIDDEN_VARIANTS)
_NON_MECHANIC_VARIANTS = {"short_meeting", "fast_kill_cooldown", "rapid_critical"}
AMONG_US_MECHANICS: tuple[str, ...] = tuple(
    variant.name for variant in HIDDEN_VARIANTS if variant.name not in _NON_MECHANIC_VARIANTS
)


def among_us_mechanics() -> list[str]:
    return list(AMONG_US_MECHANICS)


def _normalize_requested_names(names: list[str]) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        requested.append(name)
    unknown = [name for name in requested if name not in _VARIANT_TYPES_BY_NAME]
    if unknown:
        available = ", ".join(sorted(_VARIANT_TYPES_BY_NAME))
        raise ValueError(f"Unknown variant {unknown[0]!r}. Available: {available}")
    return requested


def create_variant(name: str) -> CoGameMissionVariant:
    requested = _normalize_requested_names([name])
    expected_type = _VARIANT_TYPES_BY_NAME[requested[0]]
    return expected_type()  # pyright: ignore[reportCallIssue]


def build_variant_registry(names: list[str]) -> VariantRegistry:
    requested = _normalize_requested_names(names)
    registry = VariantRegistry([create_variant(name) for name in requested])
    registry.run_configure(requested)

    unexpected = [variant.name for variant in registry.all() if not isinstance(variant, ALL_VARIANT_TYPES)]
    assert not unexpected, f"Among Us registry resolved non-local variants: {unexpected}"
    return registry


def requires_explicit_mechanics_surface(names: list[str]) -> bool:
    return any(name in HIDDEN_VARIANT_NAMES for name in _normalize_requested_names(names))


def parse_variants(names: list[str]) -> list[CoGameMissionVariant]:
    if not names:
        return []
    return build_variant_registry(names).configured()


def resolve_variants(names: list[str]) -> list[CoGameMissionVariant]:
    return parse_variants(names)


def resolved_variant_names(names: list[str]) -> list[str]:
    return [variant.name for variant in parse_variants(names)]
