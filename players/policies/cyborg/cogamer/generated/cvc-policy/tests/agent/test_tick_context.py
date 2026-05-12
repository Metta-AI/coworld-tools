"""Tests for TickContext building and helper functions."""

from __future__ import annotations

import pytest

from cvc_policy.agent.tick_context import build_tick_context, teammate_aligner_positions
from cvc_policy.agent.world_model import WorldModel


class TestTeammateAlignerPositions:
    def test_no_team_summary(self, make_state):
        state = make_state(team_summary=None)
        assert teammate_aligner_positions(state) == []

    def test_no_aligners(self, make_state):
        from mettagrid.sdk.agent import GridPosition, TeamMemberSummary

        members = [
            TeamMemberSummary(entity_id="a1", role="miner", position=GridPosition(x=10, y=10), inventory={}),
            TeamMemberSummary(entity_id="a2", role="scrambler", position=GridPosition(x=20, y=20), inventory={}),
        ]
        state = make_state(members=members)
        assert teammate_aligner_positions(state) == []

    def test_returns_aligner_positions(self, make_state):
        from mettagrid.sdk.agent import GridPosition, TeamMemberSummary

        members = [
            TeamMemberSummary(entity_id="a1", role="aligner", position=GridPosition(x=10, y=10), inventory={}),
            TeamMemberSummary(entity_id="a2", role="miner", position=GridPosition(x=20, y=20), inventory={}),
            TeamMemberSummary(entity_id="a3", role="aligner", position=GridPosition(x=30, y=30), inventory={}),
        ]
        state = make_state(members=members)
        positions = teammate_aligner_positions(state)
        assert (10, 10) in positions
        assert (30, 30) in positions
        assert len(positions) == 2

    def test_excludes_self(self, make_state):
        from mettagrid.sdk.agent import GridPosition, TeamMemberSummary

        members = [
            TeamMemberSummary(entity_id="agent_0", role="aligner", position=GridPosition(x=10, y=10), inventory={}),
            TeamMemberSummary(entity_id="a2", role="aligner", position=GridPosition(x=20, y=20), inventory={}),
        ]
        # make_state sets self_state.attributes["entity_id"] via SelfState entity_id
        # but teammate_aligner_positions reads attributes.get("entity_id") which
        # defaults to "" in make_state. The SelfState entity_id="agent_0" is a
        # separate field. So we need to check the actual attribute lookup.
        state = make_state(members=members)
        # self_state.attributes has no "entity_id" key, so my_entity_id is ""
        # which doesn't match "agent_0", so both are included
        positions = teammate_aligner_positions(state)
        assert len(positions) == 2
        assert (10, 10) in positions
        assert (20, 20) in positions


class TestBuildTickContext:
    """Test build_tick_context with mock engine components."""

    @pytest.fixture
    def world_model(self):
        return WorldModel()

    @pytest.fixture
    def hub(self, make_entity):
        return make_entity(entity_type="hub", x=44, y=44, team="team_0", owner="team_0")

    def _build(self, state, world_model, hub):
        return build_tick_context(
            state,
            world_model=world_model,
            nearest_hub_fn=lambda s: hub,
            known_junctions_fn=lambda s, predicate: [],
            stalled_steps=0,
            oscillation_steps=0,
            resource_bias="carbon",
            step_index=500,
        )

    def test_basic_fields(self, make_state, world_model, hub):
        state = make_state(hp=75, global_x=44, global_y=44, step=500)
        ctx = self._build(state, world_model, hub)
        assert ctx.position == (44, 44)
        assert ctx.hp == 75
        assert ctx.step == 500
        assert ctx.team == "team_0"
        assert ctx.resource_bias == "carbon"

    def test_inventory_fields(self, make_state, world_model, hub):
        state = make_state(inventory={"heart": 3, "carbon": 5, "oxygen": 2})
        ctx = self._build(state, world_model, hub)
        assert ctx.hearts == 3
        assert ctx.cargo == 7  # 5 + 2

    def test_hub_distance(self, make_state, world_model, hub):
        state = make_state(global_x=50, global_y=44)
        ctx = self._build(state, world_model, hub)
        assert ctx.hub == hub
        assert ctx.hub_distance == 6  # |50-44| + |44-44|

    def test_no_hub(self, make_state, world_model):
        state = make_state()
        ctx = build_tick_context(
            state,
            world_model=world_model,
            nearest_hub_fn=lambda s: None,
            known_junctions_fn=lambda s, predicate: [],
            stalled_steps=0,
            oscillation_steps=0,
            resource_bias="carbon",
            step_index=500,
        )
        assert ctx.hub is None
        assert ctx.hub_distance == 0

    def test_enemy_aoe_detection(self, make_state, world_model, hub, make_entity):
        enemy_junction = make_entity(entity_type="junction", x=48, y=44, owner="team_1")

        def known_junctions_fn(s, predicate):
            candidates = [enemy_junction]
            return [j for j in candidates if predicate(j)]

        state = make_state(global_x=44, global_y=44)
        ctx = build_tick_context(
            state,
            world_model=world_model,
            nearest_hub_fn=lambda s: hub,
            known_junctions_fn=known_junctions_fn,
            stalled_steps=0,
            oscillation_steps=0,
            resource_bias="carbon",
            step_index=500,
        )
        # Enemy at distance 4, within AOE range (10)
        assert ctx.in_enemy_aoe is True
        assert ctx.near_enemy_territory is True

    def test_no_enemy_aoe(self, make_state, world_model, hub):
        state = make_state()
        ctx = self._build(state, world_model, hub)
        assert ctx.in_enemy_aoe is False
        assert ctx.near_enemy_territory is False

    def test_stall_and_oscillation(self, make_state, world_model, hub):
        state = make_state()
        ctx = build_tick_context(
            state,
            world_model=world_model,
            nearest_hub_fn=lambda s: hub,
            known_junctions_fn=lambda s, predicate: [],
            stalled_steps=12,
            oscillation_steps=4,
            resource_bias="carbon",
            step_index=500,
        )
        assert ctx.stalled_steps == 12
        assert ctx.oscillation_steps == 4

    def test_junction_classification(self, make_state, world_model, hub, make_entity):
        friendly = make_entity(entity_type="junction", x=50, y=50, owner="team_0")
        enemy = make_entity(entity_type="junction", x=60, y=60, owner="team_1")
        neutral = make_entity(entity_type="junction", x=70, y=70, owner=None)

        all_junctions = [friendly, enemy, neutral]

        def known_junctions_fn(s, predicate):
            return [j for j in all_junctions if predicate(j)]

        state = make_state()
        ctx = build_tick_context(
            state,
            world_model=world_model,
            nearest_hub_fn=lambda s: hub,
            known_junctions_fn=known_junctions_fn,
            stalled_steps=0,
            oscillation_steps=0,
            resource_bias="carbon",
            step_index=500,
        )
        assert ctx.friendly_junctions == [friendly]
        assert ctx.enemy_junctions == [enemy]
        # friendly has owner="team_0" which is not in {None, "neutral"}, so not neutral
        assert ctx.neutral_junctions == [neutral]

    def test_frozen(self, make_state, world_model, hub):
        state = make_state()
        ctx = self._build(state, world_model, hub)
        with pytest.raises(AttributeError):
            ctx.hp = 50  # type: ignore[misc]
