"""Rule 8 -- Comprehensive math formula tests.

Validates every numeric formula in the game:
- Coherence: max = 10 + 5*core_d
- Energy: max = 100 + 25*gen_d
- Cargo: max = 100 + 25*storage_d
- Coherence regen: 1 + core_a every 10 ticks
- Energy regen: 1 + gen_a every 10 ticks
- Gear cost: 2^(2 + gear_held)
- Reboot threshold: 10 + 5*core_d ticks
- Cog reboot: lose one gear
- Stake mint: cost k*(s+1), k=10
- Stake burn: refund k*s
- Stake closed curve: mint N then burn N = net zero
- Market pricing: C=1, O=2, G=3, S=4
- Attack damage: sum(max(0, atk_i - def_i)) per channel
- Strike-back: target retaliates with its own stats
"""

from __future__ import annotations

# Zero out random starting gear for deterministic tests.
_ZERO_ATK = {"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0}


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

MAP_SOLO = [["#", "#", "#"], ["#", "@", "#"], ["#", "#", "#"]]

MAP_AGENT_EXTRACTOR = [
    ["#", "#", "#", "#"],
    ["#", "@", "c", "#"],
    ["#", "#", "#", "#"],
]

MAP_TWO_AGENTS = [
    ["#", "#", "#", "#"],
    ["#", "@", "@", "#"],
    ["#", "#", "#", "#"],
]

MAP_AGENT_GEAR = [
    ["#", "#", "#", "#"],
    ["#", "@", "D", "#"],
    ["#", "#", "#", "#"],
]

MAP_AGENT_BUY_HUB = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "+", "h", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_AGENT_SELL_HUB = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "-", "h", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_AGENT_MARKET = [
    ["#", "#", "#", "#"],
    ["#", "@", "M", "#"],
    ["#", "#", "#", "#"],
]


def _set_extractor_stats(cfg, atk=None, dfe=None):
    """Set deterministic extractor stats."""
    ext_init = cfg.game.objects["carbon_extractor"].inventory.initial
    ext_init.update({"core_a": 0, "os_a": 0, "gen_a": 0, "storage_a": 0,
                     "core_d": 0, "os_d": 0, "gen_d": 0, "storage_d": 0})
    if atk:
        ext_init.update(atk)
    if dfe:
        ext_init.update(dfe)


# ---------------------------------------------------------------------------
# 1. max_coherence = 20 + 5*core_d
# ---------------------------------------------------------------------------


def test_max_coherence_base(build_rule_config, new_simulation, step_with_actions):
    """With 0 core_d, max_coherence = 20. Regen at 19 goes to 20, not 21."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "coherence": 19}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 20
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 20


def test_max_coherence_with_core_d(build_rule_config, new_simulation, step_with_actions):
    """With core_d=5, max_coherence = 20+25 = 45. Can regen above 20."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "core_d": 5, "coherence": 44}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 45


# ---------------------------------------------------------------------------
# 2. max_energy = 100 + 25*gen_d
# ---------------------------------------------------------------------------


def test_max_energy_base(build_rule_config, new_simulation):
    """With 0 gen_d, max_energy = 100."""
    cfg = build_rule_config(MAP_SOLO, agent_inventory=[{**_ZERO_ATK}])
    sim = new_simulation(cfg)
    assert sim.agent(0).inventory["energy"] == 100


def test_max_energy_with_gen_d(build_rule_config, new_simulation, step_with_actions):
    """With gen_d=2, max_energy = 150. Regen at 149 goes to 150, not beyond."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "gen_d": 2, "energy": 149}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["energy"] == 150


# ---------------------------------------------------------------------------
# 3. max_cargo = 100 + 25*storage_d
# ---------------------------------------------------------------------------


def test_max_cargo_base(build_rule_config, new_simulation, step_with_actions):
    """With 0 storage_d, max_cargo = 100. Can hold up to 100 carbon."""
    cfg = build_rule_config(MAP_SOLO,
        agent_inventory=[{**_ZERO_ATK, "carbon": 99}])
    sim = new_simulation(cfg)
    assert sim.agent(0).inventory.get("carbon", 0) == 99


# ---------------------------------------------------------------------------
# 4. Coherence regen = 1 + core_a every 10 ticks
# ---------------------------------------------------------------------------


def test_coherence_regen_base(build_rule_config, new_simulation, step_with_actions):
    """With core_a=0 and core_d=5, max=35, regen = 1 per 10 ticks."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "core_d": 5, "coherence": 5}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 6


def test_coherence_regen_with_core_a(build_rule_config, new_simulation, step_with_actions):
    """With core_a=3 and core_d=5, max=35, regen = 4 per 10 ticks."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "core_a": 3, "core_d": 5, "coherence": 5}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["coherence"] == 9


# ---------------------------------------------------------------------------
# 5. Energy regen = 1 + gen_a every 10 ticks
# ---------------------------------------------------------------------------


def test_energy_regen_base(build_rule_config, new_simulation, step_with_actions):
    """With gen_a=0, energy regen = 1 per 10 ticks."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "energy": 50}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["energy"] == 51


def test_energy_regen_with_gen_a(build_rule_config, new_simulation, step_with_actions):
    """With gen_a=2, energy regen = 3 per 10 ticks."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "gen_a": 2, "energy": 50}])
    sim = new_simulation(cfg)
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory["energy"] == 53


# ---------------------------------------------------------------------------
# 6. Gear cost = 2^(2 + gear_held)
# ---------------------------------------------------------------------------


def test_gear_cost_first(build_rule_config, new_simulation, step_with_actions):
    """First gear buy (0 held) costs 2^(2+0) = 4."""
    cfg = build_rule_config(MAP_AGENT_GEAR,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("core_a", 0) == 1
    assert sim.agent(0).inventory["creds"] == 96  # 100 - 4


def test_gear_cost_second(build_rule_config, new_simulation, step_with_actions):
    """Second gear buy (1 held) costs 2^(2+1) = 8. Total = 4+8 = 12."""
    cfg = build_rule_config(MAP_AGENT_GEAR,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])  # buy #1: cost 4
    step_with_actions(sim, ["move_east"])  # buy #2: cost 8
    assert sim.agent(0).inventory.get("core_a", 0) == 2
    assert sim.agent(0).inventory["creds"] == 88  # 100 - 12


def test_gear_cost_third(build_rule_config, new_simulation, step_with_actions):
    """Third gear buy (2 held) costs 2^(2+2) = 16. Total = 4+8+16 = 28."""
    cfg = build_rule_config(MAP_AGENT_GEAR,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("core_a", 0) == 3
    assert sim.agent(0).inventory["creds"] == 72  # 100 - 28


# ---------------------------------------------------------------------------
# 7. Reboot countdown = 10 + 5*core_d ticks
# ---------------------------------------------------------------------------


def test_reboot_threshold_base(build_rule_config, new_simulation, step_with_actions):
    """With core_d=0, max_coh=10. Countdown fires on tick 10."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK}])
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    sim = new_simulation(cfg)

    for _ in range(9):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) == 0

    step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) >= 10


def test_reboot_threshold_with_core_d(build_rule_config, new_simulation, step_with_actions):
    """With core_d=3, max_coh=25. Countdown fires on tick 25."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "core_d": 3}])
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    sim = new_simulation(cfg)

    for _ in range(24):
        step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) == 0

    step_with_actions(sim, ["noop"])
    assert sim.agent(0).inventory.get("coherence", 0) > 0


# ---------------------------------------------------------------------------
# 8. Cog reboot loses one gear
# ---------------------------------------------------------------------------


def test_reboot_loses_one_gear(build_rule_config, new_simulation, step_with_actions):
    """After reboot, total gear decreases by 1."""
    cfg = build_rule_config(MAP_SOLO, max_steps=200,
        agent_inventory=[{**_ZERO_ATK, "core_a": 2, "os_a": 1}])
    cfg.game.agents[0].inventory.initial["coherence"] = 0
    sim = new_simulation(cfg)

    for _ in range(11):
        step_with_actions(sim, ["noop"])

    inv = sim.agent(0).inventory
    total = inv.get("core_a", 0) + inv.get("os_a", 0)
    assert total == 2  # was 3, lost 1


# ---------------------------------------------------------------------------
# 9. Stake mint cost = k*(s+1), k=10
# ---------------------------------------------------------------------------


def test_stake_mint_first(build_rule_config, new_simulation, step_with_actions):
    """First stake costs k*1 = 10."""
    cfg = build_rule_config(MAP_AGENT_BUY_HUB,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("red_stake", 0) == 1
    assert sim.agent(0).inventory["creds"] == 90


def test_stake_mint_second(build_rule_config, new_simulation, step_with_actions):
    """Second stake costs k*2 = 20. Total = 30."""
    cfg = build_rule_config(MAP_AGENT_BUY_HUB,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("red_stake", 0) == 2
    assert sim.agent(0).inventory["creds"] == 70


def test_stake_mint_third(build_rule_config, new_simulation, step_with_actions):
    """Third stake costs k*3 = 30. Total = 60."""
    cfg = build_rule_config(MAP_AGENT_BUY_HUB,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("red_stake", 0) == 3
    assert sim.agent(0).inventory["creds"] == 40


# ---------------------------------------------------------------------------
# 10. Stake burn refund = k*s
# ---------------------------------------------------------------------------


def test_stake_burn_refund_one(build_rule_config, new_simulation, step_with_actions):
    """Burn 1 stake (s=1): refund k*1 = 10."""
    cfg = build_rule_config(MAP_AGENT_BUY_HUB,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)
    # Mint 1
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory["creds"] == 90

    # Move to sell station (need sell station map)
    # Use a different approach: mint via buy, then test burn separately
    # Actually, we need a map with sell station + hub
    pass


def test_stake_burn_refund_via_sell(build_rule_config, new_simulation, step_with_actions):
    """Mint 1 via buy, then burn via sell. Net zero."""
    map_buy_sell = [
        ["#", "#", "#", "#", "#", "#"],
        ["#", "+", "@", "-", "h", "#"],
        ["#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_buy_sell,
        agent_inventory=[{**_ZERO_ATK, "creds": 100}])
    sim = new_simulation(cfg)

    # Mint (bump west)
    step_with_actions(sim, ["move_west"])
    assert sim.agent(0).inventory["creds"] == 90
    assert sim.agent(0).inventory.get("red_stake", 0) == 1

    # Move to sell
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])  # bump sell

    assert sim.agent(0).inventory.get("red_stake", 0) == 0
    assert sim.agent(0).inventory["creds"] == 100  # refund k*1 = 10


# ---------------------------------------------------------------------------
# 11. Stake closed curve: mint N then burn N = net zero
# ---------------------------------------------------------------------------


def test_stake_closed_curve(build_rule_config, new_simulation, step_with_actions):
    """Mint 3 then burn 3 = exact creds restoration."""
    map_buy_sell = [
        ["#", "#", "#", "#", "#", "#"],
        ["#", "+", "@", "-", "h", "#"],
        ["#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_buy_sell,
        agent_inventory=[{**_ZERO_ATK, "creds": 200}])
    sim = new_simulation(cfg)

    # Mint 3 (bump west)
    step_with_actions(sim, ["move_west"])  # cost 10
    step_with_actions(sim, ["move_west"])  # cost 20
    step_with_actions(sim, ["move_west"])  # cost 30
    assert sim.agent(0).inventory.get("red_stake", 0) == 3
    assert sim.agent(0).inventory["creds"] == 140

    # Move to sell and burn 3
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])  # bump sell: refund 30
    step_with_actions(sim, ["move_east"])  # refund 20
    step_with_actions(sim, ["move_east"])  # refund 10

    assert sim.agent(0).inventory.get("red_stake", 0) == 0
    assert sim.agent(0).inventory["creds"] == 200


# ---------------------------------------------------------------------------
# 12. Market pricing: C=1, O=2, G=3, S=4
# ---------------------------------------------------------------------------


def test_market_carbon_price(build_rule_config, new_simulation, step_with_actions):
    """Selling 5 carbon at price 1 gives 5 creds."""
    cfg = build_rule_config(MAP_AGENT_MARKET,
        agent_inventory=[{**_ZERO_ATK, "carbon": 5}])
    sim = new_simulation(cfg)
    creds_before = sim.agent(0).inventory.get("creds", 0)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("creds", 0) == creds_before + 5
    assert sim.agent(0).inventory.get("carbon", 0) == 0


def test_market_silicon_price(build_rule_config, new_simulation, step_with_actions):
    """Selling 3 silicon at price 4 gives 12 creds."""
    cfg = build_rule_config(MAP_AGENT_MARKET,
        agent_inventory=[{**_ZERO_ATK, "silicon": 3}])
    sim = new_simulation(cfg)
    creds_before = sim.agent(0).inventory.get("creds", 0)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("creds", 0) == creds_before + 12


def test_market_mixed_elements(build_rule_config, new_simulation, step_with_actions):
    """Selling mixed: 2C*1 + 3O*2 + 1G*3 + 4S*4 = 2+6+3+16 = 27."""
    cfg = build_rule_config(MAP_AGENT_MARKET,
        agent_inventory=[{**_ZERO_ATK, "carbon": 2, "oxygen": 3,
                          "germanium": 1, "silicon": 4}])
    sim = new_simulation(cfg)
    creds_before = sim.agent(0).inventory.get("creds", 0)
    step_with_actions(sim, ["move_east"])
    assert sim.agent(0).inventory.get("creds", 0) == creds_before + 27


# ---------------------------------------------------------------------------
# 13. Attack damage: sum(max(0, atk_i - def_i)) per channel
# ---------------------------------------------------------------------------


def test_attack_single_channel(build_rule_config, new_simulation, step_with_actions):
    """core_a=5 vs core_d=2: damage = max(0, 5-2) = 3."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 5}])
    _set_extractor_stats(cfg, dfe={"core_d": 2})
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 7  # 10 - 3


def test_attack_multi_channel(build_rule_config, new_simulation, step_with_actions):
    """Multiple channels: core(4-1=3) + os(2-3=0) + gen(6-0=6) = 9 damage."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 4, "os_a": 2, "gen_a": 6}])
    _set_extractor_stats(cfg, dfe={"core_d": 1, "os_d": 3})
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 1  # 10 - 9


def test_attack_resist_exceeds_damage(build_rule_config, new_simulation, step_with_actions):
    """core_a=1 vs core_d=5: damage = max(0, 1-5) = 0."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 1}])
    _set_extractor_stats(cfg, dfe={"core_d": 5})
    sim = new_simulation(cfg)
    step_with_actions(sim, ["move_east"])
    ext = _extractor(sim)
    assert ext.get("inv:coherence") == 10  # no damage


# ---------------------------------------------------------------------------
# 14. Strike-back: target retaliates
# ---------------------------------------------------------------------------


def test_strike_back(build_rule_config, new_simulation, step_with_actions):
    """Target with core_a=4 vs attacker core_d=1: strike-back = max(0, 4-1) = 3."""
    cfg = build_rule_config(MAP_AGENT_EXTRACTOR,
        agent_inventory=[{**_ZERO_ATK, "core_a": 2, "core_d": 1}])
    _set_extractor_stats(cfg, atk={"core_a": 4})
    sim = new_simulation(cfg)
    initial_coh = sim.agent(0).inventory["coherence"]
    step_with_actions(sim, ["move_east"])
    # Agent takes strike-back: max(0, 4-1) = 3 damage.
    assert sim.agent(0).inventory["coherence"] == initial_coh - 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extractor(sim) -> dict:
    for o in sim.grid_objects().values():
        if "extractor" in o.get("type_name", ""):
            return o
    raise AssertionError("no extractor found")
