"""Shared test fixtures for cvc_policy tests."""

from __future__ import annotations

from typing import Any

import pytest

from cvc_policy.agent.types import ELEMENTS, KnownEntity
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import (
    GridPosition,
    MettagridState,
    SelfState,
    SemanticEntity,
    TeamSummary,
)

_SENTINEL = object()


def _fake_policy_env_info(num_agents: int = 1) -> PolicyEnvInterface:
    """Minimal PolicyEnvInterface for tests that construct CvCPolicy directly."""
    return PolicyEnvInterface(
        action_names=["noop", "move_north", "move_south", "move_east", "move_west"],
        vibe_action_names=["change_vibe_default"],
        num_agents=num_agents,
        observation_shape=(10, 3),
        egocentric_shape=(5, 5),
    )


def _default_shared_inventory() -> dict[str, int]:
    inv = {r: 10 for r in ELEMENTS}
    inv["heart"] = 5
    return inv


@pytest.fixture
def make_entity():
    """Build a KnownEntity from flexible kwargs.

    Accepted kwargs: entity_type, x, y, team, owner, last_seen_step,
    labels, attributes, plus any extra kwargs folded into attributes.
    """

    def _make(
        entity_type: str = "junction",
        x: int = 0,
        y: int = 0,
        *,
        team: str | None = None,
        owner: str | None = None,
        last_seen_step: int = 0,
        labels: tuple[str, ...] = (),
        attributes: dict[str, Any] | None = None,
        **extra: Any,
    ) -> KnownEntity:
        attrs: dict[str, Any] = {}
        if attributes:
            attrs.update(attributes)
        attrs.update(extra)
        return KnownEntity(
            entity_type=entity_type,
            global_x=x,
            global_y=y,
            labels=tuple(labels),
            team=team,
            owner=owner,
            last_seen_step=last_seen_step,
            attributes=attrs,
        )

    return _make


@pytest.fixture
def make_semantic_entity():
    """Build a SemanticEntity. Accepts entity_type, x, y, and arbitrary attributes."""

    _counter = [0]

    def _make(
        entity_type: str = "junction",
        x: int = 0,
        y: int = 0,
        *,
        entity_id: str | None = None,
        labels: list[str] | None = None,
        **attributes: Any,
    ) -> SemanticEntity:
        _counter[0] += 1
        if entity_id is None:
            entity_id = f"ent_{_counter[0]}"
        # Preserve global_x/global_y in attributes so WorldModel keys match
        attrs: dict[str, Any] = dict(attributes)
        attrs.setdefault("global_x", x)
        attrs.setdefault("global_y", y)
        return SemanticEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            position=GridPosition(x=x, y=y),
            labels=list(labels or []),
            attributes=attrs,
        )

    return _make


@pytest.fixture
def make_state():
    """Build a MettagridState with sensible defaults.

    Kwargs:
      inventory: dict[str, int] — self_state.inventory (hp/heart/resources/role gear)
      hp: int — shorthand for inventory["hp"]
      global_x, global_y: ints — self_state.attributes["global_x"/"global_y"]
      team: str — self_state.attributes["team"], also default team_summary.team_id
      step: int — MettagridState.step
      visible_entities: list[SemanticEntity]
      team_summary: TeamSummary | None | Ellipsis — Ellipsis/omitted builds default
      shared_inventory: dict[str, int] — overrides for default team_summary
      members: list[TeamMemberSummary] — members for default team_summary
      role: str | None — self_state.role
    """

    def _make(
        *,
        inventory: dict[str, int] | None = None,
        hp: int | None = None,
        global_x: int = 44,
        global_y: int = 44,
        team: str = "team_0",
        step: int = 0,
        visible_entities: list[SemanticEntity] | None = None,
        team_summary: Any = _SENTINEL,
        shared_inventory: dict[str, int] | None = None,
        members: list[Any] | None = None,
        role: str | None = None,
        entity_id: str = "agent_self",
        entity_type: str = "agent",
        self_position: tuple[int, int] | None = None,
    ) -> MettagridState:
        inv: dict[str, int] = {}
        if inventory:
            inv.update(inventory)
        if hp is not None:
            inv["hp"] = hp
        elif "hp" not in inv:
            inv["hp"] = 100

        attrs: dict[str, Any] = {
            "global_x": global_x,
            "global_y": global_y,
            "team": team,
        }

        if self_position is None:
            self_position = (global_x, global_y)

        self_state = SelfState(
            entity_id=entity_id,
            entity_type=entity_type,
            position=GridPosition(x=self_position[0], y=self_position[1]),
            labels=[],
            attributes=attrs,
            role=role,
            inventory=inv,
            status=[],
        )

        if team_summary is _SENTINEL or team_summary is ...:
            shared = _default_shared_inventory()
            if shared_inventory is not None:
                shared = dict(shared_inventory)
            ts = TeamSummary(
                team_id=team,
                members=list(members or []),
                shared_inventory=shared,
                shared_objectives=[],
            )
        elif team_summary is None:
            ts = None
        else:
            ts = team_summary

        return MettagridState(
            game="test",
            step=step,
            self_state=self_state,
            visible_entities=list(visible_entities or []),
            team_summary=ts,
            recent_events=[],
        )

    return _make
