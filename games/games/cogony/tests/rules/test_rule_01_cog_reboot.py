
"""Rule 1 -- Cog reboot integration test.

Validates:
- Disabled cogs (coherence=0) cannot move
- Reboot countdown: max_coherence ticks (10 with 0 core_d)
- Coherence restores to max on restart
- Creds and hearts kept across death
"""

from __future__ import annotations


MAP = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", ".", "c", "#"],
    ["#", "#", "#", "#", "#"],
]


def test_disabled_cog_cannot_move(build_rule_config, new_simulation, step_with_actions):
    """A cog with coherence=0 should not move (required_resources enforced)."""
    cfg = build_rule_config(MAP, max_steps=200)
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    cfg.game.agents[0].inventory.initial["mobile"] = 0

    sim = new_simulation(cfg, seed=0)
    a0 = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    start_r, start_c = a0["r"], a0["c"]

    for _ in range(3):
        step_with_actions(sim, ["move_east"])

    a0 = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a0["r"] == start_r and a0["c"] == start_c, (
        f"disabled cog should not move, but went from ({start_r},{start_c}) to ({a0['r']},{a0['c']})"
    )


def test_cog_reboots_after_max_coherence_ticks(build_rule_config, new_simulation, step_with_actions):
    """Cog reboots after max_coherence ticks (10 with 0 core_d)."""
    cfg = build_rule_config(MAP, max_steps=200)
    cfg.game.agents[0].inventory.initial["coherence"] = 0

    sim = new_simulation(cfg, seed=0)

    for _ in range(9):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) == 0

    step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) >= 10


def test_creds_hearts_kept_across_death(build_rule_config, new_simulation, step_with_actions):
    """Creds and hearts persist through disabled state and reboot."""
    cfg = build_rule_config(MAP, agent_inventory=[{"heart": 3}], max_steps=200)
    cfg.game.agents[0].inventory.initial["coherence"] = 0

    sim = new_simulation(cfg, seed=0)
    assert sim.agent(0).inventory.get("creds", 0) == 100
    assert sim.agent(0).inventory.get("heart", 0) == 3

    for _ in range(11):
        step_with_actions(sim, ["noop"])

    assert sim.agent(0).inventory.get("creds", 0) == 100, "creds should survive reboot"
    assert sim.agent(0).inventory.get("heart", 0) == 3, "hearts should survive reboot"


def test_cog_can_move_after_reboot(build_rule_config, new_simulation, step_with_actions):
    """After reboot, cog regains coherence and can move again."""
    cfg = build_rule_config(MAP, max_steps=200)
    cfg.game.agents[0].inventory.initial["coherence"] = 0

    sim = new_simulation(cfg, seed=0)
    a0 = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    start_c = a0["c"]

    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) >= 10

    # Should be able to move now.
    step_with_actions(sim, ["move_east"])
    a0 = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a0["c"] == start_c + 1, "cog should move east after reboot"
