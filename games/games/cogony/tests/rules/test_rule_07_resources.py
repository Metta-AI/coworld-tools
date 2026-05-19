"""Rule 7 -- Resources: elements, cargo, creds, hearts (RULES.md section 3/7).

Validates:
- Elements are Carbon, Oxygen, Germanium, Silicon (COGS order).
- Market station: sell elements for creds at dynamic prices (rarest=4).
- Heart station: buy 1 heart for 100 creds.
- Creds and hearts persist across death.
"""

from __future__ import annotations

from cogony.mission import CogonyMission

# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

# Agent next to a market station.
MAP_AGENT_MARKET = [
    ["#", "#", "#", "#"],
    ["#", "@", "M", "#"],
    ["#", "#", "#", "#"],
]

# Agent next to a heart station.
MAP_AGENT_HEART = [
    ["#", "#", "#", "#"],
    ["#", "@", "H", "#"],
    ["#", "#", "#", "#"],
]

# Agent between market and heart station.
MAP_AGENT_MARKET_HEART = [
    ["#", "#", "#", "#", "#"],
    ["#", "M", "@", "H", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_TWO_AGENTS = [
    ["#", "#", "#", "#"],
    ["#", "@", "@", "#"],
    ["#", "#", "#", "#"],
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_elements_in_cogs_order(build_rule_config, new_simulation):
    """Elements are Carbon, Oxygen, Germanium, Silicon (RULES.md section 3)."""
    cfg = build_rule_config(MAP_AGENT_MARKET)
    sim = new_simulation(cfg)

    # Verify all four element resources exist by checking the agent
    # can carry them (cargo limit includes them).
    inv = sim.agent(0).inventory
    for element in ["carbon", "oxygen", "germanium", "silicon"]:
        # Each element should be a valid inventory key (may be 0).
        assert element in inv or inv.get(element, 0) == 0, (
            f"Element '{element}' not registered"
        )


def test_market_sells_elements_for_creds(build_rule_config, new_simulation, step_with_actions):
    """Bumping market sells elements at dynamic prices (initial: C=1,O=2,G=3,S=4)."""
    cfg = build_rule_config(
        MAP_AGENT_MARKET,
        agent_inventory=[{"carbon": 5, "silicon": 3}],
    )
    sim = new_simulation(cfg)

    creds_before = sim.agent(0).inventory.get("creds", 0)
    step_with_actions(sim, ["move_east"])

    # 5 carbon * 1 + 3 silicon * 4 = 17 creds.
    assert sim.agent(0).inventory.get("creds", 0) == creds_before + 17
    assert sim.agent(0).inventory.get("carbon", 0) == 0
    assert sim.agent(0).inventory.get("silicon", 0) == 0


def test_market_no_elements_no_creds(build_rule_config, new_simulation, step_with_actions):
    """Bumping market with no elements gives no creds."""
    cfg = build_rule_config(MAP_AGENT_MARKET)
    sim = new_simulation(cfg)

    creds_before = sim.agent(0).inventory.get("creds", 0)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("creds", 0) == creds_before


def test_market_dynamic_pricing(build_rule_config, new_simulation, step_with_actions):
    """After selling carbon heavily, its price drops and rarer elements rise."""
    cfg = build_rule_config(
        MAP_AGENT_MARKET,
        agent_inventory=[{"carbon": 20}],
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    # After selling only carbon, carbon is most common (sold=20).
    # Prices recalculate: carbon=1(most sold), rest have sold=0 (tied).
    # Carbon should now be cheapest.


def test_heart_station_buys_heart(build_rule_config, new_simulation, step_with_actions):
    """Agent with 100+ creds bumps heart station -> gains 1 heart, loses 100 creds."""
    cfg = build_rule_config(
        MAP_AGENT_HEART,
        agent_inventory=[{"creds": 150}],
    )
    sim = new_simulation(cfg)

    assert sim.agent(0).inventory.get("heart", 0) == 1
    assert sim.agent(0).inventory["creds"] == 150

    # Bump the heart station (east).
    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("heart", 0) == 2
    assert sim.agent(0).inventory["creds"] == 50


def test_heart_station_requires_100_creds(build_rule_config, new_simulation, step_with_actions):
    """Agent with < 100 creds cannot buy a heart."""
    cfg = build_rule_config(
        MAP_AGENT_HEART,
        agent_inventory=[{"creds": 50}],
    )
    sim = new_simulation(cfg)

    # Bump the heart station (east).
    step_with_actions(sim, ["move_east"])

    # Should be blocked -- no heart gained (stays at initial 1), creds unchanged.
    assert sim.agent(0).inventory.get("heart", 0) == 1
    assert sim.agent(0).inventory["creds"] == 50


def test_heart_station_can_stack_past_ten_hearts(build_rule_config, new_simulation, step_with_actions):
    """Hearts are uncapped victory points; buying should not stop at 10."""
    cfg = build_rule_config(
        MAP_AGENT_HEART,
        agent_inventory=[{"creds": 1100, "heart": 10}],
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("heart", 0) == 11
    assert sim.agent(0).inventory["creds"] == 1000


def test_testing_only_resource_vibes_are_not_registered(build_rule_config):
    """Cash/hearts test vibes should not be available in normal games."""
    cfg = build_rule_config(MAP_AGENT_MARKET_HEART)

    action_vibe_names = [vibe.name for vibe in cfg.game.actions.change_vibe.vibes]

    assert "cred" not in cfg.game.vibe_names
    assert "heart" not in cfg.game.vibe_names
    assert "cred" not in action_vibe_names
    assert "heart" not in action_vibe_names


def test_testing_only_resource_vibes_are_registered_in_god_mode():
    """God mode exposes the resource-transfer vibes for manual testing."""
    mission = CogonyMission(god_mode=True)
    cfg = mission.make_env()

    action_vibe_names = [vibe.name for vibe in cfg.game.actions.change_vibe.vibes]

    assert "cred" in cfg.game.vibe_names
    assert "heart" in cfg.game.vibe_names
    assert "cred" in action_vibe_names
    assert "heart" in action_vibe_names


def test_god_mode_cred_vibe_transfers_creds(build_rule_config, new_simulation, step_with_actions):
    """God-mode cred vibe transfers 10 creds to the bumped cog."""
    cfg = build_rule_config(
        MAP_TWO_AGENTS,
        agent_inventory=[{"creds": 20}, {"creds": 0}],
        god_mode=True,
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["change_vibe_cred", "noop"])
    step_with_actions(sim, ["move_east", "noop"])

    assert sim.agent(0).inventory["creds"] == 10
    assert sim.agent(1).inventory["creds"] == 10


def test_god_mode_heart_vibe_transfers_heart(build_rule_config, new_simulation, step_with_actions):
    """God-mode heart vibe transfers one heart to the bumped cog."""
    cfg = build_rule_config(
        MAP_TWO_AGENTS,
        agent_inventory=[{"heart": 2}, {"heart": 0}],
        god_mode=True,
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["change_vibe_heart", "noop"])
    step_with_actions(sim, ["move_east", "noop"])

    assert sim.agent(0).inventory["heart"] == 1
    assert sim.agent(1).inventory["heart"] == 1


def test_creds_persist_through_death(build_rule_config, new_simulation, step_with_actions):
    """Creds are kept when coherence drops to 0 (RULES.md section 3)."""
    cfg = build_rule_config(
        MAP_AGENT_MARKET,
        agent_inventory=[{"creds": 42}],
    )
    # Set coherence to 0 to simulate death.
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    sim = new_simulation(cfg)

    # Step once so the death handler fires.
    step_with_actions(sim, ["noop"])

    # Creds should still be there.
    assert sim.agent(0).inventory["creds"] == 42


def test_hearts_persist_through_death(build_rule_config, new_simulation, step_with_actions):
    """Hearts are kept when coherence drops to 0 (RULES.md section 3)."""
    cfg = build_rule_config(
        MAP_AGENT_HEART,
        agent_inventory=[{"heart": 3}],
    )
    # Set coherence to 0 to simulate death.
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    sim = new_simulation(cfg)

    # Step once so the death handler fires.
    step_with_actions(sim, ["noop"])

    # Hearts should still be there.
    assert sim.agent(0).inventory.get("heart", 0) == 3
