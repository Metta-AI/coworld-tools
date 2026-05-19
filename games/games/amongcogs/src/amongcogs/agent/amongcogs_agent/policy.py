"""Scripted policy for the Among Us station-task game."""

from __future__ import annotations

import math
import random
import re
from collections import deque
from typing import Callable

from amongcogs.constants import (
    CRITICAL_STATION_NAMES,
    INTERACTIVE_STATION_NAMES,
    LIGHTS_CREW_VISION_RADIUS,
    TASK_STATION_NAMES,
    VENT_STATION_NAMES,
)
from amongcogs.game import (
    VIBE_CALL_MEETING,
    VIBE_KILL,
    VIBE_REPORT,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_OXYGEN,
    VIBE_SABOTAGE_REACTOR,
    VIBE_VOTE_SKIP,
    named_vote_target_count,
    vote_target_vibe,
)
from amongcogs.runtime import make_game
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation
from mettagrid.simulator.simulator import Simulation

from .obs_parser import AmongUsState, ObsParser, VisibleEntity

TASK_STATION_TYPES = set(TASK_STATION_NAMES)
CRITICAL_STATION_TYPES = set(CRITICAL_STATION_NAMES)
EMERGENCY_BUTTON = "emergency_button"
SECURITY_STATION = "security_station"
ADMIN_STATION = "admin_station"
COMMS_STATION = "comms_station"
AGENT_TYPE = "agent"
INTERACTIVE_STATION_TYPES = set(INTERACTIVE_STATION_NAMES)
VENT_STATION_TYPES = set(VENT_STATION_NAMES)
INFO_PATROL_STATIONS = (SECURITY_STATION, ADMIN_STATION, COMMS_STATION)
SABOTAGE_VIBES = (
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_OXYGEN,
    VIBE_SABOTAGE_REACTOR,
)
SAFE_EARLY_SABOTAGE_VIBES = (
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_COMMS,
)
EARLY_CRITICAL_SABOTAGE_UNLOCK_STEP = 36

MOVE_ACTIONS = {
    "north": "move_north",
    "south": "move_south",
    "west": "move_west",
    "east": "move_east",
}
MOVE_DELTAS = {
    "north": (-1, 0),
    "south": (1, 0),
    "west": (0, -1),
    "east": (0, 1),
}
EXPLORE_BIAS = [
    ["north", "east", "south", "west"],
    ["east", "south", "west", "north"],
    ["south", "west", "north", "east"],
    ["west", "north", "east", "south"],
]
EARLY_TASK_FOCUS_STEPS = 24
AGENT_REF_RE = re.compile(r"\bagent[- ]?(\d+)\b")
BODY_LOCATION_MAX_DISTANCE = 8
STATION_LOCATION_LABELS = {
    "emergency_button": "Cafeteria",
    "crew_station": "Cafeteria",
    "impostor_station": "Cafeteria",
    "wiring_station": "Electrical",
    "lights_station": "Electrical",
    "reactor_station": "Reactor",
    "navigation_station": "Navigation",
    "oxygen_station": "O2",
    "admin_station": "Admin",
    "medbay_station": "MedBay",
    "weapons_station": "Weapons",
    "shields_station": "Shields",
    "comms_station": "Communications",
    "security_station": "Security",
}


class AmongUsAgent(AgentPolicy):
    """Single-agent scripted behavior with lightweight map memory."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        desired_role: str,
        static_known: dict[tuple[int, int], VisibleEntity],
        spawn_pos: tuple[int, int],
    ) -> None:
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._targetable_count = named_vote_target_count(policy_env_info.num_agents)
        self._desired_role = desired_role
        self._static_known = static_known
        self._spawn_pos = spawn_pos
        self._parser = ObsParser(policy_env_info)
        self._rng = random.Random(1000 + agent_id)
        self._known: dict[tuple[int, int], VisibleEntity] = {}
        self._min_row = min(pos[0] for pos in static_known)
        self._max_row = max(pos[0] for pos in static_known)
        self._min_col = min(pos[1] for pos in static_known)
        self._max_col = max(pos[1] for pos in static_known)
        self._reset_runtime_state()

    def _reset_runtime_state(self) -> None:
        self._step = 0
        self._position = self._spawn_pos
        self._last_position = self._spawn_pos
        self._last_action = "noop"
        self._stuck_steps = 0
        self._clear_intent_next_step = False
        self._last_kill_cooldown = math.inf
        self._post_kill_vent_steps = 0
        self._direct_corpse_seen_steps = 0
        self._direct_body_suspect_id: int | None = None
        self._direct_body_location: str | None = None
        self._recent_agent_sightings: dict[int, tuple[tuple[int, int], int]] = {}
        self._recent_crew_sightings: dict[int, tuple[tuple[int, int], int]] = {}
        self._info_patrol_station = INFO_PATROL_STATIONS[self._agent_id % len(INFO_PATROL_STATIONS)]
        self._info_patrol_steps = 0
        self._button_patrol_steps = 0
        self._next_sabotage_idx = self._agent_id % len(SABOTAGE_VIBES)
        self._meeting_turn = 0
        self._heard_talk_count = 0
        self._in_meeting = False
        self._meeting_reported_body = False
        self._reset_meeting_memory()

    def _reset_meeting_memory(self) -> None:
        self._meeting_heard_signatures: set[tuple[int, str]] = set()
        self._meeting_speakers: set[int] = set()
        self._meeting_body_claims = 0
        self._meeting_accuse_claims = 0
        self._meeting_skip_claims = 0
        self._meeting_suspect_counts: dict[int, int] = {}

    def reset(self, simulation=None) -> None:  # type: ignore[override]
        self._known = {
            pos: VisibleEntity(
                type_name=entity.type_name,
                tags=set(entity.tags),
                inventory=dict(entity.inventory),
                last_seen=entity.last_seen,
            )
            for pos, entity in self._static_known.items()
        }
        self._reset_runtime_state()

    def step(self, obs: AgentObservation) -> Action:
        self._step += 1
        state, visible = self._parser.parse(obs, self._step, self._spawn_pos)
        self._position = state.position
        self._merge_visible(visible)
        self._direct_corpse_seen_steps = max(0, self._direct_corpse_seen_steps - 1)
        heard_talk = tuple(talk.text.lower() for talk in obs.talk if talk.agent_id != self._agent_id and talk.text)
        self._heard_talk_count = len(heard_talk)
        self._meeting_reported_body = state.meeting_reported_body > 0
        if state.meeting_active > 0 and not self._in_meeting:
            self._reset_meeting_memory()
            if state.meeting_reported_body <= 0:
                self._direct_body_suspect_id = None
                self._direct_body_location = None
        elif state.meeting_active <= 0 and self._in_meeting:
            self._reset_meeting_memory()
            self._direct_body_suspect_id = None
            self._direct_body_location = None
        if state.meeting_active > 0:
            self._meeting_turn = self._meeting_turn + 1 if self._in_meeting else 1
            self._ingest_meeting_talk(obs.talk)
        else:
            self._meeting_turn = 0
        self._in_meeting = state.meeting_active > 0
        if (
            state.role == "impostor"
            and self._step > 2
            and self._last_kill_cooldown <= 1
            and state.kill_cooldown > self._last_kill_cooldown
        ):
            self._post_kill_vent_steps = 12
        self._last_kill_cooldown = state.kill_cooldown

        if self._last_action.startswith("move_") and self._position == self._last_position:
            self._stuck_steps += 1
        else:
            self._stuck_steps = max(0, self._stuck_steps - 1)
        self._last_position = self._position

        action = self._select_action(state=state)
        self._last_action = action.name
        self._infos = {
            "role": state.role or "unset",
            "alive": int(state.is_alive),
            "meeting_active": state.meeting_active,
            "meeting_discussion": state.meeting_discussion,
            "meeting_ballot": state.meeting_ballot,
            "meeting_reported_body": state.meeting_reported_body,
            "meeting_token": state.meeting_token,
            "voted": state.voted,
            "task_progress": state.task_progress,
            "kill_cooldown": state.kill_cooldown,
            "sabotage_cooldown": state.sabotage_cooldown,
            "vent_cooldown": state.vent_cooldown,
            "desired_role": self._desired_role,
            "stuck_steps": self._stuck_steps,
            "known_objects": len(self._known),
            "heard_talk": self._heard_talk_count,
            "meeting_speakers": len(self._meeting_speakers),
            "meeting_body_claims": self._meeting_body_claims,
            "meeting_accuse_claims": self._meeting_accuse_claims,
            "meeting_skip_claims": self._meeting_skip_claims,
            "meeting_suspect": self._crew_meeting_vote_target() if state.role == "crew" else -1,
            "direct_body_suspect": self._direct_body_suspect_id if self._direct_body_suspect_id is not None else -1,
        }
        return action

    def _merge_visible(self, visible: dict[tuple[int, int], VisibleEntity]) -> None:
        # Agents move every step; clear stale agent positions before adding current sightings.
        for pos in [pos for pos, entity in self._known.items() if entity.type_name == AGENT_TYPE]:
            del self._known[pos]
        for pos, entity in visible.items():
            self._known[pos] = entity
            if entity.type_name == AGENT_TYPE and entity.agent_id is not None and entity.inventory.get("alive", 0) > 0:
                self._recent_agent_sightings[entity.agent_id] = (pos, self._step)
                if entity.inventory.get("crew", 0) > 0:
                    self._recent_crew_sightings[entity.agent_id] = (pos, self._step)

    def _select_action(self, state: AmongUsState) -> Action:
        if not state.is_alive:
            return Action(name="noop")
        if state.meeting_active > 0:
            return self._meeting_action(state)
        if self._clear_intent_next_step:
            self._clear_intent_next_step = False
            return Action(name="change_vibe_default")

        role = state.role
        if role is None:
            return Action(name="noop") if self._step <= 2 else self._explore()
        if role == "crew":
            return self._crew_action(state)
        return self._impostor_action(state)

    def _meeting_action(self, state: AmongUsState) -> Action:
        if state.voted > 0:
            return Action(name="noop")
        if state.meeting_discussion > 0:
            return self._meeting_discussion_action(state)
        if state.meeting_ballot > 0 and state.role == "crew":
            suspect_id = self._crew_meeting_vote_target()
            if suspect_id is not None:
                return self._emit_intent(vote_target_vibe(suspect_id), talk=self._meeting_vote_text(suspect_id))
            return self._emit_intent(VIBE_VOTE_SKIP, talk=self._meeting_vote_text(None))
        if state.meeting_ballot > 0 and state.role == "impostor":
            suspect_id = self._impostor_meeting_vote_target()
            if suspect_id is not None:
                return self._emit_intent(vote_target_vibe(suspect_id), talk=self._meeting_vote_text(suspect_id))
            return self._emit_intent(VIBE_VOTE_SKIP, talk=self._meeting_vote_text(None))
        return Action(name="noop")

    def _meeting_discussion_action(self, state: AmongUsState) -> Action:
        button_action = self._navigate_to(lambda e: e.type_name == EMERGENCY_BUTTON, adjacent_ok=True)
        talk = self._meeting_discussion_text(state)
        action_name = "noop" if button_action is None else button_action.name
        return Action(name=action_name, talk=talk)

    def _crew_action(self, state: AmongUsState) -> Action:
        corpse_action = self._crew_corpse_action(state)
        if corpse_action is not None:
            return corpse_action

        if state.task_progress > 0:
            task_action = self._task_station_action()
            if task_action is not None:
                return task_action

        critical_action = self._crew_critical_action(state)
        if critical_action is not None:
            return critical_action

        button_action = self._button_patrol_action(state)
        if button_action is not None:
            return button_action

        if self._step > EARLY_TASK_FOCUS_STEPS and self._info_patrol_station == SECURITY_STATION:
            info_action = self._info_patrol_action(force=self._should_patrol_info_station())
            if info_action is not None:
                return info_action

        task_action = self._task_station_action()
        if task_action is not None:
            return task_action

        info_action = self._info_patrol_action()
        if info_action is not None:
            return info_action

        if state.meeting_token > 0:
            button_action = self._navigate_to(lambda e: e.type_name == EMERGENCY_BUTTON, adjacent_ok=True)
            if button_action is not None:
                if button_action.name == "noop":
                    return self._emit_intent(VIBE_CALL_MEETING, talk="meeting now")
                return button_action

        return self._explore()

    def _impostor_action(self, state: AmongUsState) -> Action:
        hunt_action = self._impostor_hunt_action(state)
        if hunt_action is not None:
            return hunt_action

        if (
            state.sabotage_cooldown <= 0
            and self._nearest(lambda e: e.type_name in CRITICAL_STATION_TYPES and "station:sabotaged" in e.tags) is None
            and self._step >= 10
            and self._step % 6 == self._agent_id % 6
        ):
            return self._emit_intent(self._planned_sabotage_vibe())

        if state.vent_cooldown <= 0:
            vent_action = self._post_kill_vent_action()
            if vent_action is not None:
                return vent_action

        if state.vent_cooldown <= 0 and state.kill_cooldown > 2 and self._step % 55 == (self._agent_id % 11):
            action = self._navigate_to_if_close(lambda e: e.type_name in VENT_STATION_TYPES, max_distance=14)
            if action is not None:
                return action

        hunt_action = self._impostor_hunt_action(state, allow_chase=True)
        if hunt_action is not None:
            return hunt_action

        task_action = self._task_station_action(include_empty=True)
        if task_action is not None:
            return task_action

        return self._explore()

    def _impostor_hunt_action(self, state: AmongUsState, *, allow_chase: bool = False) -> Action | None:
        if state.kill_cooldown > 0 and not allow_chase:
            return None

        target = self._nearest(
            lambda e: e.type_name == AGENT_TYPE
            and e.inventory.get("crew", 0) > 0
            and e.inventory.get("alive", 0) > 0,
        )
        target_pos = target[0] if target is not None else self._recent_crew_target(max_age=36)
        if target_pos is None:
            return None

        if state.kill_cooldown <= 0:
            if _manhattan(self._position, target_pos) <= 1:
                return self._emit_intent(VIBE_KILL, talk="clear target")
            return self._step_toward(target_pos)

        if allow_chase and state.kill_cooldown <= 2:
            return self._step_toward(target_pos)

        return None

    def _recent_crew_target(self, *, max_age: int) -> tuple[int, int] | None:
        candidates: list[tuple[int, int, tuple[int, int]]] = []
        for agent_id, (pos, seen_step) in self._recent_crew_sightings.items():
            if agent_id == self._agent_id:
                continue
            age = self._step - seen_step
            if age <= max_age:
                candidates.append((_manhattan(self._position, pos), age, pos))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _crew_corpse_action(self, state: AmongUsState) -> Action | None:
        nearest_corpse = self._nearest(
            lambda e: e.type_name == AGENT_TYPE and e.inventory.get("corpse", 0) > 0,
            max_distance=self._crew_dynamic_vision_radius(state),
        )
        if nearest_corpse is None:
            return None

        self._direct_corpse_seen_steps = 10
        corpse_pos, corpse_entity = nearest_corpse
        self._direct_body_location = self._body_location_label(corpse_pos)
        self._direct_body_suspect_id = self._nearest_body_suspect_id(corpse_pos, corpse_entity.agent_id)
        if _manhattan(self._position, corpse_pos) <= 2:
            return self._emit_intent(VIBE_REPORT, talk=self._body_report_text())
        return self._step_toward(corpse_pos)

    def _body_location_label(self, corpse_pos: tuple[int, int]) -> str | None:
        candidates: list[tuple[int, str]] = []
        for pos, entity in self._known.items():
            if entity.type_name not in STATION_LOCATION_LABELS:
                continue
            candidates.append((_manhattan(pos, corpse_pos), STATION_LOCATION_LABELS[entity.type_name]))
        if not candidates:
            return None
        candidates.sort()
        distance, label = candidates[0]
        if distance > BODY_LOCATION_MAX_DISTANCE:
            return None
        return label

    def _nearest_body_suspect_id(self, corpse_pos: tuple[int, int], corpse_agent_id: int | None) -> int | None:
        candidates: list[tuple[int, int, int]] = []
        for pos, entity in self._known.items():
            if entity.type_name != AGENT_TYPE or entity.agent_id is None:
                continue
            if (
                entity.agent_id == self._agent_id
                or entity.agent_id == corpse_agent_id
                or entity.agent_id >= self._targetable_count
            ):
                continue
            if entity.inventory.get("alive", 0) <= 0 or entity.inventory.get("corpse", 0) > 0:
                continue
            distance_to_body = _manhattan(pos, corpse_pos)
            if distance_to_body > 4:
                continue
            candidates.append((distance_to_body, _manhattan(self._position, pos), entity.agent_id))
        for agent_id, (pos, seen_step) in self._recent_agent_sightings.items():
            if agent_id == self._agent_id or agent_id == corpse_agent_id or agent_id >= self._targetable_count:
                continue
            age = self._step - seen_step
            if age > 12:
                continue
            distance_to_body = _manhattan(pos, corpse_pos)
            if distance_to_body > 5:
                continue
            candidates.append((distance_to_body, age + 1, agent_id))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _body_report_text(self) -> str:
        prefix = self._body_report_prefix()
        if self._direct_body_suspect_id is None:
            return f"{prefix}. no named suspect."
        return f"{prefix} near Agent {self._direct_body_suspect_id}."

    def _body_report_prefix(self) -> str:
        if self._direct_body_location is None:
            return "body here"
        return f"body in {self._direct_body_location}"

    def _crew_critical_action(self, state: AmongUsState) -> Action | None:
        for station_name, alert_active in (
            ("reactor_station", state.reactor_alert > 0),
            ("oxygen_station", state.oxygen_alert > 0),
            ("lights_station", state.lights_alert > 0),
            (COMMS_STATION, state.comms_alert > 0),
        ):
            if not alert_active:
                continue
            action = self._navigate_to(lambda e, station_name=station_name: e.type_name == station_name)
            if action is not None:
                return action

        return self._navigate_to(
            lambda e: e.type_name in CRITICAL_STATION_TYPES and "station:sabotaged" in e.tags,
        )

    def _button_patrol_action(self, state: AmongUsState) -> Action | None:
        if state.meeting_token <= 0:
            self._button_patrol_steps = 0
            return None
        if self._button_patrol_steps <= 0 and self._agent_id % 4 == 3 and self._step >= 40:
            self._button_patrol_steps = 24
        if self._button_patrol_steps <= 0:
            return None

        self._button_patrol_steps -= 1
        action = self._navigate_to(lambda e: e.type_name == EMERGENCY_BUTTON, adjacent_ok=True)
        if action is None:
            self._button_patrol_steps = 0
            return None
        if action.name == "noop":
            self._button_patrol_steps = 0
            return self._emit_intent(VIBE_CALL_MEETING, talk="meeting now")
        return action

    def _task_station_action(self, *, include_empty: bool = False) -> Action | None:
        assigned_station_names = _rotated_station_names(TASK_STATION_NAMES, self._agent_id)
        for station_name in assigned_station_names:
            action = self._navigate_to(
                lambda e, station_name=station_name: e.type_name == station_name
                and "station:online" in e.tags
                and e.inventory.get("task", 0) > 0
            )
            if action is not None:
                return action

        def has_task(e: VisibleEntity) -> bool:
            return e.type_name in TASK_STATION_TYPES and "station:online" in e.tags and e.inventory.get("task", 0) > 0

        action = self._navigate_to(has_task)
        if action is not None:
            return action

        if include_empty:
            action = self._navigate_to(lambda e: e.type_name in TASK_STATION_TYPES)
            if action is not None:
                return action
        return None

    def _post_kill_vent_action(self) -> Action | None:
        if self._post_kill_vent_steps <= 0:
            return None

        nearest_vent = self._nearest(lambda e: e.type_name in VENT_STATION_TYPES, max_distance=18)
        self._post_kill_vent_steps -= 1
        if nearest_vent is None:
            return None

        vent_pos, _ = nearest_vent
        if _manhattan(self._position, vent_pos) <= 1:
            self._post_kill_vent_steps = 0
        return self._step_toward(vent_pos)

    def _ingest_meeting_talk(self, talks) -> None:
        for talk in talks:
            if talk.agent_id == self._agent_id or not talk.text:
                continue
            self._remember_meeting_utterance(talk.agent_id, talk.text)

    def _remember_meeting_utterance(self, speaker_id: int, text: str) -> None:
        normalized = " ".join(text.lower().split())
        if not normalized:
            return
        signature = (speaker_id, normalized)
        if signature in self._meeting_heard_signatures:
            return
        self._meeting_heard_signatures.add(signature)
        self._meeting_speakers.add(speaker_id)
        if any(token in normalized for token in ("body", "corpse", "report")):
            self._meeting_body_claims += 1
        suspect_ids = _agent_ids_from_text(normalized)
        for suspect_id in suspect_ids:
            if suspect_id != self._agent_id:
                self._meeting_suspect_counts[suspect_id] = self._meeting_suspect_counts.get(suspect_id, 0) + 1
        if "impostor" in normalized or "sus" in normalized or suspect_ids:
            self._meeting_accuse_claims += 1
        if any(token in normalized for token in ("skip", "proof", "no clear suspect")):
            self._meeting_skip_claims += 1

    def _crew_meeting_vote_target(self) -> int | None:
        if (
            self._direct_body_suspect_id is not None
            and self._direct_body_suspect_id != self._agent_id
            and self._direct_body_suspect_id < self._targetable_count
        ):
            return self._direct_body_suspect_id
        return self._most_supported_meeting_suspect()

    def _impostor_meeting_vote_target(self) -> int | None:
        suspect_id = self._most_supported_meeting_suspect()
        if suspect_id is not None and suspect_id != self._agent_id:
            return suspect_id
        return None

    def _most_supported_meeting_suspect(self) -> int | None:
        candidates = [
            (count, -suspect_id, suspect_id)
            for suspect_id, count in self._meeting_suspect_counts.items()
            if suspect_id != self._agent_id and suspect_id < self._targetable_count
        ]
        if not candidates:
            return None
        candidates.sort(reverse=True)
        best_count, _, best_id = candidates[0]
        if len(candidates) > 1 and candidates[1][0] == best_count:
            return None
        return best_id

    def _meeting_discussion_text(self, state: AmongUsState) -> str:
        if state.role == "crew":
            suspect_id = self._crew_meeting_vote_target()
            if suspect_id is not None and self._direct_corpse_seen_steps > 0 and self._meeting_turn > 1:
                return f"{self._meeting_body_prefix()} near Agent {suspect_id}. vote Agent {suspect_id}."
            if suspect_id is not None and self._direct_corpse_seen_steps > 0:
                return f"{self._meeting_body_prefix()} near Agent {suspect_id}."
            if suspect_id is not None and self._meeting_turn > 1:
                return f"best evidence points to Agent {suspect_id}."
            if self._direct_corpse_seen_steps > 0:
                return f"{self._meeting_body_prefix()}. no named suspect."
            if self._meeting_reported_body and self._meeting_turn > 1:
                return "body was reported. no named suspect."
            if self._meeting_reported_body and self._meeting_skip_claims > 0:
                return "body was reported. need more than skip."
            if self._meeting_reported_body:
                return "body was reported. who was nearby?"
            if self._meeting_body_claims > 0 and self._meeting_skip_claims > 0:
                return "heard a report. need more than skip."
            if self._meeting_body_claims > 0:
                return "heard a body report. who was nearby?"
            return "no clear suspect yet."
        if state.role == "impostor":
            if self._meeting_turn <= 1 and self._meeting_body_claims > 0:
                return "where was the body?"
            if self._meeting_turn <= 1:
                return "what did anyone see?"
            if self._meeting_accuse_claims > 0:
                return "one claim is not proof."
            if self._meeting_body_claims > 0:
                return "where was the body?"
            return "skip unless we have proof."
        return "discuss first."

    def _meeting_body_prefix(self) -> str:
        if self._direct_body_location is None:
            return "I found the body"
        return f"I found the body in {self._direct_body_location}"

    @staticmethod
    def _meeting_vote_text(suspect_id: int | None) -> str:
        if suspect_id is not None:
            return f"voting Agent {suspect_id}."
        return "skipping for now."

    def _navigate_to(self, predicate: Callable[[VisibleEntity], bool], *, adjacent_ok: bool = False) -> Action | None:
        nearest = self._nearest(predicate)
        if nearest is None:
            return None

        target_pos, _ = nearest
        if adjacent_ok and _manhattan(self._position, target_pos) <= 1:
            return Action(name="noop")
        return self._step_toward(target_pos)

    def _navigate_to_if_close(
        self,
        predicate: Callable[[VisibleEntity], bool],
        *,
        max_distance: int,
        adjacent_ok: bool = False,
    ) -> Action | None:
        nearest = self._nearest(predicate)
        if nearest is None:
            return None

        target_pos, _ = nearest
        if _manhattan(self._position, target_pos) > max_distance:
            return None
        if adjacent_ok and _manhattan(self._position, target_pos) <= 1:
            return Action(name="noop")
        return self._step_toward(target_pos)

    def _nearest(
        self,
        predicate: Callable[[VisibleEntity], bool],
        *,
        max_distance: int | None = None,
    ) -> tuple[tuple[int, int], VisibleEntity] | None:
        candidates: list[tuple[int, int, tuple[int, int], VisibleEntity]] = []
        for pos, entity in self._known.items():
            if not predicate(entity):
                continue
            # Prefer nearby and recently seen objects.
            distance = _manhattan(self._position, pos)
            if max_distance is not None and distance > max_distance:
                continue
            age = self._step - entity.last_seen
            candidates.append((distance, age, pos, entity))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1], x[2][0], x[2][1]))
        ranked_candidates = [
            (distance, age, self._rng.randint(0, 1000), pos, entity) for distance, age, pos, entity in candidates
        ]
        ranked_candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3][0], x[3][1]))
        _, _, _, pos, entity = ranked_candidates[0]
        return pos, entity

    @staticmethod
    def _crew_dynamic_vision_radius(state: AmongUsState) -> int | None:
        if state.role == "crew" and state.lights_alert > 0:
            return LIGHTS_CREW_VISION_RADIUS
        return None

    def _should_patrol_info_station(self) -> bool:
        patrol_period = 30 if self._info_patrol_station == SECURITY_STATION else 45
        patrol_offset = (self._agent_id % len(INFO_PATROL_STATIONS)) * 5
        return self._step > 24 and (self._step - patrol_offset) % patrol_period == 0

    def _info_patrol_action(self, *, force: bool = False) -> Action | None:
        if force or self._should_patrol_info_station():
            self._info_patrol_steps = 20 if self._info_patrol_station == SECURITY_STATION else 14
        if self._info_patrol_steps <= 0:
            return None

        self._info_patrol_steps -= 1
        nearest = self._nearest(lambda e: e.type_name == self._info_patrol_station, max_distance=48)
        if nearest is None:
            self._info_patrol_steps = 0
            return None

        target_pos, _ = nearest
        if _manhattan(self._position, target_pos) <= 1:
            self._info_patrol_steps = 0
        return self._step_toward(target_pos)

    def _step_toward(self, target: tuple[int, int]) -> Action:
        path_action = self._path_step_toward(target)
        if path_action is not None:
            return path_action

        directions = list(MOVE_DELTAS.items())
        self._rng.shuffle(directions)
        directions.sort(key=lambda entry: _manhattan(_apply_delta(self._position, entry[1]), target))

        current_distance = _manhattan(self._position, target)
        for direction, delta in directions:
            next_pos = _apply_delta(self._position, delta)
            if self._is_wall(next_pos):
                continue
            next_distance = _manhattan(next_pos, target)
            if next_distance <= current_distance or current_distance <= 1:
                return Action(name=MOVE_ACTIONS[direction])

        for direction, delta in directions:
            next_pos = _apply_delta(self._position, delta)
            if not self._is_wall(next_pos):
                return Action(name=MOVE_ACTIONS[direction])

        return Action(name="noop")

    def _path_step_toward(self, target: tuple[int, int]) -> Action | None:
        if self._position == target:
            return None

        queue: deque[tuple[int, int]] = deque([self._position])
        first_step: dict[tuple[int, int], str] = {}
        visited = {self._position}

        while queue:
            current = queue.popleft()
            directions = list(MOVE_DELTAS.items())
            self._rng.shuffle(directions)
            directions.sort(key=lambda entry: _manhattan(_apply_delta(current, entry[1]), target))

            for direction, delta in directions:
                next_pos = _apply_delta(current, delta)
                if next_pos in visited or self._is_path_blocked(next_pos, target) or not self._in_bounds(next_pos):
                    continue
                visited.add(next_pos)
                first_step[next_pos] = first_step.get(current, MOVE_ACTIONS[direction])
                if next_pos == target:
                    return Action(name=first_step[next_pos])
                queue.append(next_pos)

        return None

    def _explore(self) -> Action:
        order = list(EXPLORE_BIAS[self._agent_id % len(EXPLORE_BIAS)])
        if self._stuck_steps >= 2:
            order = order[1:] + order[:1]
            self._rng.shuffle(order)

        for direction in order:
            delta = MOVE_DELTAS[direction]
            next_pos = _apply_delta(self._position, delta)
            if not self._is_wall(next_pos):
                return Action(name=MOVE_ACTIONS[direction])

        return Action(name="noop")

    def _is_wall(self, pos: tuple[int, int]) -> bool:
        entity = self._known.get(pos)
        return entity is not None and entity.type_name == "wall"

    def _is_path_blocked(self, pos: tuple[int, int], target: tuple[int, int]) -> bool:
        entity = self._known.get(pos)
        if entity is None:
            return False
        if entity.type_name == "wall":
            return True
        return pos != target and entity.type_name in INTERACTIVE_STATION_TYPES

    def _in_bounds(self, pos: tuple[int, int]) -> bool:
        return self._min_row <= pos[0] <= self._max_row and self._min_col <= pos[1] <= self._max_col

    def _emit_intent(self, vibe_name: str, *, talk: str | None = None) -> Action:
        self._clear_intent_next_step = True
        return Action(name=f"change_vibe_{vibe_name}", talk=talk)

    def _planned_sabotage_vibe(self) -> str:
        vibe = self._sabotage_vibe()
        if self._step < EARLY_CRITICAL_SABOTAGE_UNLOCK_STEP and vibe in {
            VIBE_SABOTAGE_OXYGEN,
            VIBE_SABOTAGE_REACTOR,
        }:
            return SAFE_EARLY_SABOTAGE_VIBES[self._next_sabotage_idx % len(SAFE_EARLY_SABOTAGE_VIBES)]
        return vibe

    def _sabotage_vibe(self) -> str:
        vibe = SABOTAGE_VIBES[self._next_sabotage_idx]
        self._next_sabotage_idx = (self._next_sabotage_idx + 1) % len(SABOTAGE_VIBES)
        return vibe


class AmongThemNotTooDumbAgent(AmongUsAgent):
    """AmongThem nottoodumb task-runner adapted to the AmongCogs action contract."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        desired_role: str,
        static_known: dict[tuple[int, int], VisibleEntity],
        spawn_pos: tuple[int, int],
    ) -> None:
        super().__init__(
            policy_env_info,
            agent_id=agent_id,
            desired_role=desired_role,
            static_known=static_known,
            spawn_pos=spawn_pos,
        )
        self._reset_task_runner_state()

    def reset(self, simulation=None) -> None:  # type: ignore[override]
        super().reset(simulation=simulation)
        self._reset_task_runner_state()

    def step(self, obs: AgentObservation) -> Action:
        action = super().step(obs)
        self._infos.update(
            {
                "nottoodumb_goal": self._task_goal_station_name or "",
                "nottoodumb_task_hold": self._task_hold_steps,
            }
        )
        return action

    def _reset_task_runner_state(self) -> None:
        self._task_goal_station_name: str | None = None
        self._task_hold_steps = 0

    def _crew_action(self, state: AmongUsState) -> Action:
        corpse_action = self._crew_corpse_action(state)
        if corpse_action is not None:
            return corpse_action

        critical_action = self._crew_critical_action(state)
        if critical_action is not None:
            return critical_action

        if self._step > EARLY_TASK_FOCUS_STEPS and self._info_patrol_station == SECURITY_STATION:
            info_action = self._info_patrol_action(force=self._should_patrol_info_station())
            if info_action is not None:
                return info_action

        task_action = self._task_station_action()
        if task_action is not None:
            return task_action

        if state.meeting_token > 0:
            button_action = self._navigate_to(lambda e: e.type_name == EMERGENCY_BUTTON, adjacent_ok=True)
            if button_action is not None:
                if button_action.name == "noop":
                    return self._emit_intent(VIBE_CALL_MEETING, talk="meeting now")
                return button_action

        if self._step > EARLY_TASK_FOCUS_STEPS:
            info_action = self._info_patrol_action(force=self._should_patrol_info_station())
            if info_action is not None:
                return info_action

        return self._explore()

    def _task_station_action(self, *, include_empty: bool = False) -> Action | None:
        if self._task_hold_steps > 0:
            self._task_hold_steps -= 1
            return Action(name="noop")

        if self._task_goal_station_name is not None:
            action = self._action_for_task_station(self._task_goal_station_name, include_empty=include_empty)
            if action is not None:
                return action
            self._task_goal_station_name = None

        nearest = self._nearest(lambda e: self._is_active_task_station(e, include_empty=include_empty))
        if nearest is None:
            return None

        _, entity = nearest
        self._task_goal_station_name = entity.type_name
        return self._action_for_task_station(entity.type_name, include_empty=include_empty)

    def _action_for_task_station(self, station_name: str, *, include_empty: bool) -> Action | None:
        nearest = self._nearest(
            lambda e: e.type_name == station_name and self._is_active_task_station(e, include_empty=include_empty)
        )
        if nearest is None:
            return None

        target_pos, _ = nearest
        if _manhattan(self._position, target_pos) <= 1:
            self._task_hold_steps = 1
        return self._step_toward(target_pos)

    @staticmethod
    def _is_active_task_station(entity: VisibleEntity, *, include_empty: bool) -> bool:
        if entity.type_name not in TASK_STATION_TYPES or "station:online" not in entity.tags:
            return False
        return include_empty or entity.inventory.get("task", 0) > 0


class AmongUsPolicy(MultiAgentPolicy):
    """Scripted policy for Among Us.

    URI: ``metta://policy/amongcogs_agent?impostor_ratio=0.25``
    """

    short_names = ["amongcogs_agent"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        impostor_ratio: float = 0.25,
        **kwargs: object,
    ) -> None:
        super().__init__(policy_env_info, device=device)
        ratio = max(0.05, min(float(impostor_ratio), 0.5))
        num_agents = policy_env_info.num_agents
        impostor_count = max(1, int(round(num_agents * ratio)))
        self._impostor_ids = set(range(impostor_count))
        self._agents: dict[int, AmongUsAgent] = {}
        self._static_known, self._spawn_positions = _build_static_known(num_agents)

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agents:
            desired_role = "impostor" if agent_id in self._impostor_ids else "crew"
            self._agents[agent_id] = AmongUsAgent(
                self._policy_env_info,
                agent_id=agent_id,
                desired_role=desired_role,
                static_known=self._static_known,
                spawn_pos=self._spawn_positions[agent_id],
            )
        return self._agents[agent_id]


class AmongThemNotTooDumbPolicy(AmongUsPolicy):
    """AmongThem nottoodumb-style policy surface for AmongCogs.

    This policy keeps the same observation/action contract as AmongCogs and maps
    the BitWorld reference bot's defaults onto it: one impostor in a 5-player
    lobby, task-first crew movement, button fallback, and evidence-only voting.
    """

    short_names = ["amongthem_nottoodumb", "amongcogs_nottoodumb"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        impostor_ratio: float = 0.2,
        **kwargs: object,
    ) -> None:
        super().__init__(
            policy_env_info,
            device=device,
            impostor_ratio=impostor_ratio,
            **kwargs,
        )

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agents:
            desired_role = "impostor" if agent_id in self._impostor_ids else "crew"
            self._agents[agent_id] = AmongThemNotTooDumbAgent(
                self._policy_env_info,
                agent_id=agent_id,
                desired_role=desired_role,
                static_known=self._static_known,
                spawn_pos=self._spawn_positions[agent_id],
            )
        return self._agents[agent_id]


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _apply_delta(position: tuple[int, int], delta: tuple[int, int]) -> tuple[int, int]:
    return position[0] + delta[0], position[1] + delta[1]


def _rotated_station_names(station_names: tuple[str, ...], agent_id: int) -> tuple[str, ...]:
    start = agent_id % len(station_names)
    return (*station_names[start:], *station_names[:start])


def _agent_ids_from_text(text: str) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(match.group(1)) for match in AGENT_REF_RE.finditer(text)))


def _build_static_known(
    num_agents: int,
) -> tuple[dict[tuple[int, int], VisibleEntity], dict[int, tuple[int, int]]]:
    env = make_game("amongcogs", num_agents=num_agents, max_steps=32)
    sim = Simulation(env, seed=0)
    try:
        tag_names = sim.config.game.id_map().tag_names()
        known: dict[tuple[int, int], VisibleEntity] = {}
        spawn_positions: dict[int, tuple[int, int]] = {}
        for obj in sim.grid_objects(ignore_types=["agent"]).values():
            tags = {tag_names[tag_id] for tag_id in obj.get("tag_ids", [])}
            inventory = {
                key[4:]: int(value) for key, value in obj.items() if isinstance(key, str) and key.startswith("inv:")
            }
            pos = (int(obj.get("r", 0)), int(obj.get("c", 0)))
            known[pos] = VisibleEntity(
                type_name=str(obj.get("type_name", "unknown")),
                tags=tags,
                inventory=inventory,
                last_seen=0,
            )
        for obj in sim.grid_objects(ignore_types=["wall"]).values():
            if obj.get("type_name") != "agent":
                continue
            spawn_positions[int(obj.get("agent_id", 0))] = (int(obj.get("r", 0)), int(obj.get("c", 0)))
        if len(spawn_positions) != num_agents:
            raise AssertionError(f"Expected {num_agents} spawn positions, got {len(spawn_positions)}")
        return known, spawn_positions
    finally:
        sim.close()
