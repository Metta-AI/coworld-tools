from __future__ import annotations

import re

from mettagrid_sdk.games.base import SemanticStateAdapter
from mettagrid_sdk.runtime.observation import ObservationCell, ObservationEnvelope, decode_observation
from mettagrid_sdk.sdk import (
    GridPosition,
    MettagridState,
    SelfState,
    SemanticEntity,
    TeamMemberSummary,
    TeamSummary,
)

_PLAYER_TAG = "type:agent"
_BELL_TAG = "type:meeting_bell"
_CALL_RE = re.compile(r"\b(vote|hunt) agent (?P<agent_id>\d+)\b")


class WerewolfMafiaStateAdapter(SemanticStateAdapter):
    def build_state(self, observation: ObservationEnvelope) -> MettagridState:
        decoded = decode_observation(observation)
        self_cell = decoded.self_cell
        self_inventory = _inventory_from_features(self_cell.features)
        self_agent_id = int(self_cell.features.get("agent_id", observation.raw_observation.agent_id))
        role = _role_from_globals(decoded.global_features)
        phase = _phase_from_inventory(self_inventory)
        packmates = _packmate_ids(decoded.global_features)
        global_x = _global_axis(decoded.global_features, positive="lp:east", negative="lp:west")
        global_y = _global_axis(decoded.global_features, positive="lp:south", negative="lp:north")
        self_state = SelfState(
            entity_id=f"agent-{self_agent_id}",
            entity_type="agent",
            position=GridPosition(x=0, y=0),
            labels=[phase, "alive" if self_inventory.get("alive", 0) > 0 else "dead"],
            attributes={
                "agent_id": self_agent_id,
                "global_x": global_x,
                "global_y": global_y,
                "vote_token": int(self_inventory.get("vote_token", 0)),
                "day_vote_open": int(self_inventory.get("day_vote_open", 0)),
                "night_hunt_open": int(self_inventory.get("night_hunt_open", 0)),
                "alive": int(self_inventory.get("alive", 0)),
                "packmate_count": len(packmates),
            },
            role=role,
            inventory=self_inventory,
            status=_self_status(phase=phase, inventory=self_inventory, role=role),
        )

        visible_entities = [
            _build_entity(
                cell=cell,
                self_agent_id=self_agent_id,
                self_role=role,
                packmates=packmates,
                self_global_x=global_x,
                self_global_y=global_y,
            )
            for cell in decoded.cells
            if (cell.row, cell.col) != (decoded.center_row, decoded.center_col)
            if _include_cell(cell.tags)
        ]
        _attach_visible_talk(
            self_state=self_state,
            visible_entities=visible_entities,
            visible_talk=decoded.observation.talk,
            center_col=decoded.center_col,
            center_row=decoded.center_row,
            self_global_x=global_x,
            self_global_y=global_y,
        )
        visible_entities.sort(key=lambda entity: (entity.position.y, entity.position.x, entity.entity_id))

        team_summary = TeamSummary(
            team_id="werewolves" if role == "werewolf" else "village",
            members=[
                TeamMemberSummary(
                    entity_id=entity.entity_id,
                    role=str(entity.attributes.get("known_role", "player")),
                    position=entity.position,
                    status=list(entity.labels),
                )
                for entity in visible_entities
                if entity.entity_type == "agent" and "packmate" in entity.labels
            ],
            shared_objectives=_shared_objectives(phase=phase, role=role, packmates=packmates),
        )
        return MettagridState(
            game="werecog",
            step=decoded.step,
            self_state=self_state,
            visible_entities=visible_entities,
            team_summary=team_summary,
        )


def _build_entity(
    *,
    cell: ObservationCell,
    self_agent_id: int,
    self_role: str,
    packmates: frozenset[int],
    self_global_x: int,
    self_global_y: int,
) -> SemanticEntity:
    entity_type = _entity_type(cell.tags)
    global_x = self_global_x + cell.x
    global_y = self_global_y + cell.y
    if entity_type == "agent":
        inventory = _inventory_from_features(cell.features)
        agent_id = int(cell.features.get("agent_id", -1))
        labels = ["player", "alive" if inventory.get("alive", 0) > 0 else "dead"]
        attributes: dict[str, str | int | float | bool] = {
            "agent_id": agent_id,
            "alive": int(inventory.get("alive", 0)),
            "vote_token": int(inventory.get("vote_token", 0)),
            "day_vote_open": int(inventory.get("day_vote_open", 0)),
            "night_hunt_open": int(inventory.get("night_hunt_open", 0)),
            "accusation": int(inventory.get("accusation", 0)),
            "suspicion": int(inventory.get("suspicion", 0)),
            "global_x": global_x,
            "global_y": global_y,
        }
        if agent_id == self_agent_id:
            labels.append("self")
        if self_role == "werewolf" and agent_id in packmates:
            labels.extend(["packmate", "friendly"])
            attributes["known_role"] = "werewolf"
        elif _looks_like_call_target(cell.features):
            labels.append("called_out")
        return SemanticEntity(
            entity_id=f"agent-{agent_id}",
            entity_type="agent",
            position=GridPosition(x=cell.x, y=cell.y),
            labels=labels,
            attributes=attributes,
        )
    return SemanticEntity(
        entity_id=f"{entity_type}@{global_x},{global_y}",
        entity_type=entity_type,
        position=GridPosition(x=cell.x, y=cell.y),
        labels=[entity_type],
        attributes={"global_x": global_x, "global_y": global_y},
    )


def _attach_visible_talk(
    *,
    self_state: SelfState,
    visible_entities: list[SemanticEntity],
    visible_talk,
    center_col: int,
    center_row: int,
    self_global_x: int,
    self_global_y: int,
) -> None:
    agents_by_id: dict[int, SemanticEntity] = {}
    agents_by_position: dict[tuple[int, int], SemanticEntity] = {}
    for entity in visible_entities:
        if entity.entity_type != "agent":
            continue
        agent_id = entity.attributes.get("agent_id")
        if isinstance(agent_id, int):
            agents_by_id[agent_id] = entity
        agents_by_position[(entity.position.x, entity.position.y)] = entity

    self_agent_id = self_state.attributes.get("agent_id")
    for talk in visible_talk:
        rel_x = talk.location.col - center_col
        rel_y = talk.location.row - center_row
        if isinstance(self_agent_id, int) and talk.agent_id == self_agent_id and rel_x == 0 and rel_y == 0:
            _attach_talk_fields(
                self_state,
                text=talk.text,
                remaining_steps=talk.remaining_steps,
                row=talk.location.row,
                col=talk.location.col,
            )
            continue

        entity = agents_by_id.get(talk.agent_id) or agents_by_position.get((rel_x, rel_y))
        if entity is None:
            entity = SemanticEntity(
                entity_id=f"agent-{talk.agent_id}",
                entity_type="agent",
                position=GridPosition(x=rel_x, y=rel_y),
                labels=["player", "talking"],
                attributes={
                    "agent_id": talk.agent_id,
                    "global_x": self_global_x + rel_x,
                    "global_y": self_global_y + rel_y,
                },
            )
            visible_entities.append(entity)
            agents_by_position[(rel_x, rel_y)] = entity
        _backfill_talking_agent_identity(entity, agent_id=talk.agent_id)
        agents_by_id[talk.agent_id] = entity

        _attach_talk_fields(
            entity,
            text=talk.text,
            remaining_steps=talk.remaining_steps,
            row=talk.location.row,
            col=talk.location.col,
        )


def _backfill_talking_agent_identity(entity: SemanticEntity, *, agent_id: int) -> None:
    entity.attributes["agent_id"] = agent_id
    entity.entity_id = f"agent-{agent_id}"


def _attach_talk_fields(
    entity: SelfState | SemanticEntity,
    *,
    text: str,
    remaining_steps: int,
    row: int,
    col: int,
) -> None:
    entity.attributes["talk_text"] = text
    entity.attributes["talk_remaining_steps"] = remaining_steps
    entity.attributes["talk_row"] = row
    entity.attributes["talk_col"] = col
    if "talking" not in entity.labels:
        entity.labels.append("talking")


def _include_cell(tags: tuple[str, ...]) -> bool:
    return _PLAYER_TAG in tags or _BELL_TAG in tags


def _entity_type(tags: tuple[str, ...]) -> str:
    if _PLAYER_TAG in tags:
        return "agent"
    if _BELL_TAG in tags:
        return "meeting_bell"
    return "unknown"


def _inventory_from_features(features: dict[str, int]) -> dict[str, int]:
    return {
        feature_name.removeprefix("inv:"): value
        for feature_name, value in sorted(features.items())
        if feature_name.startswith("inv:")
    }


def _role_from_globals(global_features: dict[str, int]) -> str:
    return "werewolf" if global_features.get("role_werewolf", 0) > 0 else "villager"


def _packmate_ids(global_features: dict[str, int]) -> frozenset[int]:
    return frozenset(
        value - 1 for name, value in global_features.items() if name.startswith("wolf_pack_") and value > 0
    )


def _phase_from_inventory(inventory: dict[str, int]) -> str:
    return "day" if inventory.get("day_phase", 0) > 0 else "night"


def _self_status(*, phase: str, inventory: dict[str, int], role: str) -> list[str]:
    status = [phase, role]
    if inventory.get("alive", 0) > 0:
        status.append("alive")
    else:
        status.append("dead")
    if inventory.get("vote_token", 0) > 0:
        status.append("can_vote")
    if inventory.get("day_vote_open", 0) > 0:
        status.append("vote_open")
    if inventory.get("night_hunt_open", 0) > 0:
        status.append("hunt_open")
    return status


def _shared_objectives(*, phase: str, role: str, packmates: frozenset[int]) -> list[str]:
    objectives = [f"phase:{phase}"]
    if role == "werewolf":
        objectives.append("channel:wolf_private" if phase == "night" else "channel:public")
        objectives.extend(f"packmate:agent-{agent_id}" for agent_id in sorted(packmates))
    else:
        objectives.append("channel:public" if phase == "day" else "channel:quiet")
    return objectives


def _global_axis(features: dict[str, int], *, positive: str, negative: str) -> int:
    return int(features.get(positive, 0)) - int(features.get(negative, 0))


def _looks_like_call_target(features: dict[str, int]) -> bool:
    for name, value in features.items():
        if not name.startswith("call_") or value <= 0:
            continue
        if _CALL_RE.search(name.removeprefix("call_")) is not None:
            return True
    return False
