"""Rule 1 -- Coherence (RULES.md section 1).

Validates coherence as the primary health resource, regen, and starting
inventory for cogs.
"""

from __future__ import annotations

# Simple 3x3 map with a single agent in the center.
MAP_3x3 = [["#", "#", "#"], ["#", "@", "#"], ["#", "#", "#"]]


def test_cog_spawns_with_coherence_10(build_rule_config, new_simulation):
    """Cog starts with coherence=10, max=10+5*core_d."""
    cfg = build_rule_config(MAP_3x3)
    sim = new_simulation(cfg)

    inv = sim.agent(0).inventory
    assert inv["coherence"] == 10


def test_cog_spawns_with_100_creds(build_rule_config, new_simulation):
    """Cog starts with 100 creds."""
    cfg = build_rule_config(MAP_3x3)
    sim = new_simulation(cfg)

    inv = sim.agent(0).inventory
    assert inv["creds"] == 100


def test_coherence_regen_every_10_ticks(build_rule_config, new_simulation, step_with_actions):
    """Every 10 ticks, coherence += 1+core_a. With 0 core_a, regen = 1."""
    cfg = build_rule_config(MAP_3x3, max_steps=200,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    initial = sim.agent(0).inventory["coherence"]
    assert initial == 10

    # Step 9 ticks (no regen yet).
    for _ in range(9):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 10

    # 10th tick triggers regen: coherence -> 11 (max=20 with 0 core_d).
    step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 11


def test_no_regen_at_coherence_zero(build_rule_config, new_simulation, step_with_actions):
    """Regen does not apply when coherence = 0."""
    cfg = build_rule_config(MAP_3x3, max_steps=200)
    sim = new_simulation(cfg)

    # Force coherence to 0 via set_inventory (must include all resources;
    # reading back is stale until the next step).
    inv = dict(sim.agent(0).inventory)
    inv["coherence"] = 0
    sim.agent(0).set_inventory(inv)

    # Step once so the engine picks up the new inventory.
    step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) == 0

    # After 5 more ticks (6 total) -- still disabled, reboot counting down.
    for _ in range(5):
        step_with_actions(sim, ["noop"])

    assert sim.agent(0).inventory.get("coherence", 0) == 0
    assert sim.agent(0).inventory.get("reboot", 0) > 0
