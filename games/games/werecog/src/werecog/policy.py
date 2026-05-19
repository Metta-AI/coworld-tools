"""Scripted baseline policy for Werewolf/Mafia."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation, Location, ObservationToken, VisibleTalk

_CENTER_TAG = "type:agent"
_BELL_TAG = "type:meeting_bell"
_MOVE_ACTIONS = ("move_north", "move_east", "move_south", "move_west")
_AGENT_CALL_PATTERN = re.compile(r"\b(vote|hunt) agent (?P<agent_id>\d+)\b")
_DAY_DISCUSSION_STEPS = 10


@dataclass(frozen=True)
class VisibleEntity:
    location: Location
    tags: frozenset[str]
    inventory: dict[str, int]
    agent_id: int | None


class WerewolfMafiaAgentPolicy(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int) -> None:
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._tag_by_id = policy_env_info.tag_id_to_name
        self._center = Location(policy_env_info.obs_height // 2, policy_env_info.obs_width // 2)
        self._explore_index = agent_id % len(_MOVE_ACTIONS)
        self._last_action = "noop"
        self._step = 0
        self._talk_enabled = policy_env_info.talk.enabled
        self._talk_max_length = policy_env_info.talk.max_length
        self._talk_cooldown_steps = max(1, policy_env_info.talk.cooldown_steps)
        self._next_talk_step = 0
        self._phase = ""
        self._phase_step = 0
        self._day_count = 0
        self._night_count = 0
        self._phase_mentions: dict[str, dict[int, int]] = {
            "vote": defaultdict(int),
            "hunt": defaultdict(int),
        }
        self._directive_objective = ""
        self._directive_target_agent_id: int | None = None
        self._directive_talk: str | None = None

    def step(self, obs: AgentObservation) -> Action:
        self._step += 1
        global_obs = _decode_global(obs.tokens)
        if self._last_action.startswith("move_") and global_obs.get("last_action_move", 1) == 0:
            self._explore_index = (self._explore_index + 1) % len(_MOVE_ACTIONS)

        me, entities = _parse_entities(obs.tokens, self._tag_by_id, self._center)
        inventory = me.inventory
        if inventory.get("alive", 0) < 1:
            return self._set_action("noop", phase=_phase_name(inventory), plan="dead")

        role = _role_name(global_obs)
        packmates = _packmate_ids(global_obs)
        phase = _phase_name(inventory)
        phase_changed = self._advance_phase(phase)
        self._remember_phase_mentions(obs.talk)
        visible_agents = [
            entity for entity in entities if _CENTER_TAG in entity.tags and entity.agent_id != self._agent_id
        ]
        bell = _nearest(self._center, [entity for entity in entities if _BELL_TAG in entity.tags])
        mentioned_votes = self._phase_mentions["vote"]

        if role == "werewolf" and phase == "night":
            candidates = [entity for entity in visible_agents if not _is_packmate(entity, packmates)]
            ranked_targets = _ranked_targets(self._center, candidates, self._phase_mentions["hunt"])
            target = self._directive_target(candidates) or _ranked_target_for_pack(
                self._agent_id, packmates, ranked_targets
            )
            if target is not None:
                return self._set_action(
                    _move_toward(self._center, target.location),
                    phase=phase,
                    plan="hunt",
                    talk=self._preferred_talk(default=self._night_hunt_talk(target, phase_changed=phase_changed)),
                )

        if phase == "day":
            bell_distance = _distance(self._center, bell.location) if bell is not None else None
            if inventory.get("vote_token", 0) < 1:
                if bell is not None:
                    if bell_distance and bell_distance > 1:
                        return self._set_action(
                            _move_toward(self._center, bell.location),
                            phase=phase,
                            plan="rally",
                            talk=self._preferred_talk(default=self._day_talk(None, phase_changed=phase_changed)),
                        )
                    return self._set_action(
                        _move_toward(self._center, bell.location),
                        phase=phase,
                        plan="bell",
                        talk=self._preferred_talk(default=self._day_talk(None, phase_changed=phase_changed)),
                    )
                return self._set_action(
                    self._explore(),
                    phase=phase,
                    plan="search_bell",
                    talk=self._preferred_talk(default=self._day_talk(None, phase_changed=phase_changed)),
                )

            if role == "werewolf":
                candidates = [entity for entity in visible_agents if not _is_packmate(entity, packmates)]
            else:
                candidates = visible_agents

            objective = self._day_objective(role)
            target = self._day_target(
                center=self._center,
                candidates=candidates,
                mentioned_votes=mentioned_votes,
                role=role,
                packmates=packmates,
                objective=objective,
            )
            talk = self._preferred_talk(default=self._day_talk(target, phase_changed=phase_changed))
            if self._phase_step <= _DAY_DISCUSSION_STEPS or objective in {
                "public_discussion",
                "survive_and_observe",
            }:
                return self._day_discussion_action(
                    bell=bell,
                    bell_distance=bell_distance,
                    phase=phase,
                    talk=talk,
                )
            if objective == "blend_in" and target is None:
                return self._day_discussion_action(
                    bell=bell,
                    bell_distance=bell_distance,
                    phase=phase,
                    talk=talk,
                )
            if target is not None:
                return self._set_action(
                    _move_toward(self._center, target.location),
                    phase=phase,
                    plan="accuse",
                    talk=self._preferred_talk(default=self._day_talk(target, phase_changed=phase_changed)),
                )
            if bell is not None and bell_distance and bell_distance > 2:
                return self._set_action(
                    _move_toward(self._center, bell.location),
                    phase=phase,
                    plan="regroup",
                    talk=self._preferred_talk(default=self._day_talk(None, phase_changed=phase_changed)),
                )

        if role == "villager" and phase == "night":
            return self._set_action("noop", phase=phase, plan="sleep")

        return self._set_action(self._explore(), phase=phase, plan="explore")

    def _explore(self) -> str:
        action = _MOVE_ACTIONS[self._explore_index]
        self._explore_index = (self._explore_index + 1) % len(_MOVE_ACTIONS)
        return action

    def _set_action(self, name: str, *, phase: str, plan: str, talk: str | None = None) -> Action:
        self._last_action = name
        self._infos = {
            "phase": phase,
            "phase_step": self._phase_step,
            "day_count": self._day_count,
            "night_count": self._night_count,
            "plan": plan,
        }
        return Action(name=name, talk=self._maybe_talk(talk))

    def _maybe_talk(self, text: str | None) -> str | None:
        if not self._talk_enabled or not text or self._step < self._next_talk_step:
            return None
        normalized = " ".join(text.split()).strip()
        if not normalized:
            return None
        self._next_talk_step = self._step + self._talk_cooldown_steps
        return normalized[: self._talk_max_length]

    def _advance_phase(self, phase: str) -> bool:
        changed = phase != self._phase
        if changed:
            self._phase = phase
            self._phase_step = 0
            self._phase_mentions = {
                "vote": defaultdict(int),
                "hunt": defaultdict(int),
            }
            if phase == "day":
                self._day_count += 1
            else:
                self._night_count += 1
        self._phase_step += 1
        return changed

    def _phase_prefix(self, phase: str, *, phase_changed: bool) -> str:
        if not phase_changed:
            return ""
        count = self._day_count if phase == "day" else self._night_count
        return f"{phase.title()} {count} begins"

    def _day_reason(self, target: VisibleEntity) -> str:
        if target.inventory.get("accusation", 0) > 0:
            return "already has the village watching them"
        if _suspicion(target) > 0:
            return "is carrying visible suspicion"
        if _distance(self._center, target.location) > 4:
            return "stayed away from the bell"
        return "keeps dodging direct questions"

    def _night_reason(self, target: VisibleEntity) -> str:
        if _distance(self._center, target.location) > 4:
            return "is isolated past the square"
        if _suspicion(target) > 0:
            return "already looks exposed"
        return "is separated from the crowd"

    def _day_talk(self, target: VisibleEntity | None, *, phase_changed: bool) -> str:
        prefix = self._phase_prefix("day", phase_changed=phase_changed)
        if target is None:
            message = "crowd the bell and compare stories"
        else:
            message = f"{self._day_reason(target)}, vote agent {target.agent_id}"
        return f"{prefix}, {message}" if prefix else message

    def _night_hunt_talk(self, target: VisibleEntity | None, *, phase_changed: bool) -> str:
        prefix = self._phase_prefix("night", phase_changed=phase_changed)
        if target is None:
            message = "sweep the village edge and stay quiet"
        else:
            message = f"{self._night_reason(target)}, hunt agent {target.agent_id}"
        return f"{prefix}, {message}" if prefix else message

    def apply_strategy(
        self,
        *,
        objective: str | None = None,
        target_agent_id: int | None = None,
        talk: str | None = None,
    ) -> None:
        self._directive_objective = "" if objective is None else objective.strip()
        self._directive_target_agent_id = target_agent_id
        self._directive_talk = _normalize_talk_text(talk)

    def _remember_phase_mentions(self, visible_talk: list[VisibleTalk] | tuple[VisibleTalk, ...]) -> None:
        for utterance in visible_talk:
            if utterance.agent_id == self._agent_id or utterance.remaining_steps != self._talk_cooldown_steps:
                continue
            for match in _AGENT_CALL_PATTERN.finditer(utterance.text.strip().lower()):
                self._phase_mentions[match.group(1)][int(match.group("agent_id"))] += 1

    def _directive_target(self, candidates: list[VisibleEntity]) -> VisibleEntity | None:
        if self._directive_target_agent_id is None:
            return None
        return next(
            (entity for entity in candidates if entity.agent_id == self._directive_target_agent_id),
            None,
        )

    def _day_objective(self, role: str) -> str:
        objective = self._directive_objective.strip().lower()
        if objective == "blend_in" and role != "werewolf":
            return "public_discussion"
        if objective in {
            "public_discussion",
            "public_vote",
            "blend_in",
            "survive_and_observe",
        }:
            return objective
        return ""

    def _day_target(
        self,
        *,
        center: Location,
        candidates: list[VisibleEntity],
        mentioned_votes: dict[int, int],
        role: str,
        packmates: frozenset[int],
        objective: str,
    ) -> VisibleEntity | None:
        if objective in {"public_discussion", "survive_and_observe"}:
            return None
        directive_target = self._directive_target(candidates)
        if objective == "blend_in":
            blend_candidates = (
                [entity for entity in candidates if not _is_packmate(entity, packmates)]
                if role == "werewolf"
                else candidates
            )
            return _blend_in_target(
                center,
                blend_candidates,
                mentioned_votes,
                preferred_agent_id=None if directive_target is None else directive_target.agent_id,
            )
        return directive_target or _consensus_target(center, candidates, mentioned_votes)

    def _day_discussion_action(
        self,
        *,
        bell: VisibleEntity | None,
        bell_distance: int | None,
        phase: str,
        talk: str,
    ) -> Action:
        if bell is not None:
            plan = "rally" if bell_distance and bell_distance > 1 else "discuss"
            return self._set_action(
                _move_toward(self._center, bell.location),
                phase=phase,
                plan=plan,
                talk=talk,
            )
        return self._set_action(self._explore(), phase=phase, plan="search_bell", talk=talk)

    def _preferred_talk(self, *, default: str) -> str:
        return default if self._directive_talk is None else self._directive_talk


class WerewolfMafiaPolicy(MultiAgentPolicy):
    short_names = ["werecog", "werecog_policy"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs: object) -> None:
        del device, kwargs
        super().__init__(policy_env_info)
        self._agents: dict[int, WerewolfMafiaAgentPolicy] = {}

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        policy = self._agents.get(agent_id)
        if policy is None:
            policy = WerewolfMafiaAgentPolicy(self._policy_env_info, agent_id)
            self._agents[agent_id] = policy
        return policy


def _decode_global(tokens: list[ObservationToken] | tuple[ObservationToken, ...]) -> dict[str, int]:
    return _decode_values(token for token in tokens if token.is_global)


def _decode_values(tokens) -> dict[str, int]:
    values: dict[str, dict[int, int]] = defaultdict(dict)
    for token in tokens:
        name = token.feature.name
        match = re.match(r"^(.+):p(\d+)$", name)
        if match:
            base_name = match.group(1)
            power = int(match.group(2))
        else:
            base_name = name
            power = 0
        values[base_name][power] = int(token.value)

    decoded: dict[str, int] = {}
    for name, powers in values.items():
        total = 0
        for power, value in powers.items():
            total += value * (256**power)
        decoded[name] = total
    return decoded


def _parse_entities(
    tokens: list[ObservationToken] | tuple[ObservationToken, ...],
    tag_by_id: dict[int, str],
    center: Location,
) -> tuple[VisibleEntity, list[VisibleEntity]]:
    by_location: dict[Location, list[ObservationToken]] = defaultdict(list)
    for token in tokens:
        if token.location is not None:
            by_location[token.location].append(token)

    me = VisibleEntity(location=center, tags=frozenset({_CENTER_TAG}), inventory={}, agent_id=None)
    entities: list[VisibleEntity] = []
    for location, location_tokens in by_location.items():
        tags = frozenset(tag_by_id[token.value] for token in location_tokens if token.feature.name == "tag")
        inventory = _decode_values(token for token in location_tokens if token.feature.name.startswith("inv:"))
        agent_id = next((int(token.value) for token in location_tokens if token.feature.name == "agent_id"), None)
        entity = VisibleEntity(
            location=location,
            tags=tags,
            inventory={k[4:]: v for k, v in inventory.items()},
            agent_id=agent_id,
        )
        if location == center:
            me = entity
        else:
            entities.append(entity)
    return me, entities


def _phase_name(inventory: dict[str, int]) -> str:
    return "day" if inventory.get("day_phase", 0) >= 1 else "night"


def _role_name(global_obs: dict[str, int]) -> str:
    return "werewolf" if global_obs.get("role_werewolf", 0) >= 1 else "villager"


def _normalize_talk_text(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = " ".join(text.split()).strip()
    return normalized or None


def _packmate_ids(global_obs: dict[str, int]) -> frozenset[int]:
    return frozenset(value - 1 for name, value in global_obs.items() if name.startswith("wolf_pack_") and value > 0)


def _nearest(center: Location, entities: list[VisibleEntity]) -> VisibleEntity | None:
    if not entities:
        return None
    return min(
        entities,
        key=lambda entity: (
            _distance(center, entity.location),
            entity.location.row,
            entity.location.col,
        ),
    )


def _consensus_target(
    center: Location,
    entities: list[VisibleEntity],
    mentioned_counts: dict[int, int],
) -> VisibleEntity | None:
    ranked = _ranked_targets(center, entities, mentioned_counts)
    if not ranked:
        return None
    return ranked[0]


def _blend_in_target(
    center: Location,
    entities: list[VisibleEntity],
    mentioned_counts: dict[int, int],
    *,
    preferred_agent_id: int | None,
) -> VisibleEntity | None:
    supported_entities = [
        entity for entity in entities if entity.agent_id is not None and mentioned_counts.get(entity.agent_id, 0) > 0
    ]
    if not supported_entities:
        return None
    if preferred_agent_id is not None and mentioned_counts.get(preferred_agent_id, 0) > 0:
        preferred_target = next(
            (entity for entity in supported_entities if entity.agent_id == preferred_agent_id),
            None,
        )
        if preferred_target is not None:
            return preferred_target
    return _consensus_target(center, supported_entities, mentioned_counts)


def _ranked_targets(
    center: Location,
    entities: list[VisibleEntity],
    mentioned_counts: dict[int, int] | None = None,
) -> list[VisibleEntity]:
    if not entities:
        return []
    counts = mentioned_counts or {}
    return sorted(
        entities,
        key=lambda entity: (
            -counts.get(-1 if entity.agent_id is None else entity.agent_id, 0),
            -entity.inventory.get("accusation", 0),
            -_suspicion(entity),
            _distance(center, entity.location),
            entity.location.row,
            entity.location.col,
        ),
    )


def _ranked_target_for_pack(
    agent_id: int,
    packmates: frozenset[int],
    ranked_targets: list[VisibleEntity],
) -> VisibleEntity | None:
    if not ranked_targets:
        return None
    target_index = min(_pack_hunt_slot(agent_id, packmates), len(ranked_targets) - 1)
    return ranked_targets[target_index]


def _night_hunt_slots(packmates: frozenset[int]) -> int:
    return max(1, (len(packmates) + 1) // 3)


def _pack_hunt_slot(agent_id: int, packmates: frozenset[int]) -> int:
    pack_ids = sorted({agent_id, *packmates})
    return pack_ids.index(agent_id) % _night_hunt_slots(packmates)


def _highest_suspicion(center: Location, entities: list[VisibleEntity]) -> VisibleEntity | None:
    if not entities:
        return None
    return min(
        entities,
        key=lambda entity: (
            -_suspicion(entity),
            _distance(center, entity.location),
            entity.location.row,
            entity.location.col,
        ),
    )


def _lowest_suspicion(center: Location, entities: list[VisibleEntity]) -> VisibleEntity | None:
    if not entities:
        return None
    return min(
        entities,
        key=lambda entity: (
            _suspicion(entity),
            _distance(center, entity.location),
            entity.location.row,
            entity.location.col,
        ),
    )


def _suspicion(entity: VisibleEntity) -> int:
    return entity.inventory.get("suspicion", 0)


def _is_packmate(entity: VisibleEntity, packmates: frozenset[int]) -> bool:
    return entity.agent_id in packmates


def _distance(a: Location, b: Location) -> int:
    return abs(a.row - b.row) + abs(a.col - b.col)


def _mentioned_agent_counts(obs: AgentObservation, *, directive: str) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for visible_talk in obs.talk:
        for match in _AGENT_CALL_PATTERN.finditer(visible_talk.text.strip().lower()):
            if match.group(1) != directive:
                continue
            counts[int(match.group("agent_id"))] += 1
    return counts


def _move_toward(center: Location, target: Location) -> str:
    row_delta = target.row - center.row
    col_delta = target.col - center.col
    if abs(col_delta) > abs(row_delta) and col_delta != 0:
        return "move_east" if col_delta > 0 else "move_west"
    if row_delta != 0:
        return "move_south" if row_delta > 0 else "move_north"
    if col_delta != 0:
        return "move_east" if col_delta > 0 else "move_west"
    return "noop"


def _move_away(center: Location, target: Location) -> str:
    toward = _move_toward(center, target)
    return {
        "move_north": "move_south",
        "move_south": "move_north",
        "move_east": "move_west",
        "move_west": "move_east",
    }.get(toward, "noop")
