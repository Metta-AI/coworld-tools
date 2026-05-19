from overcogged.agent.overcogged_agent.policy import _assign_role


def test_scripted_policy_assigns_runner_role_for_four_agents() -> None:
    assert [_assign_role(agent_id, 4) for agent_id in range(4)] == [
        "prep",
        "cook",
        "server",
        "all_rounder",
    ]
