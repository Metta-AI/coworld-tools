"""Rule 4 -- Stake-based team hubs.

Validates:
- Hub has team-scoped visible stake economy resources.
- Default bump = CLAIM (settle dividends + join team + restore health).
- Stake buy station = MINT (buy stake at bonding curve price).
- Stake sell station = BURN (sell stake, refund from curve).
"""

from __future__ import annotations

MAP_AGENT_HUB = [
    ["#", "#", "#", "#"],
    ["#", "@", "h", "#"],
    ["#", "#", "#", "#"],
]

MAP_AGENT_BUY = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "+", "h", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_AGENT_SELL = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "-", "h", "#"],
    ["#", "#", "#", "#", "#"],
]


def test_hub_has_stake_resources(build_rule_config, new_simulation):
    """Hub starts with initial red stake economy display."""
    cfg = build_rule_config(MAP_AGENT_HUB)
    sim = new_simulation(cfg)

    hub = _hub(sim)
    assert hub["inv:red_stake_buy_price"] == 10
    assert hub.get("inv:red_stake_sell_price", 0) == 0
    assert hub.get("inv:red_total_stakes", 0) == 0
    assert "inv:total_stake" not in hub
    assert "inv:curve_reserve" not in hub


def test_mint_stake(build_rule_config, new_simulation, step_with_actions):
    """Bumping stake buy station mints one stake. First costs k*1=10."""
    cfg = build_rule_config(MAP_AGENT_BUY, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("red_stake", 0) == 1
    assert sim.agent(0).inventory["creds"] == 90  # 100 - 10


def test_mint_second_stake_costs_more(build_rule_config, new_simulation, step_with_actions):
    """Second stake costs k*2=20. Total spent = 10+20 = 30."""
    cfg = build_rule_config(MAP_AGENT_BUY, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])  # mint #1: cost 10
    step_with_actions(sim, ["move_east"])  # mint #2: cost 20

    assert sim.agent(0).inventory.get("red_stake", 0) == 2
    assert sim.agent(0).inventory["creds"] == 70  # 100 - 10 - 20


def test_burn_stake_refunds(build_rule_config, new_simulation, step_with_actions):
    """Mint one stake then burn it. Net cost = 0."""
    map_buy_sell = [
        ["#", "#", "#", "#", "#", "#"],
        ["#", "+", "@", "-", "h", "#"],
        ["#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_buy_sell, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    # Mint (bump west).
    step_with_actions(sim, ["move_west"])
    assert sim.agent(0).inventory["creds"] == 90
    assert sim.agent(0).inventory.get("red_stake", 0) == 1

    # Move to sell and burn (bump east).
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("red_stake", 0) == 0
    assert sim.agent(0).inventory["creds"] == 100


def test_claim_restores_health(build_rule_config, new_simulation, step_with_actions):
    """Default bump on hub (claim) restores coherence to max."""
    cfg = build_rule_config(MAP_AGENT_HUB,
        agent_inventory=[{"core_d": 10}])  # max_coh = 20 + 5*10 = 70
    cfg.game.agents[0].inventory.initial["coherence"] = 5

    sim = new_simulation(cfg)
    assert sim.agent(0).inventory["coherence"] == 5

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory["coherence"] == 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub(sim) -> dict:
    for o in sim.grid_objects().values():
        if o.get("type_name") == "hub":
            return o
    raise AssertionError("no hub found")
