"""Rule 4 -- Stake-based team economics (bonding curve).

Validates the full stake lifecycle:
- Bonding curve pricing: mint costs k*(s+1), burn refunds k*s.
- Dividend settlement: payout = q * (dps - basis), basis resets.
- Closed curve: mints and burns are exact inverses.
- Edge cases: can't mint without creds, can't burn with 0 stakes.
- Invested/dividends tracking for P&L.
- Hub observation: team-scoped buy price, sell price, and total stakes.
- Station observation: buy station shows only buy price; sell station shows only sell price.
"""

from __future__ import annotations

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent.runtime.observation import ObservationEnvelope, decode_observation

MAP_BUY = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "+", "h", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_SELL = [
    ["#", "#", "#", "#", "#"],
    ["#", "@", "-", "h", "#"],
    ["#", "#", "#", "#", "#"],
]

MAP_BUY_SELL = [
    ["#", "#", "#", "#", "#", "#"],
    ["#", "+", "@", "-", "h", "#"],
    ["#", "#", "#", "#", "#", "#"],
]

K = 10


def _buy(sim, step_fn, n=1):
    """Mint n stakes by bumping buy station repeatedly."""
    for _ in range(n):
        step_fn(sim, ["move_east"])


def _sell(sim, step_fn, n=1):
    """Burn n stakes. Agent must be adjacent to sell station."""
    for _ in range(n):
        step_fn(sim, ["move_east"])


def _hub(sim) -> dict:
    for o in sim.grid_objects().values():
        if o.get("type_name") == "hub":
            return o
    raise AssertionError("no hub found")


def _inv(sim, res):
    return sim.agent(0).inventory.get(res, 0)


def _obs_features_by_type(sim) -> dict[str, dict[str, int]]:
    pei = PolicyEnvInterface.from_mg_cfg(sim.config)
    decoded = decode_observation(ObservationEnvelope(
        raw_observation=sim.observations()[0],
        policy_env_info=pei,
        step=sim.current_step,
    ))
    by_type = {}
    for cell in decoded.cells:
        type_tags = [tag for tag in cell.tags if tag.startswith("type:")]
        if type_tags:
            by_type[type_tags[0].removeprefix("type:")] = cell.features
    return by_type


# ---------------------------------------------------------------------------
# Bonding curve pricing
# ---------------------------------------------------------------------------


def test_bonding_curve_three_stakes(build_rule_config, new_simulation, step_with_actions):
    """Minting 3 stakes costs 10+20+30=60 total (k=10)."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    _buy(sim, step_with_actions, 3)

    assert _inv(sim, "red_stake") == 3
    assert _inv(sim, "creds") == 140  # 200 - 60


def test_closed_curve_mint_then_burn_all(build_rule_config, new_simulation, step_with_actions):
    """Mint 3 via buy, burn 3 via sell -> exact creds restoration."""
    cfg = build_rule_config(MAP_BUY_SELL, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_west"])  # mint #1: cost 10
    step_with_actions(sim, ["move_west"])  # mint #2: cost 20
    step_with_actions(sim, ["move_west"])  # mint #3: cost 30
    assert _inv(sim, "red_stake") == 3
    assert _inv(sim, "creds") == 140

    step_with_actions(sim, ["move_east"])  # back toward center
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])  # burn #1 refund 30
    step_with_actions(sim, ["move_east"])  # burn #2 refund 20
    step_with_actions(sim, ["move_east"])  # burn #3 refund 10

    assert _inv(sim, "red_stake") == 0
    assert _inv(sim, "creds") == 200


def test_mint_blocked_without_creds(build_rule_config, new_simulation, step_with_actions):
    """Can't mint if creds < k*(s+1). First stake costs 10."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 5}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert _inv(sim, "red_stake") == 0
    assert _inv(sim, "creds") == 5


def test_burn_blocked_with_no_stakes(build_rule_config, new_simulation, step_with_actions):
    """Can't burn if agent holds 0 stakes."""
    cfg = build_rule_config(MAP_SELL, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert _inv(sim, "red_stake") == 0
    assert _inv(sim, "creds") == 100


def test_stake_resources_per_team(build_rule_config, new_simulation, step_with_actions):
    """Minting red stakes doesn't affect blue/green/yellow stake counts."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_east"])

    assert _inv(sim, "red_stake") == 1
    assert _inv(sim, "blue_stake") == 0
    assert _inv(sim, "green_stake") == 0
    assert _inv(sim, "yellow_stake") == 0


# ---------------------------------------------------------------------------
# Invested / dividends tracking
# ---------------------------------------------------------------------------


def test_invested_tracks_mint_cost(build_rule_config, new_simulation, step_with_actions):
    """Minting 3 stakes records invested = 10+20+30 = 60."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    _buy(sim, step_with_actions, 3)

    assert _inv(sim, "red_invested") == 60


def test_invested_tracks_single_mint(build_rule_config, new_simulation, step_with_actions):
    """Single mint: invested = k*(0+1) = 10."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    _buy(sim, step_with_actions, 1)

    assert _inv(sim, "red_invested") == K


def test_dividends_tracks_sell_refund(build_rule_config, new_simulation, step_with_actions):
    """Burning stakes records refunds in dividends counter."""
    cfg = build_rule_config(MAP_BUY_SELL, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_west"])  # mint: cost 10
    step_with_actions(sim, ["move_east"])  # move back
    step_with_actions(sim, ["move_east"])  # burn: refund 10

    assert _inv(sim, "red_dividends") == K


def test_buy3_sell3_net_zero_pnl(build_rule_config, new_simulation, step_with_actions):
    """Buy 3 then sell 3: invested == dividends (net zero P&L)."""
    cfg = build_rule_config(MAP_BUY_SELL, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    # Mint 3.
    step_with_actions(sim, ["move_west"])  # cost 10
    step_with_actions(sim, ["move_west"])  # cost 20
    step_with_actions(sim, ["move_west"])  # cost 30

    assert _inv(sim, "red_invested") == 60
    assert _inv(sim, "red_stake") == 3

    # Move to sell.
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])

    # Burn 3.
    step_with_actions(sim, ["move_east"])  # refund 30
    step_with_actions(sim, ["move_east"])  # refund 20
    step_with_actions(sim, ["move_east"])  # refund 10

    assert _inv(sim, "red_stake") == 0
    assert _inv(sim, "red_invested") == 60
    assert _inv(sim, "red_dividends") == 60  # 30+20+10
    assert _inv(sim, "creds") == 200


def test_buy1_sell1_invested_equals_dividends(build_rule_config, new_simulation, step_with_actions):
    """Simplest round-trip: buy 1, sell 1. invested == dividends == k."""
    cfg = build_rule_config(MAP_BUY_SELL, agent_inventory=[{"creds": 100}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_west"])  # mint: cost 10
    step_with_actions(sim, ["move_east"])  # move back
    step_with_actions(sim, ["move_east"])  # burn: refund 10

    assert _inv(sim, "red_invested") == K
    assert _inv(sim, "red_dividends") == K
    assert _inv(sim, "red_stake") == 0
    assert _inv(sim, "creds") == 100


# ---------------------------------------------------------------------------
# Visible stake economy bookkeeping
# ---------------------------------------------------------------------------


def test_hub_total_stakes_after_mints(build_rule_config, new_simulation, step_with_actions):
    """Hub red_total_stakes = number of outstanding red stakes."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    _buy(sim, step_with_actions, 3)
    hub = _hub(sim)
    assert hub["inv:red_total_stakes"] == 3


def test_hub_does_not_expose_redundant_stake_bookkeeping(build_rule_config, new_simulation, step_with_actions):
    """Hub does not expose generic stake accounting fields."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    _buy(sim, step_with_actions, 3)
    hub = _hub(sim)
    forbidden = {
        "inv:total_stake",
        "inv:curve_reserve",
        "inv:stake_cost",
        "inv:stake_buy_price",
        "inv:stake_sell_price",
        "inv:dividend_per_stake",
    }
    assert forbidden.isdisjoint(hub)


def test_hub_stake_price_display(build_rule_config, new_simulation, step_with_actions):
    """Hub exposes current team-scoped buy and sell prices."""
    cfg = build_rule_config(MAP_BUY, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    hub = _hub(sim)
    assert hub["inv:red_stake_buy_price"] == K  # k*(0+1) = 10
    assert hub.get("inv:red_stake_sell_price", 0) == 0

    _buy(sim, step_with_actions, 2)
    hub = _hub(sim)
    assert hub["inv:red_stake_buy_price"] == K * 3  # k*(2+1) = 30
    assert hub["inv:red_stake_sell_price"] == K * 2  # k*2


def test_hub_resources_after_full_cycle(build_rule_config, new_simulation, step_with_actions):
    """After buy 3, sell 3: hub returns to zero stakes and initial prices."""
    cfg = build_rule_config(MAP_BUY_SELL, agent_inventory=[{"creds": 200}])
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_west"])
    step_with_actions(sim, ["move_west"])
    step_with_actions(sim, ["move_west"])

    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])

    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])
    step_with_actions(sim, ["move_east"])

    hub = _hub(sim)
    assert hub.get("inv:red_total_stakes", 0) == 0
    assert hub["inv:red_stake_buy_price"] == K  # k*(0+1) back to initial
    assert hub.get("inv:red_stake_sell_price", 0) == 0


def test_stake_station_and_hub_expose_only_relevant_team_scoped_stake_economics(
    build_rule_config,
    new_simulation,
    step_with_actions,
):
    """Stake stations expose only their relevant price; hub exposes all team economy fields."""
    map_stakes_junction = [
        ["#", "#", "#", "#", "#", "#", "#"],
        ["#", "+", "@", "-", "h", "j", "#"],
        ["#", "#", "#", "#", "#", "#", "#"],
    ]
    cfg = build_rule_config(map_stakes_junction, agent_inventory=[{"creds": 200}], max_steps=120)
    cfg.game.objects["junction"].tags.append("team:cogs_red")
    sim = new_simulation(cfg)

    step_with_actions(sim, ["move_west"])
    step_with_actions(sim, ["move_west"])
    for _ in range(98):
        step_with_actions(sim, ["noop"])

    observed = _obs_features_by_type(sim)
    hub_expected = {
        "inv:red_stake_buy_price": 30,
        "inv:red_stake_sell_price": 20,
        "inv:red_total_stakes": 2,
    }
    generic_forbidden = {
        "inv:stake_buy_price",
        "inv:stake_sell_price",
        "inv:stake_cost",
        "inv:total_stake",
        "inv:curve_reserve",
        "inv:revenue",
        "inv:dividend_per_stake",
    }

    assert observed["stake_buy_station"]["inv:red_stake_buy_price"] == 30
    assert "inv:red_stake_sell_price" not in observed["stake_buy_station"]
    assert "inv:red_total_stakes" not in observed["stake_buy_station"]

    assert observed["stake_sell_station"]["inv:red_stake_sell_price"] == 20
    assert "inv:red_stake_buy_price" not in observed["stake_sell_station"]
    assert "inv:red_total_stakes" not in observed["stake_sell_station"]

    assert {k: observed["hub"][k] for k in hub_expected} == hub_expected

    for type_name in ["stake_buy_station", "stake_sell_station", "hub"]:
        assert generic_forbidden.isdisjoint(observed[type_name])
