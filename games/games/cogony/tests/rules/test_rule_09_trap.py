"""Rule 9 -- Trap and Jump abilities.

Validates:
- Trap trigger: bumping removes trap, deals damage, scrambles agent, agent moves to trap cell.
- Trap auto-expire: trap removed from grid after TTL ticks.
- Trap vibe: drops trap at old location on move, resets vibe.
- Jump vibe: moves 2 cells if open, jumps over objects, falls back to 1.
"""

from __future__ import annotations


MAP_TRAP = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "T", ".", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_OPEN = [
    ["#", "#", "#", "#", "#", "#"],
    ["#", "@", ".", ".", ".", "#"],
    ["#", "#", "#", "#", "#", "#"],
]


def _trap(sim):
    for o in sim.grid_objects().values():
        if o.get("type_name") == "trap":
            return o
    return None


def test_bump_trap_deals_damage(build_rule_config, new_simulation, step_with_actions):
    """Walking onto a trap deals damage to the agent."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    initial_coh = sim.agent(0).inventory["coherence"]
    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory["coherence"] < initial_coh


def test_bump_trap_scrambles(build_rule_config, new_simulation, step_with_actions):
    """Bumping a trap sets scrambled=10 and mobile=0."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("scrambled", 0) >= 9
    assert sim.agent(0).inventory.get("mobile", 0) == 0


def test_scrambled_blocks_movement(build_rule_config, new_simulation, step_with_actions):
    """While scrambled, agent cannot move."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])
    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    pos_after_trap = a["c"]

    step_with_actions(sim, ["move_east"])
    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a["c"] == pos_after_trap, "scrambled agent should not move"


def test_scrambled_wears_off(build_rule_config, new_simulation, step_with_actions):
    """After 10 ticks, scrambled reaches 0 and mobile is restored."""
    cfg = build_rule_config(MAP_TRAP, max_steps=200,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])
    for _ in range(10):
        step_with_actions(sim, ["noop"])

    assert sim.agent(0).inventory.get("scrambled", 0) == 0
    assert sim.agent(0).inventory.get("mobile", 1) == 1

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    pos_before = a["c"]
    step_with_actions(sim, ["move_east"])
    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a["c"] == pos_before + 1, "should be able to move after scrambled wears off"


def test_bump_trap_removes_from_grid(build_rule_config, new_simulation, step_with_actions):
    """After triggering, the trap is removed from the grid."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    assert _trap(sim) is not None
    step_with_actions(sim, ["move_east"])

    assert _trap(sim) is None, "trap should be removed from grid after trigger"


def test_bump_trap_moves_agent(build_rule_config, new_simulation, step_with_actions):
    """After triggering, agent ends up on the trap's former cell."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a["c"] == 2, f"agent should be at trap's old cell (col 2), got {a['c']}"


def test_trap_expires_and_removed(build_rule_config, new_simulation, step_with_actions):
    """After TTL ticks, trap is removed from the grid entirely."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    assert _trap(sim) is not None
    for _ in range(6):
        step_with_actions(sim, ["noop"])

    assert _trap(sim) is None, "trap should be removed after TTL expires"


def test_expired_trap_no_damage(build_rule_config, new_simulation, step_with_actions):
    """After expiry, walking to the trap's old cell does no damage."""
    cfg = build_rule_config(MAP_TRAP,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    for _ in range(6):
        step_with_actions(sim, ["noop"])

    initial_coh = sim.agent(0).inventory["coherence"]
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory["coherence"] == initial_coh


def test_trap_vibe_drops_trap(build_rule_config, new_simulation, step_with_actions):
    """Setting trap vibe then moving drops a trap at old location."""
    cfg = build_rule_config(MAP_OPEN,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    assert _trap(sim) is None
    step_with_actions(sim, ["change_vibe_trap"])
    step_with_actions(sim, ["move_east"])

    assert _trap(sim) is not None


def test_trap_vibe_resets_after_drop(build_rule_config, new_simulation, step_with_actions):
    """Vibe resets to default after dropping a trap."""
    cfg = build_rule_config(MAP_OPEN,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["change_vibe_trap"])
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    traps = [o for o in sim.grid_objects().values() if o.get("type_name") == "trap"]
    assert len(traps) == 1


def test_spawned_trap_triggers(build_rule_config, new_simulation, step_with_actions):
    """Agent drops trap, walks back onto it — takes damage and trap removed."""
    map_long = [
        ["#", "#", "#", "#", "#", "#", "#", "#"],
        ["#", "@", ".", ".", ".", ".", ".", "#"],
        ["#", "#", "#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_long, max_steps=200,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["change_vibe_trap"])
    step_with_actions(sim, ["move_east"])

    initial_coh = sim.agent(0).inventory["coherence"]
    step_with_actions(sim, ["move_west"])

    assert sim.agent(0).inventory["coherence"] < initial_coh
    assert _trap(sim) is None, "spawned trap should be removed after trigger"


def test_jump_moves_two_cells(build_rule_config, new_simulation, step_with_actions):
    """Jump vibe moves agent 2 cells in one step."""
    cfg = build_rule_config(MAP_OPEN,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    start_c = a["c"]

    step_with_actions(sim, ["change_vibe_jump"])
    step_with_actions(sim, ["move_east"])

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a["c"] == start_c + 2


def test_jump_over_object(build_rule_config, new_simulation, step_with_actions):
    """Jump vibe leaps over an object to land on the cell behind it."""
    map_obstacle = [
        ["#", "#", "#", "#", "#", "#"],
        ["#", "@", "T", ".", ".", "#"],
        ["#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_obstacle,
        agent_inventory=[{"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}])
    sim = new_simulation(cfg)

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    start_c = a["c"]

    step_with_actions(sim, ["change_vibe_jump"])
    step_with_actions(sim, ["move_east"])

    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a["c"] == start_c + 2, (
        f"should jump over trap to col {start_c + 2}, got {a['c']}"
    )
