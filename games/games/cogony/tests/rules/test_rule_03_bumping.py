"""Rule 3 -- Bumping (RULES.md section 3).

Validates combat resolution (attack formula with 4 subsystems),
strike-back, extractor collection, junction alignment, and vibe overrides.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

# Agent next to a carbon extractor.
MAP_AGENT_EXTRACTOR = [
    ["#", "#", "#", "#"],
    ["#", "@", "c", "#"],
    ["#", "#", "#", "#"],
]

# Agent with one empty space then junction.
MAP_AGENT_JUNCTION = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", ".", "j", "#"],
    ["#", "#", "#", "#", "#"],
]

# Two agents adjacent to each other.
MAP_TWO_AGENTS = [
    ["#", "#", "#", "#"],
    ["#", "@", "@", "#"],
    ["#", "#", "#", "#"],
]


# ---------------------------------------------------------------------------
# Extractor combat
# ---------------------------------------------------------------------------


_ZERO_ATK = {"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}
_FIXED_EXT = {"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0,
              "core_d": 1, "os_d": 1, "gen_d": 1, "storage_d": 1}


def _set_extractor_stats(cfg, stats=None):
    """Set deterministic extractor stats for testing."""
    for key, obj in cfg.game.objects.items():
        if "extractor" in key:
            obj.inventory.initial.update(stats or _FIXED_EXT)


def test_attack_extractor_reduces_coherence(build_rule_config, new_simulation, step_with_actions):
    """Bumping an extractor with Dmg[Core]=3 vs Res[Core]=1 deals 2 damage."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR, agent_inventory=[{**_ZERO_ATK, "core_a": 3}])
    _set_extractor_stats(cfg)

    sim = new_simulation(cfg)

    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 10

    step_with_actions(sim, ["move_east"])

    # max(0, 3 - 1) = 2 damage -> coherence 10 - 2 = 8.
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 8


def test_multi_channel_damage_sums(build_rule_config, new_simulation, step_with_actions):
    """Damage sums across all four subsystems (minus node resist per subsystem)."""
    cfg = build_rule_config(
        MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 2, "os_a": 3, "gen_a": 1, "storage_a": 4}],
    )
    _set_extractor_stats(cfg)
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    # Per channel vs def=1: Core=max(0,2-1)=1, OS=max(0,3-1)=2, Gen=max(0,1-1)=0, Stor=max(0,4-1)=3.
    # Total = 6 -> coherence 10 - 6 = 4.
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 4


def test_resist_reduces_damage_per_channel(build_rule_config, new_simulation, step_with_actions):
    """Resist is subtracted per-subsystem before summing."""
    cfg = build_rule_config(
        MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 5, "os_a": 2}],
    )
    _set_extractor_stats(cfg, {"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0,
                                "core_d": 3, "os_d": 5, "gen_d": 1, "storage_d": 1})

    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])

    # Core: max(0, 5 - 3) = 2
    # OS: max(0, 2 - 5) = 0  (resist exceeds damage)
    # Gen: max(0, 0 - 1) = 0
    # Storage: max(0, 0 - 1) = 0
    # Total = 2 -> coherence 10 - 2 = 8.
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 8


def test_strike_back_damages_attacker(build_rule_config, new_simulation, step_with_actions):
    """Target with core_a=3 vs attacker core_d=1 -> attacker loses 2 coherence.

    Strike-back: if the target survives, it hits back using its own Dmg vs
    the attacker's Res.
    """
    cfg = build_rule_config(
        MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 2, "core_d": 1}],
    )
    _set_extractor_stats(cfg, {**_FIXED_EXT, "core_a": 3})

    sim = new_simulation(cfg)
    initial_coh = sim.agent(0).inventory["coherence"]

    step_with_actions(sim, ["move_east"])

    # Strike-back = max(0, 3 - 1) = 2.
    assert sim.agent(0).inventory["coherence"] == initial_coh - 2
    # Extractor damage: Core=max(0, 2-1)=1, OS/Gen/Storage: max(0, 0-1)=0 each.
    # Total = 1 -> coherence 10 - 1 = 9.
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 9


def test_no_damage_when_all_channels_zero(build_rule_config, new_simulation, step_with_actions):
    """Agent with no Dmg stats deals 0 damage."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR, agent_inventory=[_ZERO_ATK])
    _set_extractor_stats(cfg)
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 10  # Unchanged.


# ---------------------------------------------------------------------------
# Extractor collection
# ---------------------------------------------------------------------------


def test_collect_from_disabled_extractor(build_rule_config, new_simulation, step_with_actions):
    """Kill an extractor then collect its element loot.

    CogonyAttackMutation drops rand(1, level*10) of the extractor's
    element on the target when the killing blow lands. Next bump collects.
    """
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR, agent_inventory=[{"core_a": 21}])

    sim = new_simulation(cfg)
    assert sim.agent(0).inventory.get("carbon", 0) == 0

    # Tick 1: attack kills extractor → drops carbon.
    step_with_actions(sim, ["move_east"])

    # Tick 2: bump again to collect.
    step_with_actions(sim, ["move_east"])

    assert sim.agent(0).inventory.get("carbon", 0) > 0


# ---------------------------------------------------------------------------
# Junction combat & alignment
# ---------------------------------------------------------------------------


def test_attack_junction_reduces_coherence(build_rule_config, new_simulation, step_with_actions):
    """Bumping a live junction deals channel damage (accounting for node resist)."""
    cfg = build_rule_config(MAP_AGENT_JUNCTION, agent_inventory=[{**_ZERO_ATK, "core_a": 5}])
    # Set deterministic junction stats.
    cfg.game.objects["junction"].inventory.initial.update(_FIXED_EXT)
    sim = new_simulation(cfg)

    # Move to (1,2) first.
    step_with_actions(sim, ["move_east"])
    # Bump junction at (1,3).
    step_with_actions(sim, ["move_east"])

    junc = _junction(sim)
    # core_a=5 - core_d=1 (node level 1) = 4 -> coherence 10 - 4 = 6.
    assert junc.get("inv:coherence") == 6


def test_align_junction_when_disabled(build_rule_config, new_simulation, step_with_actions):
    """Bumping a disabled junction as a team member near hub aligns it."""
    map_with_hub = [
        ["#", "#", "#", "#", "#", "#"],
        ["#", "h", "@", ".", "j", "#"],
        ["#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(
        map_with_hub,
        agent_inventory=[{"core_a": 21}],
    )
    sim = new_simulation(cfg)

    # Join team by bumping hub (move west).
    step_with_actions(sim, ["move_west"])
    # Move back east toward junction.
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    # Attack junction at (1,4) -> coherence 10 - max(0, 21-1) = 0.
    step_with_actions(sim, ["move_east"])

    junc = _junction(sim)
    assert junc.get("inv:coherence", 0) == 0

    # Bump again to align (hub within radius 25, agent has team tag).
    step_with_actions(sim, ["move_east"])

    junc = _junction(sim)
    tag_names = _tag_names(cfg, junc)
    assert "team:cogs_red" in tag_names


def test_align_junction_requires_nearby_hub(build_rule_config, new_simulation, step_with_actions):
    """Cannot align a junction if no hub or aligned junction is nearby."""
    map_no_hub = [
        ["#", "#", "#", "#"],
        ["#", "@", "j", "#"],
        ["#", "#", "#", "#"],
    ]
    cfg = build_rule_config(
        map_no_hub,
        agent_inventory=[{"core_a": 21}],
        agent_tags=[["team:cogs_red"]],
    )
    sim = new_simulation(cfg)

    # Kill the junction.
    step_with_actions(sim, ["move_east"])
    junc = _junction(sim)
    assert junc.get("inv:coherence", 0) == 0

    # Bump again — should fail (no hub/net nearby).
    step_with_actions(sim, ["move_east"])

    junc = _junction(sim)
    tag_names = _tag_names(cfg, junc)
    assert "team:cogs_red" not in tag_names


# ---------------------------------------------------------------------------
# Agent vs Agent
# ---------------------------------------------------------------------------


def test_bump_cog_does_nothing_by_default(build_rule_config, new_simulation, step_with_actions):
    """Bumping another cog does nothing without a vibe override."""
    cfg = build_rule_config(
        MAP_TWO_AGENTS,
        agent_inventory=[{"core_a": 4}, {}],
    )
    cfg.game.agents[1].inventory.initial["coherence"] = 40

    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east", "noop"])

    assert sim.agent(1).inventory["coherence"] == 40


def test_loot_disabled_cog(build_rule_config, new_simulation, step_with_actions):
    """Bumping a disabled cog transfers its elements."""
    cfg = build_rule_config(MAP_TWO_AGENTS)
    # Give agent 1 some carbon and set coherence=0.
    cfg.game.agents[1].inventory.initial["coherence"] = 0
    cfg.game.agents[1].inventory.initial["carbon"] = 20

    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east", "noop"])

    # Agent 0 should have looted agent 1's carbon.
    assert sim.agent(0).inventory.get("carbon", 0) == 20
    assert sim.agent(1).inventory.get("carbon", 0) == 0


# ---------------------------------------------------------------------------
# Vibe overrides
# ---------------------------------------------------------------------------


def test_vibe_attack_attacks_cog(build_rule_config, new_simulation, step_with_actions):
    """With vibe_attack, bumping a cog attacks it."""
    zero_atk = {"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}
    cfg = build_rule_config(
        MAP_TWO_AGENTS,
        agent_inventory=[{**zero_atk, "core_a": 3}, {**zero_atk}],
    )
    sim = new_simulation(cfg)

    initial_coh = sim.agent(1).inventory["coherence"]
    step_with_actions(sim, ["change_vibe_attack", "noop"])
    step_with_actions(sim, ["move_east", "noop"])

    # max(0, 3 - 0) = 3 damage.
    assert sim.agent(1).inventory["coherence"] == initial_coh - 3


def test_vibe_patch_heals_cog(build_rule_config, new_simulation, step_with_actions):
    """With vibe_patch, bumping a cog heals it by 10*core_a, costs 10 energy."""
    cfg = build_rule_config(
        MAP_TWO_AGENTS,
        # Agent 1 needs core_d=10 for max_coh=60 so heal is visible.
        agent_inventory=[{"core_a": 2, "energy": 100}, {"core_d": 10}],
    )
    cfg.game.agents[1].inventory.initial["coherence"] = 5

    sim = new_simulation(cfg)

    step_with_actions(sim, ["change_vibe_patch", "noop"])

    # Bump: should heal target by 10*2=20 coherence, drain 10 energy.
    step_with_actions(sim, ["move_east", "noop"])

    assert sim.agent(1).inventory["coherence"] == 25  # 5 + 20
    # 100 - 10 (self-heal tick when vibe set) - 10 (self-heal tick) - 10 (bump)
    assert sim.agent(0).inventory["energy"] == 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extractor(sim) -> dict:
    """Find the first extractor on the grid."""
    for o in sim.grid_objects().values():
        if "extractor" in o.get("type_name", ""):
            return o
    raise AssertionError("no extractor found")


def _junction(sim) -> dict:
    """Find the first junction on the grid."""
    for o in sim.grid_objects().values():
        if o.get("type_name") == "junction":
            return o
    raise AssertionError("no junction found")


def _tag_names(cfg, obj) -> list[str]:
    """Map an object's tag_ids to tag names."""
    tag_names_list = list(cfg.game.id_map().tag_names())
    return [
        tag_names_list[tid] if tid < len(tag_names_list) else f"#{tid}"
        for tid in obj.get("tag_ids", [])
    ]
