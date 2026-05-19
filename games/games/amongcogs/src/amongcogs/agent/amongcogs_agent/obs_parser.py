"""Observation parser for the Among Us scripted agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    from mettagrid.simulator.interface import AgentObservation


@dataclass
class VisibleEntity:
    """Entity reconstructed from observation tokens for one map cell."""

    type_name: str
    tags: set[str] = field(default_factory=set)
    inventory: dict[str, int] = field(default_factory=dict)
    agent_id: int | None = None
    last_seen: int = 0


@dataclass
class AmongUsState:
    """Agent-local state rebuilt from each observation."""

    position: tuple[int, int] = (0, 0)
    crew: int = 0
    impostor: int = 0
    tasks: int = 0
    task_progress: int = 0
    alive: int = 0
    corpse: int = 0
    meeting_active: int = 0
    meeting_discussion: int = 0
    meeting_ballot: int = 0
    meeting_reported_body: int = 0
    meeting_token: int = 0
    meeting_timer: int = 0
    voted: int = 0
    vote_impostor: int = 0
    vote_skip: int = 0
    kill_cooldown: int = 0
    sabotage_cooldown: int = 0
    vent_cooldown: int = 0
    ejected: int = 0
    win_reward: int = 0
    lights_alert: int = 0
    comms_alert: int = 0
    oxygen_alert: int = 0
    reactor_alert: int = 0

    @property
    def role(self) -> str | None:
        if self.impostor > 0:
            return "impostor"
        if self.crew > 0:
            return "crew"
        return None

    @property
    def is_alive(self) -> bool:
        return self.alive > 0


class ObsParser:
    """Decode token observations into agent state and visible entities."""

    def __init__(self, pei: "PolicyEnvInterface") -> None:
        self._hr = pei.obs_height // 2
        self._wr = pei.obs_width // 2
        self._tags = pei.tag_id_to_name

    def parse(
        self,
        obs: "AgentObservation",
        step: int,
        fallback_position: tuple[int, int],
    ) -> tuple[AmongUsState, dict[tuple[int, int], VisibleEntity]]:
        state = AmongUsState(position=fallback_position)
        inv: dict[str, int] = {}
        row_off = 0
        col_off = 0
        has_pos = False

        # First pass: parse local-position offsets and own inventory.
        for tok in obs.tokens:
            feature_name = tok.feature.name
            location = tok.location

            if location is None:
                if feature_name.startswith("lp:"):
                    has_pos, row_off, col_off = self._parse_lp(feature_name[3:], tok.value, row_off, col_off)
                elif feature_name.startswith("inv:"):
                    _accum_inv(inv, feature_name[4:], tok.value)
                continue

            if location.row == self._hr and location.col == self._wr and feature_name.startswith("inv:"):
                _accum_inv(inv, feature_name[4:], tok.value)

        if has_pos:
            state.position = (fallback_position[0] + row_off, fallback_position[1] + col_off)
        state.crew = inv.get("crew", 0)
        state.impostor = inv.get("impostor", 0)
        state.tasks = inv.get("task", 0)
        state.task_progress = inv.get("task_progress", 0)
        state.alive = inv.get("alive", 0)
        state.corpse = inv.get("corpse", 0)
        state.meeting_active = inv.get("meeting_active", 0)
        state.meeting_discussion = inv.get("meeting_discussion", 0)
        state.meeting_ballot = inv.get("meeting_ballot", 0)
        state.meeting_reported_body = inv.get("meeting_reported_body", 0)
        state.meeting_token = inv.get("meeting_token", 0)
        state.meeting_timer = inv.get("meeting_timer", 0)
        state.voted = inv.get("voted", 0)
        state.vote_impostor = inv.get("vote_impostor", 0)
        state.vote_skip = inv.get("vote_skip", 0)
        state.kill_cooldown = inv.get("kill_cooldown", 0)
        state.sabotage_cooldown = inv.get("sabotage_cooldown", 0)
        state.vent_cooldown = inv.get("vent_cooldown", 0)
        state.ejected = inv.get("ejected", 0)
        state.win_reward = inv.get("win_reward", 0)
        state.lights_alert = inv.get("lights_alert", 0)
        state.comms_alert = inv.get("comms_alert", 0)
        state.oxygen_alert = inv.get("oxygen_alert", 0)
        state.reactor_alert = inv.get("reactor_alert", 0)

        # Second pass: parse visible entities around the agent.
        cell_tags: dict[tuple[int, int], list[str]] = {}
        cell_inv: dict[tuple[int, int], dict[str, int]] = {}
        cell_agent_ids: dict[tuple[int, int], int] = {}

        for tok in obs.tokens:
            location = tok.location
            if location is None:
                continue

            if location.row == self._hr and location.col == self._wr:
                continue

            world_pos = (
                state.position[0] + (location.row - self._hr),
                state.position[1] + (location.col - self._wr),
            )

            feature_name = tok.feature.name
            if feature_name == "tag":
                tag_name = self._tags.get(tok.value)
                if tag_name is None:
                    continue
                cell_tags.setdefault(world_pos, []).append(tag_name)
            elif feature_name == "agent_id":
                cell_agent_ids[world_pos] = tok.value
            elif feature_name.startswith("inv:"):
                bucket = cell_inv.setdefault(world_pos, {})
                _accum_inv(bucket, feature_name[4:], tok.value)

        visible: dict[tuple[int, int], VisibleEntity] = {}
        for world_pos, tags in cell_tags.items():
            type_name = _resolve_type(tags)
            if type_name == "unknown":
                continue
            visible[world_pos] = VisibleEntity(
                type_name=type_name,
                tags=set(tags),
                inventory=cell_inv.get(world_pos, {}),
                agent_id=cell_agent_ids.get(world_pos),
                last_seen=step,
            )

        return state, visible

    @staticmethod
    def _parse_lp(direction: str, value: int, row_off: int, col_off: int) -> tuple[bool, int, int]:
        if direction == "east":
            return True, row_off, value
        if direction == "west":
            return True, row_off, -value
        if direction == "south":
            return True, value, col_off
        if direction == "north":
            return True, -value, col_off
        return False, row_off, col_off


def _resolve_type(tags: list[str]) -> str:
    for name in tags:
        if name.startswith("type:"):
            return name[5:]
    return "unknown"


def _accum_inv(inv: dict[str, int], suffix: str, value: int) -> None:
    # Multi-token packed integers use suffixes like "task:p1".
    if ":p" in suffix:
        base, packed = suffix.rsplit(":p", 1)
        inv[base] = inv.get(base, 0) + value * (256 ** int(packed))
    else:
        inv[suffix] = inv.get(suffix, 0) + value
