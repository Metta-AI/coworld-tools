"""Shared constants and helpers for Werewolf/Mafia variants."""

from __future__ import annotations

from typing import Any

from werecog.defaults import (
    DEFAULT_BLIND_VISION_RADIUS,
    DEFAULT_DAY_STEPS,
    DEFAULT_EXECUTION_THRESHOLD,
    DEFAULT_FULL_VISION_RADIUS,
    DEFAULT_NIGHT_KILLS_PER_PHASE,
    DEFAULT_NIGHT_STEPS,
)
from mettagrid.config.filter import GameValueFilter, HandlerTarget, actorHas, anyOf, isNot, query, targetHas
from mettagrid.config.game_value import QueryCountValue, SumGameValue, stat, val
from mettagrid.config.handler_config import Handler, updateActor
from mettagrid.config.mettagrid_config import GridObjectConfig
from mettagrid.config.mutation.stats_mutation import StatsMutation, StatsTarget, logStatToGame
from mettagrid.config.tag import typeTag

ROLE_VILLAGER = "villager"
ROLE_WEREWOLF = "werewolf"
ALIVE = "alive"
VOTE_TOKEN = "vote_token"
SUSPICION = "suspicion"
DAY_PHASE = "day_phase"
NIGHT_PHASE = "night_phase"
DAY_VOTE_OPEN = "day_vote_open"
NIGHT_HUNT_OPEN = "night_hunt_open"
ACCUSATION = "accusation"

ROLE_RESOURCES = [ROLE_VILLAGER, ROLE_WEREWOLF]

NIGHT_KILL_USED_STAT = "night_kill_used"
DAY_EXECUTION_USED_STAT = "day_execution_used"
WINNER_DECLARED_STAT = "winner_declared"
VILLAGERS_WIN_STAT = "villagers_win"
WEREWOLVES_WIN_STAT = "werewolves_win"
NIGHT_KILLS_STAT = "night_kills"
DAY_EXECUTIONS_STAT = "day_executions"
DAY_VOTES_CAST_STAT = "day_votes_cast"
ACCUSE_ACTIONS_STAT = "accusations_made"
WEREWOLF_EXECUTIONS_STAT = "werewolf_executions"
BALLOTS_COLLECTED_STAT = "ballots_collected"
VISION_RADIUS_STAT = "vision_radius"


def night_steps(mission: Any | None = None) -> int:
    if mission is not None and hasattr(mission, "night_steps"):
        return int(mission.night_steps)
    return DEFAULT_NIGHT_STEPS


def day_steps(mission: Any | None = None) -> int:
    if mission is not None and hasattr(mission, "day_steps"):
        return int(mission.day_steps)
    return DEFAULT_DAY_STEPS


def phase_period(mission: Any | None = None) -> int:
    return night_steps(mission) + day_steps(mission)


def night_hunt_open_step(mission: Any | None = None) -> int:
    steps = night_steps(mission)
    if steps <= 1:
        return 0
    return max(1, min(steps - 1, steps // 2))


def day_vote_open_step(mission: Any | None = None) -> int:
    steps = day_steps(mission)
    if steps <= 1:
        return 0
    return max(1, min(steps - 1, steps // 3))


def night_kills_per_phase(mission: Any | None = None) -> int:
    if mission is not None and hasattr(mission, "night_kills_per_phase"):
        return int(mission.night_kills_per_phase)
    return DEFAULT_NIGHT_KILLS_PER_PHASE


def full_vision_radius(mission: Any | None = None) -> int:
    if mission is not None and hasattr(mission, "full_vision_radius"):
        return int(mission.full_vision_radius)
    return DEFAULT_FULL_VISION_RADIUS


def discussion_radius(mission: Any | None = None) -> int:
    if mission is None or not hasattr(mission, "map_builder"):
        return full_vision_radius(mission)
    map_builder = mission.map_builder
    width = getattr(map_builder, "width", 0)
    height = getattr(map_builder, "height", 0)
    if isinstance(width, int) and isinstance(height, int):
        return max(full_vision_radius(mission), width, height)
    return full_vision_radius(mission)


def blind_vision_radius(mission: Any | None = None) -> int:
    if mission is not None and hasattr(mission, "blind_vision_radius"):
        return int(mission.blind_vision_radius)
    return DEFAULT_BLIND_VISION_RADIUS


def execution_threshold(mission: Any | None = None, num_agents: int | None = None) -> int:
    del num_agents
    if mission is not None and hasattr(mission, "execution_threshold_votes"):
        return int(mission.execution_threshold_votes)
    return DEFAULT_EXECUTION_THRESHOLD


def append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def agent_is_werewolf(agent: Any) -> bool:
    return int(agent.initial_stats[ROLE_WEREWOLF]) >= 1


def actor_has_role(role_name: str) -> GameValueFilter:
    return GameValueFilter(target=HandlerTarget.ACTOR, value=stat(role_name), min=1)


def target_has_role(role_name: str) -> GameValueFilter:
    return GameValueFilter(target=HandlerTarget.TARGET, value=stat(role_name), min=1)


def actor_has_any_role() -> Any:
    return anyOf([actor_has_role(role_name) for role_name in ROLE_RESOURCES])


def target_has_any_role() -> Any:
    return anyOf([target_has_role(role_name) for role_name in ROLE_RESOURCES])


def living_role_count(role_name: str) -> QueryCountValue:
    return QueryCountValue(query=query(typeTag("agent"), [targetHas({ALIVE: 1}), target_has_role(role_name)]))


def living_villager_count() -> QueryCountValue:
    return living_role_count(ROLE_VILLAGER)


def living_werewolf_count() -> QueryCountValue:
    return living_role_count(ROLE_WEREWOLF)


def living_parity_margin() -> SumGameValue:
    return SumGameValue(values=[living_werewolf_count(), living_villager_count()], weights=[1.0, -1.0])


def no_game_winner_filter(target: HandlerTarget = HandlerTarget.ACTOR) -> GameValueFilter | Any:
    return isNot(GameValueFilter(target=target, value=stat(f"game.{WINNER_DECLARED_STAT}"), min=1))


def reset_game_stat(stat_name: str) -> StatsMutation:
    return StatsMutation(stat=stat_name, target=StatsTarget.GAME, source=val(0))


def set_game_stat(stat_name: str, value: int = 1) -> StatsMutation:
    return StatsMutation(stat=stat_name, target=StatsTarget.GAME, source=val(value))


def meeting_bell() -> GridObjectConfig:
    return GridObjectConfig(
        name="meeting_bell",
        on_use_handler=Handler(
            name="collect_ballot",
            filters=[
                actor_has_any_role(),
                actorHas({ALIVE: 1, DAY_PHASE: 1}),
                isNot(actorHas({VOTE_TOKEN: 1})),
                no_game_winner_filter(),
            ],
            mutations=[updateActor({VOTE_TOKEN: 1}), logStatToGame(BALLOTS_COLLECTED_STAT)],
        ),
    )
