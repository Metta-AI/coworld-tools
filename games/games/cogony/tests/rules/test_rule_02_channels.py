"""Rule 2 -- Channels (RULES.md section 2).

Validates that the 8 channel-stat resources (Attack/Defense for
Core/OS/Generator/Storage) are registered and start at 0 for agents.
Node channel stats are validated in test_rule_05_node_levels.
"""

from __future__ import annotations

from cogony.game.channels import CHANNEL_STATS, DMG_STATS, RES_STATS

# Simple 3x3 map with a single agent in the center.
MAP_3x3 = [["#", "#", "#"], ["#", "@", "#"], ["#", "#", "#"]]


def test_eight_channel_stats_exist():
    """CHANNEL_STATS contains exactly 8 entries."""
    assert len(CHANNEL_STATS) == 8


def test_cog_starts_with_one_attack_gear(build_rule_config, new_simulation):
    """Agent starts with exactly 1 random attack gear, 0 defense gear."""
    cfg = build_rule_config(MAP_3x3)
    sim = new_simulation(cfg, seed=0)

    inv = sim.agent(0).inventory
    total_atk = sum(inv.get(s, 0) for s in DMG_STATS)
    total_def = sum(inv.get(s, 0) for s in RES_STATS)
    assert total_atk == 1, f"expected 1 attack gear, got {total_atk}"
    assert total_def == 0, f"expected 0 defense gear, got {total_def}"


def test_channel_stats_on_junction(build_rule_config, new_simulation):
    """Junctions carry all 8 channel-stat resources.

    At level 1 (RULES.md section 4): dmg=0, resist=1.
    """
    map_with_junction = [
        ["#", "#", "#", "#", "#"],
        ["#", "@", ".", "j", "#"],
        ["#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_with_junction)
    sim = new_simulation(cfg, seed=0)

    junction = None
    for o in sim.grid_objects().values():
        if o.get("type_name") == "junction":
            junction = o
            break
    assert junction is not None, "junction must be on the map"

    total_atk = sum(junction.get(f"inv:{s}", 0) for s in DMG_STATS)
    total_def = sum(junction.get(f"inv:{s}", 0) for s in RES_STATS)
    assert total_atk == 1, f"expected 1 attack stat, got {total_atk}"
    assert total_def == 1, f"expected 1 defense stat, got {total_def}"
