from mettagrid.sdk.agent import GridPosition, MettagridState, SelfState, TeamSummary

from players.cogsguard._shared.semantic import CogsguardPolicySurface


def test_policy_surface_renders_state_with_game_semantics() -> None:
    surface = CogsguardPolicySurface()
    state = MettagridState(
        game="cogsguard",
        step=12,
        self_state=SelfState(
            entity_id="agent-0",
            entity_type="agent",
            position=GridPosition(x=3, y=4),
            labels=["friendly", "team:red"],
            attributes={"team": "red"},
            role="miner",
            inventory={"carbon": 1},
            status=["healthy"],
        ),
        team_summary=TeamSummary(team_id="red", shared_inventory={"oxygen": 2}),
    )

    rendered = surface.render_state(state)

    assert "SELF" in rendered
    assert "team: red" in rendered
    assert "role: miner" in rendered
    assert "inventory: carbon=1" in rendered
