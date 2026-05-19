"""Rule 5 -- Node levels (RULES.md section 4).

Validates that extractors and junctions have level-derived stats at level 1,
and that the reboot mechanic increments level on restart.
"""

from __future__ import annotations

from cogony.game.channels import DMG_STATS, RES_STATS

# Map with one agent, one junction, and one carbon extractor.
MAP_NODES = [
    ["#", "#", "#", "#", "#", "#", "#"],
    ["#", "@", ".", "j", ".", "c", "#"],
    ["#", "#", "#", "#", "#", "#", "#"],
]


def test_extractor_starts_at_level_1(build_rule_config, new_simulation, extractor_at):
    """Level-1 extractor: coherence=20, 1 random defense, 1 random attack."""
    cfg = build_rule_config(MAP_NODES, max_steps=200)
    sim = new_simulation(cfg)

    ext = extractor_at(sim, 1, 5)
    assert ext["inv:level"] == 1
    assert ext["inv:coherence"] == 10
    assert ext.get("inv:reboot", 0) == 0

    total_def = sum(ext.get(f"inv:{s}", 0) for s in RES_STATS)
    total_atk = sum(ext.get(f"inv:{s}", 0) for s in DMG_STATS)
    assert total_def == 1, f"expected 1 defense stat, got {total_def}"
    assert total_atk == 1, f"expected 1 attack stat, got {total_atk}"

    assert ext.get("inv:carbon", 0) == 0


def test_junction_starts_at_level_1(build_rule_config, new_simulation, junction_at):
    """Level-1 junction: coherence=10, 1 random defense, 1 random attack."""
    cfg = build_rule_config(MAP_NODES, max_steps=200)
    sim = new_simulation(cfg)

    junc = junction_at(sim, 1, 3)
    assert junc["inv:level"] == 1
    assert junc["inv:coherence"] == 10
    assert junc.get("inv:reboot", 0) == 0

    total_def = sum(junc.get(f"inv:{s}", 0) for s in RES_STATS)
    total_atk = sum(junc.get(f"inv:{s}", 0) for s in DMG_STATS)
    assert total_def == 1
    assert total_atk == 1


def test_node_reboot_increments_level(
    build_rule_config, new_simulation, step_with_actions, junction_at
):
    """After disable + reboot, node level increases to 2.

    Level-1 junction: max_coherence=20, reboot_threshold=5.
    Agent with core_a=21 one-shots the junction (net dmg=max(0,21-1)=20),
    then we step until reboot counter hits threshold and the node restarts.
    """
    cfg = build_rule_config(MAP_NODES, max_steps=200, agent_inventory=[{"core_a": 21}])
    sim = new_simulation(cfg)

    junc = junction_at(sim, 1, 3)
    assert junc["inv:level"] == 1
    assert junc["inv:coherence"] == 10

    # Move east to (1,2).
    step_with_actions(sim, ["move_east"])
    # Bump junction at (1,3) -> attack: net dmg = max(0, 11-1)=10.
    step_with_actions(sim, ["move_east"])

    junc = junction_at(sim, 1, 3)
    coh = junc.get("inv:coherence", 0)
    assert coh == 0, f"junction should be disabled after one-shot, got coherence={coh}"

    # Now step 20 ticks. Reboot threshold = 20 * level = 20 * 1 = 20 ticks.
    # After 20 ticks, reboot=20 >= threshold and node restarts:
    # coherence restored to full, reboot cleared, level incremented to 2.
    for _ in range(20):
        step_with_actions(sim, ["noop"])

    junc = junction_at(sim, 1, 3)
    assert junc["inv:level"] == 2, f"level should be 2 after reboot, got {junc.get('inv:level')}"
    assert junc.get("inv:coherence", 0) > 0, (
        f"coherence should be restored after reboot, got {junc.get('inv:coherence', 0)}"
    )
    assert junc.get("inv:reboot", 0) == 0, (
        f"reboot should be cleared, got {junc.get('inv:reboot', 0)}"
    )
