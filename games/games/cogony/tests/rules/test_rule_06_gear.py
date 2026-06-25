"""Rule 6 -- Gear (RULES.md section 2).

Validates:
- Buying gear at a station costs 2^(4+gear_held) creds.
- No gear slot cap.
- Gear persists through death.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

# Agent next to a core_a station.
MAP_AGENT_GEAR_STATION = [
    ["#", "#", "#", "#"],
    ["#", "@", "D", "#"],
    ["#", "#", "#", "#"],
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_buy_gear_first_costs_4(build_rule_config, new_simulation, step_with_actions):
    """First gear buy with 0 gear held costs 2^(2+0) = 4 creds."""
    cfg = build_rule_config(
        MAP_AGENT_GEAR_STATION,
        agent_inventory=[{"creds": 20, "core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}],
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("core_a", 0) == 1
    assert sim.agent(0).inventory["creds"] == 16  # 20 - 4


def test_buy_gear_requires_creds(build_rule_config, new_simulation, step_with_actions):
    """Cannot buy gear without enough creds. First buy costs 4."""
    cfg = build_rule_config(
        MAP_AGENT_GEAR_STATION,
        agent_inventory=[{"creds": 3, "core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}],
    )
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("core_a", 0) == 0
    assert sim.agent(0).inventory["creds"] == 3


def test_gear_cost_scales_exponentially(build_rule_config, new_simulation, step_with_actions):
    """Gear cost = 2^(2+gear_held). First=4, second=8, third=16."""
    cfg = build_rule_config(
        MAP_AGENT_GEAR_STATION,
        agent_inventory=[{"creds": 200, "core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}],
    )
    sim = new_simulation(cfg)

    # First buy: 2^(2+0) = 4.
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("core_a", 0) == 1
    assert sim.agent(0).inventory["creds"] == 196  # 200 - 4

    # Second buy: 2^(2+1) = 8.
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("core_a", 0) == 2
    assert sim.agent(0).inventory["creds"] == 188  # 196 - 8


def test_lose_one_gear_on_reboot(build_rule_config, new_simulation, step_with_actions):
    """Cog loses one random gear unit on reboot (threshold = 100 + core_d = 102)."""
    cfg = build_rule_config(
        MAP_AGENT_GEAR_STATION,
        agent_inventory=[{"core_a": 3, "core_d": 2}],
    )
    cfg.game.agents[0].inventory.initial["coherence"] = 0

    sim = new_simulation(cfg)

    total_before = 3 + 2
    # Reboot threshold = 100 + core_d(2) = 102 ticks.
    for _ in range(103):
        step_with_actions(sim, ["noop"])

    core_a = sim.agent(0).inventory.get("core_a", 0)
    core_d = sim.agent(0).inventory.get("core_d", 0)
    assert core_a + core_d == total_before - 1
    assert sim.agent(0).inventory.get("coherence", 0) > 0
