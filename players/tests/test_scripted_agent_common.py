from __future__ import annotations

from types import SimpleNamespace

from cogames_agents.policy.scripted_agent.buggy.context import PlankyContext
from cogames_agents.policy.scripted_agent.buggy.entity_map import Entity as BuggyEntity
from cogames_agents.policy.scripted_agent.buggy.entity_map import EntityMap as BuggyEntityMap
from cogames_agents.policy.scripted_agent.buggy.goal import evaluate_goals as evaluate_buggy_goals
from cogames_agents.policy.scripted_agent.common.context import StateSnapshot
from cogames_agents.policy.scripted_agent.common.goal import Goal, evaluate_goals
from cogames_agents.policy.scripted_agent.common.trace import TraceLog
from cogames_agents.policy.scripted_agent.cranky.context import CogasContext
from cogames_agents.policy.scripted_agent.cranky.entity_map import Entity as CrankyEntity
from cogames_agents.policy.scripted_agent.cranky.entity_map import EntityMap as CrankyEntityMap
from cogames_agents.policy.scripted_agent.cranky.goal import evaluate_goals as evaluate_cranky_goals

from mettagrid.simulator import Action


class _DummyGoal(Goal):
    def __init__(self, name: str, *, satisfied: bool, action: Action | None = None) -> None:
        self.name = name
        self.satisfied = satisfied
        self.action = action

    def is_satisfied(self, ctx: object) -> bool:
        return self.satisfied

    def execute(self, ctx: object) -> Action | None:
        return self.action


def _context() -> PlankyContext:
    return PlankyContext(
        state=StateSnapshot(position=(4, 5)),
        map=BuggyEntityMap(),
        blackboard={},
        navigator=SimpleNamespace(
            explore=lambda position, entity_map, direction_bias: Action(name=f"move_{direction_bias}")
        ),
        trace=TraceLog(),
        action_names=["noop", "move_north"],
        agent_id=1,
        step=7,
    )


def test_state_snapshot_cargo_helpers_live_in_common_module() -> None:
    state = StateSnapshot(carbon=1, oxygen=2, germanium=3, silicon=4)

    assert state.cargo_total == 10
    assert state.cargo_capacity == 4

    state.miner_gear = True
    assert state.cargo_capacity == 40


def test_common_goal_evaluation_supports_optional_fallback_action() -> None:
    ctx = _context()

    action = evaluate_goals(
        [_DummyGoal(name="Satisfied", satisfied=True)],
        ctx,
        fallback_action=lambda: ctx.navigator.explore(ctx.state.position, ctx.map, direction_bias="east"),
    )

    assert action == Action(name="move_east")
    assert ctx.trace is not None
    assert ctx.trace.active_goal_chain == "AllGoalsSatisfied"
    assert ctx.trace.action_name == "move_east"


def test_buggy_entity_map_expires_stale_agents_but_cranky_does_not() -> None:
    buggy_map = BuggyEntityMap()
    cranky_map = CrankyEntityMap()
    agent_pos = (50, 50)

    buggy_map.entities[agent_pos] = BuggyEntity(type="agent", properties={}, last_seen=1)
    cranky_map.entities[agent_pos] = CrankyEntity(type="agent", properties={}, last_seen=1)

    buggy_map.update_from_observation(
        agent_pos=(10, 10),
        obs_half_height=1,
        obs_half_width=1,
        visible_entities={},
        step=4,
    )
    cranky_map.update_from_observation(
        agent_pos=(10, 10),
        obs_half_height=1,
        obs_half_width=1,
        visible_entities={},
        step=4,
    )

    assert not buggy_map.has_agent(agent_pos)
    assert cranky_map.has_agent(agent_pos)


def test_cranky_context_keeps_team_default() -> None:
    ctx = CogasContext(
        state=StateSnapshot(),
        map=CrankyEntityMap(),
        blackboard={},
        navigator=SimpleNamespace(),
        trace=None,
        action_names=["noop"],
        agent_id=0,
        step=0,
    )

    assert ctx.my_team == "cogs"


def test_public_goal_wrappers_preserve_buggy_and_cranky_fallback_behavior() -> None:
    buggy_ctx = _context()
    cranky_ctx = CogasContext(
        state=StateSnapshot(position=(4, 5)),
        map=CrankyEntityMap(),
        blackboard={},
        navigator=SimpleNamespace(
            explore=lambda position, entity_map, direction_bias: Action(name=f"move_{direction_bias}")
        ),
        trace=TraceLog(),
        action_names=["noop", "move_north"],
        agent_id=1,
        step=7,
    )

    goals = [_DummyGoal(name="Satisfied", satisfied=True)]

    assert evaluate_buggy_goals(goals, buggy_ctx) == Action(name="noop")
    assert evaluate_cranky_goals(goals, cranky_ctx) == Action(name="move_east")
