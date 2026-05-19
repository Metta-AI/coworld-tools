"""Scripted baseline policy for the diplomacy game."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from mettagrid.mettagrid_c import dtype_actions
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, ObservationToken
from mettagrid.simulator.interface import AgentObservation

from diplomacog.game import COUNTRIES, RIVAL_COUNTRY_BY_TARGET

_MOVE_ACTIONS = ["move_north", "move_east", "move_south", "move_west"]
_SPAWN_POS = (100, 100)
_EXPLORE_WAYPOINTS = (
    (0, 0),
    (-12, 0),
    (0, 12),
    (12, 0),
    (0, -12),
    (-12, -12),
    (-12, 12),
    (12, 12),
    (12, -12),
)
_AGENT_STYLES = ("diplomat", "responder", "saboteur", "raider", "trader", "engineer")
_HUB_TO_STATION_DELTAS: dict[str, tuple[int, int]] = {
    "country_a_hub": (8, 8),
    "country_b_hub": (8, -8),
    "country_c_hub": (-5, 0),
}
_STATION_TO_REACTOR_DELTAS: dict[str, tuple[int, int]] = {
    "country_a_station": (7, 12),
    "country_b_station": (7, -12),
    "country_c_station": (-15, 0),
}
_REACTOR_TO_TARGET_DELTAS: dict[str, tuple[int, int]] = {
    "country_a_station": (-7, -12),
    "country_b_station": (-7, 12),
    "country_c_station": (15, 0),
    "country_a_hub": (-15, -20),
    "country_b_hub": (-15, 20),
    "country_c_hub": (20, 0),
    "comms_station": (1, -6),
    "diplomacy_station": (1, 6),
    "sabotage_station": (8, 0),
}
_TUTORIAL_OVERLAY_PHASES = (
    "Diplomacy Watch Guide\n"
    "Each color is a country bloc. Capitals sit deep in each territory, assignment stations mark the home region, "
    "and the three frontier supply centers are the contested border spaces.",
    "Turn Structure\n"
    "The board now lingers on discussion, orders, retreats, and winter adjustments long enough to read each beat. "
    "Supply centers only change hands during Fall Orders, and captured centers recolor to the country that takes them.",
    "What The Scripted Agents Are Doing\n"
    "Agents gather power at the reactor, convert it into intel and influence, then either resolve incidents, submit "
    "treaties and trade queues, or raid rival hubs if they are carrying sabotage kits.",
    "How To Read Winning\n"
    "The top-left HUD shows the current campaign year and phase, the A/B/C center counts, the current leader, and "
    "the global win score versus pressure. Rising centers and stability mean the game is going well.",
)
_DISCUSSION_TARGETS = ("country_a_hub", "country_b_hub", "country_c_hub")
_COUNTRY_SHORT_TO_HUB = {country.removeprefix("country_").upper(): f"{country}_hub" for country in COUNTRIES}
_NEGATED_TALK_CONTEXT = ("won't ", "will not ", "don't ", "do not ", "not to ", "avoid ", "avoiding ", "never ")
_TALK_TARGET_PATTERNS = (
    re.compile(
        r"\b(?:leaving summit for|summit for|carry terms to|move on|moving on|advance on|pressure|pressuring|"
        r"stabilizing|stabilize|support|back|target|targeting|pivot to|coordinate on|align on|"
        r"defend|defending|hold)\s+(?:(?:country_(?P<hub>[abc])_hub)|(?P<short>[ABC]))\b",
        re.IGNORECASE,
    ),
)


def _accum_inventory(values: dict[str, int], suffix: str, value: int) -> None:
    if ":p" in suffix:
        base, pscale = suffix.rsplit(":p", 1)
        values[base] = values.get(base, 0) + value * (256 ** int(pscale))
    else:
        values[suffix] = values.get(suffix, 0) + value


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _offset_position(position: tuple[int, int], delta: tuple[int, int]) -> tuple[int, int]:
    return (position[0] + delta[0], position[1] + delta[1])


@dataclass
class DiplomacyEntity:
    type: str
    position: tuple[int, int]
    inventory: dict[str, int]
    last_seen_step: int


@dataclass
class DiplomacyObservation:
    position: tuple[int, int]
    inventory: dict[str, int]
    global_obs: dict[str, int]
    visible_entities: dict[tuple[int, int], DiplomacyEntity]
    visible_talk: tuple[DiplomacyVisibleTalk, ...] = ()


@dataclass(frozen=True)
class DiplomacyVisibleTalk:
    agent_id: int
    text: str
    remaining_steps: int


@dataclass
class DiplomacyAgentState:
    agent_id: int
    assigned_country: str
    style: Literal["diplomat", "responder", "saboteur", "raider", "trader", "engineer"]
    step: int = 0
    discussion_messages_sent: int = 0
    post_discussion_target: str | None = None
    pending_talk_override: str | None = None
    discussion_source: str = "scripted"
    last_position: tuple[int, int] = _SPAWN_POS
    last_action: str = "noop"
    last_sent_talk_step: int | None = None
    stuck_steps: int = 0
    was_in_discussion_phase: bool = False
    discussion_steps_in_window: int = 0
    last_phase_label: str = ""
    last_center_snapshot: tuple[int, int, int] | None = None
    known_entities: dict[tuple[int, int], DiplomacyEntity] = field(default_factory=dict)


class DiplomacyBrain(StatefulPolicyImpl[DiplomacyAgentState]):
    def __init__(self, pei: PolicyEnvInterface, agent_id: int) -> None:
        self._agent_id = agent_id
        self._obs_half_h = pei.obs_height // 2
        self._obs_half_w = pei.obs_width // 2
        self._tag_id_to_name = pei.tag_id_to_name
        self._action_names = set(pei.action_names)
        self._talk_enabled = pei.talk.enabled
        self._talk_max_length = pei.talk.max_length
        self._talk_cooldown_steps = pei.talk.cooldown_steps

    def initial_agent_state(self) -> DiplomacyAgentState:
        return DiplomacyAgentState(
            agent_id=self._agent_id,
            assigned_country=COUNTRIES[self._agent_id % len(COUNTRIES)],
            style=_AGENT_STYLES[self._agent_id % len(_AGENT_STYLES)],
        )

    def _parse_position_token(
        self,
        name: str,
        value: int,
        row_offset: int,
        col_offset: int,
    ) -> tuple[bool, int, int]:
        if name == "east":
            return True, row_offset, value
        if name == "west":
            return True, row_offset, -value
        if name == "south":
            return True, value, col_offset
        if name == "north":
            return True, -value, col_offset
        return False, row_offset, col_offset

    def _resolve_object_type(self, tag_ids: list[int]) -> str:
        for tid in tag_ids:
            tag_name = self._tag_id_to_name.get(tid, "")
            if tag_name.startswith("type:"):
                return tag_name[5:]
        for tid in tag_ids:
            tag_name = self._tag_id_to_name.get(tid, "")
            if tag_name and not tag_name.startswith("country:"):
                return tag_name
        return "unknown"

    def _parse_observation(self, obs: AgentObservation, s: DiplomacyAgentState) -> DiplomacyObservation:
        center_row, center_col = self._obs_half_h, self._obs_half_w
        inventory: dict[str, int] = {}
        global_obs: dict[str, int] = {}
        row_offset = 0
        col_offset = 0
        has_position = False
        cell_data: dict[tuple[int, int], dict[str, object]] = {}

        for token in obs.tokens:
            feature_name = token.feature.name
            location = token.location

            if location is None:
                if feature_name.startswith("lp:"):
                    has_position, row_offset, col_offset = self._parse_position_token(
                        feature_name[3:],
                        token.value,
                        row_offset,
                        col_offset,
                    )
                elif feature_name.startswith("inv:"):
                    _accum_inventory(inventory, feature_name[4:], token.value)
                elif feature_name.startswith("global."):
                    _accum_inventory(global_obs, feature_name[7:], token.value)
                elif feature_name == "last_action_move":
                    global_obs["last_action_move"] = int(token.value)
                continue

            if location.row == center_row and location.col == center_col:
                if feature_name.startswith("inv:"):
                    _accum_inventory(inventory, feature_name[4:], token.value)
                elif feature_name.startswith("lp:"):
                    has_position, row_offset, col_offset = self._parse_position_token(
                        feature_name[3:],
                        token.value,
                        row_offset,
                        col_offset,
                    )
                elif feature_name.startswith("global."):
                    _accum_inventory(global_obs, feature_name[7:], token.value)
                continue

            world_pos = (
                location.row - self._obs_half_h,
                location.col - self._obs_half_w,
            )
            if world_pos not in cell_data:
                cell_data[world_pos] = {"tags": [], "inv": {}}
            if feature_name == "tag":
                cell_tags = cell_data[world_pos]["tags"]
                assert isinstance(cell_tags, list)
                cell_tags.append(int(token.value))
            elif feature_name.startswith("inv:"):
                cell_inv = cell_data[world_pos]["inv"]
                assert isinstance(cell_inv, dict)
                _accum_inventory(cell_inv, feature_name[4:], token.value)

        absolute_position = (
            (
                _SPAWN_POS[0] + row_offset,
                _SPAWN_POS[1] + col_offset,
            )
            if has_position
            else s.last_position
        )

        visible_entities: dict[tuple[int, int], DiplomacyEntity] = {}
        for relative_pos, parsed in cell_data.items():
            tags = parsed["tags"]
            inv = parsed["inv"]
            assert isinstance(tags, list)
            assert isinstance(inv, dict)
            if not tags:
                continue
            obj_type = self._resolve_object_type(tags)
            if obj_type == "unknown":
                continue
            world_pos = (absolute_position[0] + relative_pos[0], absolute_position[1] + relative_pos[1])
            visible_entities[world_pos] = DiplomacyEntity(
                type=obj_type,
                position=world_pos,
                inventory=inv,
                last_seen_step=s.step,
            )

        visible_talk = tuple(
            sorted(
                (
                    DiplomacyVisibleTalk(
                        agent_id=int(talk.agent_id),
                        text=talk.text,
                        remaining_steps=int(talk.remaining_steps),
                    )
                    for talk in obs.talk
                    if talk.text
                ),
                key=lambda talk: (-talk.remaining_steps, talk.agent_id),
            )
        )

        return DiplomacyObservation(
            position=absolute_position,
            inventory=inventory,
            global_obs=global_obs,
            visible_entities=visible_entities,
            visible_talk=visible_talk,
        )

    def _update_memory(self, obs: DiplomacyObservation, s: DiplomacyAgentState) -> None:
        for pos, entity in obs.visible_entities.items():
            s.known_entities[pos] = entity
        if s.step % 40 != 0:
            return
        stale_positions = [pos for pos, entity in s.known_entities.items() if (s.step - entity.last_seen_step) > 320]
        for pos in stale_positions:
            s.known_entities.pop(pos, None)

    @staticmethod
    def _has_country(obs: DiplomacyObservation) -> bool:
        return any(obs.inventory.get(country, 0) > 0 for country in COUNTRIES)

    @staticmethod
    def _active_country(obs: DiplomacyObservation, s: DiplomacyAgentState) -> str:
        for country in COUNTRIES:
            if obs.inventory.get(country, 0) > 0:
                return country
        return s.assigned_country

    def _nearest_known_position(
        self,
        s: DiplomacyAgentState,
        object_type: str,
        position: tuple[int, int],
    ) -> tuple[int, int] | None:
        matches = [entity.position for entity in s.known_entities.values() if entity.type == object_type]
        if not matches:
            return None
        return min(matches, key=lambda pos: _manhattan(position, pos))

    @staticmethod
    def _target_from_reactor(
        object_type: str,
        reactor_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        if object_type == "reactor_station":
            return reactor_pos
        reactor_delta = _REACTOR_TO_TARGET_DELTAS.get(object_type)
        if reactor_delta is None:
            return None
        return _offset_position(reactor_pos, reactor_delta)

    @staticmethod
    def _station_from_hub(
        home_hub_type: str,
        hub_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        station_delta = _HUB_TO_STATION_DELTAS.get(home_hub_type)
        if station_delta is None:
            return None
        return _offset_position(hub_pos, station_delta)

    @staticmethod
    def _hub_from_station(
        home_hub_type: str,
        station_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        station_delta = _HUB_TO_STATION_DELTAS.get(home_hub_type)
        if station_delta is None:
            return None
        return _offset_position(station_pos, (-station_delta[0], -station_delta[1]))

    @staticmethod
    def _reactor_from_station(
        home_station_type: str,
        station_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        reactor_delta = _STATION_TO_REACTOR_DELTAS.get(home_station_type)
        if reactor_delta is None:
            return None
        return _offset_position(station_pos, reactor_delta)

    def _target_from_station(
        self,
        home_station_type: str,
        home_hub_type: str,
        object_type: str,
        station_pos: tuple[int, int],
    ) -> tuple[int, int] | None:
        if object_type == home_station_type:
            return station_pos
        if object_type == home_hub_type:
            return self._hub_from_station(home_hub_type, station_pos)
        reactor_pos = self._reactor_from_station(home_station_type, station_pos)
        if reactor_pos is None:
            return None
        return self._target_from_reactor(object_type, reactor_pos)

    def _anchored_target_position(
        self,
        s: DiplomacyAgentState,
        object_type: str,
        position: tuple[int, int],
        home_country: str,
    ) -> tuple[int, int] | None:
        reactor_pos = self._nearest_known_position(s, "reactor_station", position)
        if reactor_pos is not None:
            target_pos = self._target_from_reactor(object_type, reactor_pos)
            if target_pos is not None:
                return target_pos

        home_station_type = f"{home_country}_station"
        home_hub_type = f"{home_country}_hub"
        home_station_pos = self._nearest_known_position(s, home_station_type, position)
        if home_station_pos is not None:
            target_pos = self._target_from_station(
                home_station_type,
                home_hub_type,
                object_type,
                home_station_pos,
            )
            if target_pos is not None:
                return target_pos

        home_hub_pos = self._nearest_known_position(s, home_hub_type, position)
        if home_hub_pos is not None:
            inferred_station = self._station_from_hub(home_hub_type, home_hub_pos)
            if inferred_station is not None:
                return self._target_from_station(
                    home_station_type,
                    home_hub_type,
                    object_type,
                    inferred_station,
                )
        return None

    def _nearest_known_worksite(
        self,
        s: DiplomacyAgentState,
        position: tuple[int, int],
    ) -> tuple[int, int] | None:
        matches = [
            entity.position
            for entity in s.known_entities.values()
            if entity.type.endswith("_station") or entity.type.endswith("_hub") or entity.type == "supply_center"
        ]
        if not matches:
            return None
        return min(matches, key=lambda pos: _manhattan(position, pos))

    def _nearest_unowned_supply_center(
        self,
        s: DiplomacyAgentState,
        position: tuple[int, int],
        home_country: str,
    ) -> tuple[int, int] | None:
        candidates = [
            entity
            for entity in s.known_entities.values()
            if entity.type == "supply_center" and entity.inventory.get(home_country, 0) <= 0
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda entity: (
                sum(entity.inventory.get(country, 0) for country in COUNTRIES) > 0,
                _manhattan(position, entity.position),
            ),
        ).position

    def _nearest_incident_hub(
        self,
        s: DiplomacyAgentState,
        home_hub: str,
        position: tuple[int, int],
    ) -> str | None:
        incident_hubs = [
            entity
            for entity in s.known_entities.values()
            if entity.type.endswith("_hub")
            and entity.inventory.get("incident_pending", 0) > 0
            and entity.inventory.get("incident_window", 0) > 0
        ]
        if not incident_hubs:
            return None
        home = [entity for entity in incident_hubs if entity.type == home_hub]
        if home:
            return home_hub
        nearest = min(incident_hubs, key=lambda entity: _manhattan(position, entity.position))
        return nearest.type

    @staticmethod
    def _foreign_hub(home_country: str, salt: int) -> str:
        foreign = [country for country in COUNTRIES if country != home_country]
        return f"{foreign[salt % len(foreign)]}_hub"

    def _heard_foreign_hub(self, obs: DiplomacyObservation, home_country: str) -> str | None:
        for talk in obs.visible_talk:
            if talk.agent_id == self._agent_id:
                continue
            talk_country = COUNTRIES[talk.agent_id % len(COUNTRIES)]
            if talk_country == home_country:
                continue
            named_target = self._mentioned_hub_from_talk_text(talk.text)
            if named_target is not None:
                return named_target
            return f"{talk_country}_hub"
        return None

    def _heard_named_target_hub(self, obs: DiplomacyObservation, home_country: str) -> str | None:
        for talk in obs.visible_talk:
            if talk.agent_id == self._agent_id:
                continue
            talk_country = COUNTRIES[talk.agent_id % len(COUNTRIES)]
            if talk_country == home_country:
                continue
            named_target = self._mentioned_hub_from_talk_text(talk.text)
            if named_target is not None:
                return named_target
        return None

    @staticmethod
    def _rival_target_hub(home_country: str) -> str:
        for target_country, rival_country in RIVAL_COUNTRY_BY_TARGET.items():
            if rival_country == home_country:
                return f"{target_country}_hub"
        return f"{COUNTRIES[0]}_hub"

    def _default_discussion_target(self, obs: DiplomacyObservation, s: DiplomacyAgentState) -> str:
        home_country = self._active_country(obs, s)
        if s.style in {"saboteur", "raider"}:
            return self._rival_target_hub(home_country)
        if s.style in {"diplomat", "trader"}:
            return self._heard_foreign_hub(obs, home_country) or self._foreign_hub(home_country, s.agent_id)
        return f"{home_country}_hub"

    def _update_discussion_agenda(self, obs: DiplomacyObservation, s: DiplomacyAgentState) -> None:
        in_discussion = obs.global_obs.get("phase_discussion", 0) > 0
        home_country = self._active_country(obs, s)
        home_hub = f"{home_country}_hub"
        if in_discussion and not s.was_in_discussion_phase:
            s.discussion_messages_sent = 0
            s.post_discussion_target = None
            s.pending_talk_override = None
            s.discussion_source = "scripted"
            s.discussion_steps_in_window = 0
        if in_discussion:
            s.discussion_steps_in_window += 1
        else:
            s.discussion_steps_in_window = 0
        if s.post_discussion_target is None and (in_discussion or s.was_in_discussion_phase):
            s.post_discussion_target = self._default_discussion_target(obs, s)
        heard_target = self._heard_named_target_hub(obs, home_country) if in_discussion else None
        if heard_target == home_hub:
            if s.post_discussion_target != home_hub:
                s.post_discussion_target = home_hub
            if s.discussion_source == "scripted":
                s.discussion_source = "heard_talk"
        elif heard_target is not None and s.style in {"diplomat", "trader"}:
            if s.post_discussion_target != heard_target:
                s.post_discussion_target = heard_target
            if s.discussion_source == "scripted":
                s.discussion_source = "heard_talk"
        s.was_in_discussion_phase = in_discussion

    def _choose_target_type(self, obs: DiplomacyObservation, s: DiplomacyAgentState) -> str:
        home_country = self._active_country(obs, s)
        home_hub = f"{home_country}_hub"

        if not self._has_country(obs):
            return f"{s.assigned_country}_station"

        influence = obs.inventory.get("influence", 0)
        sabotage_kit = obs.inventory.get("sabotage_kit", 0)
        intel = obs.inventory.get("intel", 0)
        power_cell = obs.inventory.get("power_cell", 0)
        defeat_margin = obs.global_obs.get("defeat_margin", 0)
        incident_pending_total = obs.global_obs.get("incident_pending", 0)
        incident_hub = self._nearest_incident_hub(s, home_hub, obs.position)
        phase_discussion = obs.global_obs.get("phase_discussion", 0) > 0
        phase_orders = obs.global_obs.get("phase_orders", 0) > 0
        phase_retreat = obs.global_obs.get("phase_retreat", 0) > 0
        phase_adjustment = obs.global_obs.get("phase_adjustment", 0) > 0
        season_fall = obs.global_obs.get("season_fall", 0) > 0
        unowned_center = self._nearest_unowned_supply_center(s, obs.position, home_country)
        discussion_target = s.post_discussion_target or home_hub
        foreign_discussion_target = discussion_target.endswith("_hub") and discussion_target != home_hub
        stable_enough_for_foreign_hub = incident_pending_total <= 0 and defeat_margin <= 0

        if phase_discussion:
            if s.discussion_steps_in_window <= 3:
                return "diplomacy_station"
            if sabotage_kit > 0 and s.style in {"saboteur", "raider"} and s.discussion_messages_sent >= 1:
                return self._rival_target_hub(home_country)
            if s.discussion_messages_sent < 2 and not obs.visible_talk and s.discussion_steps_in_window <= 5:
                return "diplomacy_station"
            if discussion_target.endswith("_hub"):
                return discussion_target if not foreign_discussion_target or stable_enough_for_foreign_hub else home_hub
            return "diplomacy_station"

        if (
            influence > 0
            and discussion_target.endswith("_hub")
            and (not foreign_discussion_target or stable_enough_for_foreign_hub)
        ):
            return discussion_target

        if (
            intel > 0
            and s.style in {"diplomat", "trader"}
            and discussion_target.endswith("_hub")
            and (not foreign_discussion_target or stable_enough_for_foreign_hub)
        ):
            return discussion_target

        if phase_adjustment:
            if incident_hub is not None and influence > 0:
                return incident_hub
            if influence > 0 or intel > 0 or sabotage_kit > 0:
                return home_hub

        if (
            season_fall
            and phase_orders
            and unowned_center is not None
            and s.style != "saboteur"
            and influence <= 0
            and intel <= 0
            and sabotage_kit <= 0
        ):
            return "supply_center"

        if phase_retreat:
            if incident_hub is not None and influence > 0:
                return incident_hub
            if sabotage_kit > 0:
                return home_hub

        if sabotage_kit > 0:
            if s.style in {"saboteur", "raider"}:
                rival_hub = self._rival_target_hub(home_country)
                if self._nearest_known_position(s, rival_hub, obs.position) is not None:
                    return rival_hub
                return self._foreign_hub(home_country, s.step + s.agent_id)
            return home_hub

        if influence > 0:
            if incident_hub is not None:
                return incident_hub
            if incident_pending_total > 0 and s.style not in {"saboteur", "raider"}:
                return home_hub
            if s.style in {"saboteur", "raider"}:
                return self._foreign_hub(home_country, s.step + s.agent_id)
            if s.style == "trader":
                return home_hub if s.step % 2 == 0 else self._foreign_hub(home_country, s.step)
            return home_hub if s.step % 3 else self._foreign_hub(home_country, s.step)

        if intel > 0:
            if incident_pending_total > 0 and s.style not in {"saboteur", "raider"}:
                return "diplomacy_station"
            if s.style in {"saboteur", "raider"}:
                return "sabotage_station"
            if s.style == "responder" and (incident_hub is not None or incident_pending_total > 0):
                return "diplomacy_station"
            if s.style == "diplomat":
                return "diplomacy_station"
            if defeat_margin > 0 or s.style == "trader":
                return home_hub
            return "diplomacy_station" if s.step % 4 else home_hub

        if power_cell > 0:
            return "comms_station"

        return "reactor_station"

    def _move_toward(
        self,
        current: tuple[int, int],
        target: tuple[int, int],
        s: DiplomacyAgentState,
    ) -> str:
        row_delta = target[0] - current[0]
        col_delta = target[1] - current[1]
        if row_delta == 0 and col_delta == 0:
            return "noop"

        priorities: list[str] = []
        if abs(row_delta) >= abs(col_delta):
            if row_delta < 0:
                priorities.append("move_north")
            elif row_delta > 0:
                priorities.append("move_south")
            if col_delta < 0:
                priorities.append("move_west")
            elif col_delta > 0:
                priorities.append("move_east")
        else:
            if col_delta < 0:
                priorities.append("move_west")
            elif col_delta > 0:
                priorities.append("move_east")
            if row_delta < 0:
                priorities.append("move_north")
            elif row_delta > 0:
                priorities.append("move_south")

        for move in _MOVE_ACTIONS:
            if move not in priorities:
                priorities.append(move)

        if s.stuck_steps > 0:
            rotate = s.stuck_steps % len(_MOVE_ACTIONS)
            priorities = priorities[rotate:] + priorities[:rotate]

        for move in priorities:
            if move in self._action_names:
                return move
        return "noop"

    def _explore_action(self, position: tuple[int, int], s: DiplomacyAgentState) -> str:
        if _manhattan(position, _SPAWN_POS) > 22:
            return self._move_toward(position, _SPAWN_POS, s)
        waypoint_index = (s.step // 14 + s.agent_id + s.stuck_steps) % len(_EXPLORE_WAYPOINTS)
        row_delta, col_delta = _EXPLORE_WAYPOINTS[waypoint_index]
        waypoint = (_SPAWN_POS[0] + row_delta, _SPAWN_POS[1] + col_delta)
        return self._move_toward(position, waypoint, s)

    @staticmethod
    def _phase_label(global_obs: dict[str, int]) -> str:
        season = "Spring" if global_obs.get("season_spring", 0) >= global_obs.get("season_fall", 0) else "Fall"
        phase_orders = global_obs.get("phase_orders", 0)
        phase_retreat = global_obs.get("phase_retreat", 0)
        phase_adjustment = global_obs.get("phase_adjustment", 0)
        phase = "Orders"
        if global_obs.get("phase_discussion", 0) > 0:
            phase = "Discussion"
        elif phase_adjustment > max(phase_orders, phase_retreat):
            phase = "Winter Adjustments"
        elif phase_retreat > phase_orders:
            phase = "Retreats"
        return f"{season} {phase}"

    def _talk_ready(self, s: DiplomacyAgentState) -> bool:
        if not self._talk_enabled:
            return False
        if s.last_sent_talk_step is None:
            return True
        return (s.step - s.last_sent_talk_step) >= self._talk_cooldown_steps

    @staticmethod
    def _country_short_name(country: str) -> str:
        return country.removeprefix("country_").upper()

    def _hub_country_short_name(self, hub_type: str) -> str:
        return self._country_short_name(hub_type.removesuffix("_hub"))

    @staticmethod
    def _mentioned_hub_from_talk_text(text: str) -> str | None:
        body = text.split(":", 1)[1] if ":" in text else text
        for pattern in _TALK_TARGET_PATTERNS:
            matches = []
            for match in pattern.finditer(body):
                context = body[max(0, match.start() - 24) : match.start()].lower()
                if any(negation in context for negation in _NEGATED_TALK_CONTEXT):
                    continue
                country_short = match.group("hub") or match.group("short")
                if country_short is not None:
                    matches.append(country_short.upper())
            if matches:
                return _COUNTRY_SHORT_TO_HUB[matches[-1]]
        return None

    def _discussion_talk(
        self,
        obs: DiplomacyObservation,
        s: DiplomacyAgentState,
        target_type: str,
    ) -> str | None:
        if not self._talk_ready(s):
            return None
        if obs.global_obs.get("phase_discussion", 0) <= 0:
            return None
        if s.pending_talk_override is not None:
            message = s.pending_talk_override[: self._talk_max_length].strip() or None
            s.pending_talk_override = None
            return message

        country = self._active_country(obs, s)
        country_short = self._country_short_name(country)
        discussion_target = s.post_discussion_target or self._default_discussion_target(obs, s)
        target_short = self._hub_country_short_name(discussion_target) if discussion_target.endswith("_hub") else None
        heard_target = self._heard_foreign_hub(obs, country)
        heard_named_target = self._heard_named_target_hub(obs, country)
        heard_short = self._hub_country_short_name(heard_target) if heard_target is not None else None
        heard_named_short = self._hub_country_short_name(heard_named_target) if heard_named_target is not None else None
        max_messages = 3 if s.style in {"diplomat", "trader"} else 2
        if s.discussion_messages_sent >= max_messages:
            return None

        if s.discussion_messages_sent == 0 and heard_short is None and s.style in {"responder", "engineer"}:
            return None

        if heard_short == country_short and target_short == country_short:
            message = f"{country_short}: heard pressure on {country_short}. Holding {country_short}."
        elif heard_named_short is not None and target_short == country_short:
            message = f"{country_short}: heard {heard_named_short}. Holding {country_short}."
        elif heard_named_target == discussion_target and s.discussion_messages_sent > 0:
            message = f"{country_short}: heard {heard_short}. Leaving summit for {target_short}."
        elif heard_named_target == discussion_target:
            message = f"{country_short}: heard {heard_short}. I will move on {target_short}."
        elif target_type == "supply_center":
            message = f"{country_short}: contesting the frontier center. Need support."
        elif discussion_target.endswith("_hub") and s.style in {"saboteur", "raider"}:
            message = f"{country_short}: summit first, then pressure {target_short}."
        elif discussion_target.endswith("_hub") and target_short != country_short:
            message = f"{country_short}: summit first. I will carry terms to {target_short}."
        elif target_type == "diplomacy_station":
            message = f"{country_short}: summit first. Share plans before orders."
        elif discussion_target.endswith("_hub"):
            message = f"{country_short}: stabilizing {target_short}. Hold the line."
        else:
            message = f"{country_short}: moving to summit. Share intentions."
        return message[: self._talk_max_length].strip() or None

    @staticmethod
    def _leader_label(global_obs: dict[str, int]) -> str:
        centers = {country: global_obs.get(f"{country}.centers", 0) for country in COUNTRIES}
        leader = max(COUNTRIES, key=lambda country: (centers[country], country))
        short = leader.removeprefix("country_").upper()
        return f"{short} ({centers[leader]} centers)"

    @staticmethod
    def _center_snapshot(global_obs: dict[str, int]) -> tuple[int, int, int]:
        return tuple(global_obs.get(f"{country}.centers", 0) for country in COUNTRIES)

    @staticmethod
    def _phase_overlay(global_obs: dict[str, int], phase_label: str) -> str:
        campaign_year = int(global_obs.get("campaign_year", 1901))
        if phase_label.endswith("Discussion"):
            detail = "Summit open. Agents are still negotiating before the next push."
        elif phase_label.endswith("Orders"):
            detail = "Orders are live. Fall Orders is the only phase where supply centers can change hands."
        elif phase_label.endswith("Retreats"):
            detail = "Capture pressure is paused while the front resets."
        else:
            detail = "Controlled centers convert into winter stability."
        return f"{campaign_year} {phase_label}\n{detail}"

    @staticmethod
    def _capture_overlay(previous: tuple[int, int, int], current: tuple[int, int, int]) -> str | None:
        changes = []
        for country, before, after in zip(COUNTRIES, previous, current, strict=True):
            delta = after - before
            if delta == 0:
                continue
            changes.append(f"{country.removeprefix('country_').upper()} {delta:+d}")
        if not changes:
            return None
        return "Supply Center Captured\n" + "  ".join(changes)

    def _select_action(
        self,
        obs: DiplomacyObservation,
        s: DiplomacyAgentState,
    ) -> tuple[str, str, tuple[int, int] | None]:
        target_type = self._choose_target_type(obs, s)
        target_pos = self._nearest_known_position(s, target_type, obs.position)
        if target_pos is None:
            target_pos = self._anchored_target_position(
                s,
                target_type,
                obs.position,
                self._active_country(obs, s),
            )
        if target_pos is None:
            if target_type.endswith("_station"):
                fallback_pos = self._nearest_known_worksite(s, obs.position)
                if fallback_pos is not None:
                    return self._move_toward(obs.position, fallback_pos, s), target_type, fallback_pos
            return self._explore_action(obs.position, s), "explore", None
        return self._move_toward(obs.position, target_pos, s), target_type, target_pos

    def step_with_state(self, obs: AgentObservation, s: DiplomacyAgentState) -> tuple[Action, DiplomacyAgentState]:
        s.step += 1
        parsed_obs = self._parse_observation(obs, s)

        moved_last_step = s.last_action.startswith("move_")
        if moved_last_step and parsed_obs.position == s.last_position:
            s.stuck_steps += 1
        else:
            s.stuck_steps = 0

        self._update_memory(parsed_obs, s)
        self._update_discussion_agenda(parsed_obs, s)

        candidate, target_type, target_pos = self._select_action(parsed_obs, s)
        action_name = candidate if candidate in self._action_names else "noop"
        talk_text = self._discussion_talk(parsed_obs, s, target_type)
        current_country = self._active_country(parsed_obs, s)
        phase_label = self._phase_label(parsed_obs.global_obs)
        center_snapshot = self._center_snapshot(parsed_obs.global_obs)
        target_delta = None
        if target_pos is not None:
            target_delta = [target_pos[0] - parsed_obs.position[0], target_pos[1] - parsed_obs.position[1]]
        self._infos = {
            "country": current_country,
            "style": s.style,
            "phase": phase_label,
            "objective": target_type.replace("_", " "),
            "discussion_target": s.post_discussion_target.replace("_", " ") if s.post_discussion_target else "",
            "discussion_source": s.discussion_source,
            "leader": self._leader_label(parsed_obs.global_obs),
            "discussion_phase": int(parsed_obs.global_obs.get("phase_discussion", 0) > 0),
            "visible_talk_count": len(parsed_obs.visible_talk),
            "campaign_year": parsed_obs.global_obs.get("campaign_year", 0),
            "win_score": parsed_obs.global_obs.get("win_score", 0),
            "defeat_pressure": parsed_obs.global_obs.get("defeat_pressure", 0),
            "centers": (
                f"A={parsed_obs.global_obs.get('country_a.centers', 0)} "
                f"B={parsed_obs.global_obs.get('country_b.centers', 0)} "
                f"C={parsed_obs.global_obs.get('country_c.centers', 0)}"
            ),
        }
        if target_delta is not None:
            assert target_pos is not None
            self._infos["target"] = target_delta
            self._infos["target_position"] = [target_pos[0], target_pos[1]]
        if parsed_obs.visible_talk:
            self._infos["latest_visible_talk"] = parsed_obs.visible_talk[0].text
            self._infos["latest_visible_talk_agent_id"] = parsed_obs.visible_talk[0].agent_id
        heard_target = self._heard_named_target_hub(parsed_obs, current_country)
        if heard_target is not None:
            self._infos["heard_discussion_target"] = heard_target.replace("_", " ")
        if talk_text is not None:
            self._infos["talk"] = talk_text
        overlay = None
        if phase_label != s.last_phase_label:
            overlay = self._phase_overlay(parsed_obs.global_obs, phase_label)
        elif s.last_center_snapshot is not None and center_snapshot != s.last_center_snapshot:
            overlay = self._capture_overlay(s.last_center_snapshot, center_snapshot)
        if overlay is not None:
            self._infos["tutorial_overlay"] = overlay
        if s.step == 1:
            self._infos["tutorial_overlay_phases"] = list(_TUTORIAL_OVERLAY_PHASES)

        s.last_action = action_name
        s.last_position = parsed_obs.position
        s.last_phase_label = phase_label
        s.last_center_snapshot = center_snapshot
        if talk_text is not None:
            s.discussion_messages_sent += 1
            s.last_sent_talk_step = s.step
        return Action(name=action_name, talk=talk_text), s


class DiplomacyPolicy(MultiAgentPolicy):
    """Scripted multi-agent baseline for Diplomacog missions."""

    short_names = ["diplomacog_agent"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs: object) -> None:
        super().__init__(policy_env_info, device=device)
        self._feature_by_id = {f.id: f for f in policy_env_info.obs_features}
        self._action_map = policy_env_info.action_name_to_flat_index
        self._noop = dtype_actions.type(self._action_map["noop"])
        self._agents: dict[int, StatefulAgentPolicy[DiplomacyAgentState]] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[DiplomacyAgentState]:
        if agent_id not in self._agents:
            brain = DiplomacyBrain(self._policy_env_info, agent_id)
            self._agents[agent_id] = StatefulAgentPolicy(brain, self._policy_env_info, agent_id=agent_id)
        return self._agents[agent_id]

    def step_batch(self, raw_obs: np.ndarray, raw_actions: np.ndarray) -> None:
        raw_actions[...] = self._noop
        n = min(raw_obs.shape[0], self._policy_env_info.num_agents)
        for aid in range(n):
            obs = self._raw_to_obs(aid, raw_obs[aid])
            action = self.agent_policy(aid).step(obs)
            raw_actions[aid] = dtype_actions.type(self._action_map[action.name])

    def _raw_to_obs(self, aid: int, raw: np.ndarray) -> AgentObservation:
        tokens: list[ObservationToken] = []
        for tok in raw:
            fid = int(tok[1])
            if fid == 0xFF:
                break
            feature = self._feature_by_id.get(fid)
            if feature is None:
                continue
            tokens.append(
                ObservationToken(
                    feature=feature,
                    value=int(tok[2]),
                    raw_token=(int(tok[0]), fid, int(tok[2])),
                )
            )
        return AgentObservation(agent_id=aid, tokens=tokens)
