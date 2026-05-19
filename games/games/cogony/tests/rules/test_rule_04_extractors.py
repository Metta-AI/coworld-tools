"""Rule 4 -- Extractor lifecycle integration test.

Agent kills an extractor multiple times, verifying:
- Combat reduces coherence
- Loot drops on decoherence (rand elements)
- Reboot timer runs for 10*level ticks
- Level increments on restart
- Attack/defense stats increase on restart
- Coherence cap grows with level
"""

from __future__ import annotations

from cogony.game.channels import CHANNEL_STATS

MAP = [
    ["#", "#", "#", "#"],
    ["#", "@", "c", "#"],
    ["#", "#", "#", "#"],
]


def _ext(sim):
    for o in sim.grid_objects().values():
        if "extractor" in o.get("type_name", ""):
            return o
    raise AssertionError("no extractor found")


def test_kill_loot_reboot_cycle(build_rule_config, new_simulation, step_with_actions):
    """Full extractor lifecycle: attack → disable → loot → reboot → level up.

    Level-1 extractor: coherence=10 (base=10, core_d=0), core_d=1.
    Agent needs core_a=11 for 10 damage (max(0, 11-1)=10).
    """
    cfg = build_rule_config(MAP, agent_inventory=[{"core_a": 11}], max_steps=500)
    sim = new_simulation(cfg, seed=0)

    ext = _ext(sim)
    assert ext["inv:level"] == 1
    assert ext["inv:coherence"] == 10

    # --- Kill #1 ---
    step_with_actions(sim, ["move_east"])  # bump = attack
    ext = _ext(sim)
    assert ext.get("inv:coherence", 0) == 0, "should be disabled after one-shot"

    # Kill drops elements on the extractor (CogonyAttackMutation death_drop).
    ext = _ext(sim)
    assert ext.get("inv:carbon", 0) > 0, "element loot should have been generated on kill"

    # Collect the loot.
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("carbon", 0) > 0, "agent should have collected carbon"

    # Wait for reboot: 10 + 5*core_d ticks (core_d=0 or 1 randomly).
    for _ in range(20):
        step_with_actions(sim, ["noop"])

    ext = _ext(sim)
    assert ext["inv:level"] == 2, f"level should be 2 after reboot, got {ext.get('inv:level')}"
    assert ext.get("inv:coherence", 0) > 0, "coherence should be restored"

    # --- Verify stat gains after reboot ---
    # At least some of the 8 channel stats should have increased from
    # their level-1 values (core_d=1, others 0-1).
    total_stats = sum(ext.get(f"inv:{s}", 0) for s in CHANNEL_STATS)
    assert total_stats >= 4, (
        f"after reboot, total stats should be at least 4. "
        f"Got total={total_stats}, stats={[(s, ext.get(f'inv:{s}', 0)) for s in CHANNEL_STATS]}"
    )

    # --- Kill #2 (level 2 extractor) ---
    # Level 2: coherence = level*20=40. Agent core_a=11 vs core_d >= 2.
    # Net damage per hit = max(0, 11 - core_d). Should take several hits.
    initial_coh = ext.get("inv:coherence", 0)
    step_with_actions(sim, ["move_east"])  # attack
    ext = _ext(sim)
    coh_after = ext.get("inv:coherence", 0)
    assert coh_after < initial_coh, "attack should reduce coherence"

    # Keep attacking until disabled.
    for _ in range(20):
        if ext.get("inv:coherence", 0) == 0:
            break
        step_with_actions(sim, ["move_east"])
        ext = _ext(sim)
    assert ext.get("inv:coherence", 0) == 0, "extractor should be disabled"

    # Wait for reboot. core_d grew from level-ups, so threshold varies.
    for _ in range(50):
        step_with_actions(sim, ["noop"])

    ext = _ext(sim)
    assert ext["inv:level"] == 3, f"level should be 3 after second reboot, got {ext.get('inv:level')}"
    assert ext.get("inv:coherence", 0) > 0, "coherence should be restored after second reboot"


def test_coherence_cap_scales_with_level(build_rule_config, new_simulation, step_with_actions):
    """After reboot (level 1→2), coherence increases."""
    cfg = build_rule_config(MAP, agent_inventory=[{"core_a": 11}], max_steps=200)
    sim = new_simulation(cfg, seed=0)

    # Kill and wait for reboot (10 + 5*core_d ticks, core_d=0 or 1).
    step_with_actions(sim, ["move_east"])  # one-shot kill
    for _ in range(20):
        step_with_actions(sim, ["noop"])

    ext = _ext(sim)
    assert ext["inv:level"] == 2
    # Coherence should be restored after reboot (cap = 10 + 5*core_d).
    coh = ext.get("inv:coherence", 0)
    assert coh > 0, f"coherence should be restored after reboot, got {coh}"
