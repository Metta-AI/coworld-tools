#!/usr/bin/env python3
"""Gameplay metrics dashboard for Tribal Village.

Runs the game for N steps with scripted AI (default behavior), collects
per-step metrics from the observation space, and outputs:
  - Summary table (printed to stdout)
  - CSV file with per-step data
  - JSON summary with aggregated statistics

Usage:
    python scripts/gameplay_metrics.py --steps 1000 --output /tmp/tv_metrics/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Observation layer indices matching src/types.nim ObservationName enum.
# These must stay in sync with the enum order in types.nim.
# Last synced: 2026-03-06 (96 total layers).
LAYER_AGENT = 18        # ThingAgentLayer
LAYER_TREE = 21         # ThingTreeLayer
LAYER_WHEAT = 22        # ThingWheatLayer
LAYER_FISH = 23         # ThingFishLayer
LAYER_STONE = 25        # ThingStoneLayer
LAYER_GOLD = 26         # ThingGoldLayer
LAYER_BUSH = 27         # ThingBushLayer
LAYER_GUARD_TOWER = 42  # ThingGuardTowerLayer
LAYER_MILL = 44         # ThingMillLayer
LAYER_GRANARY = 45      # ThingGranaryLayer
LAYER_LUMBER_CAMP = 46  # ThingLumberCampLayer
LAYER_QUARRY = 47       # ThingQuarryLayer
LAYER_MINING_CAMP = 48  # ThingMiningCampLayer
LAYER_TOWN_CENTER = 51  # ThingTownCenterLayer
LAYER_HOUSE = 52        # ThingHouseLayer
LAYER_BARRACKS = 53     # ThingBarracksLayer
LAYER_ARCHERY_RANGE = 54  # ThingArcheryRangeLayer
LAYER_STABLE = 55       # ThingStableLayer
LAYER_SIEGE_WORKSHOP = 56  # ThingSiegeWorkshopLayer
LAYER_BLACKSMITH = 59   # ThingBlacksmithLayer
LAYER_MARKET = 60       # ThingMarketLayer
LAYER_DOCK = 61         # ThingDockLayer
LAYER_MONASTERY = 62    # ThingMonasteryLayer
LAYER_UNIVERSITY = 63   # ThingUniversityLayer
LAYER_CASTLE = 64       # ThingCastleLayer
LAYER_WONDER = 65       # ThingWonderLayer

LAYER_TEAM = 87         # TeamLayer
LAYER_UNIT_CLASS = 89   # AgentUnitClassLayer
LAYER_IDLE = 90         # AgentIdleLayer
LAYER_TINT = 91         # TintLayer

# Building layers grouped for counting
BUILDING_LAYERS = {
    "town_center": LAYER_TOWN_CENTER,
    "house": LAYER_HOUSE,
    "barracks": LAYER_BARRACKS,
    "archery_range": LAYER_ARCHERY_RANGE,
    "stable": LAYER_STABLE,
    "siege_workshop": LAYER_SIEGE_WORKSHOP,
    "blacksmith": LAYER_BLACKSMITH,
    "market": LAYER_MARKET,
    "dock": LAYER_DOCK,
    "monastery": LAYER_MONASTERY,
    "university": LAYER_UNIVERSITY,
    "castle": LAYER_CASTLE,
    "wonder": LAYER_WONDER,
    "guard_tower": LAYER_GUARD_TOWER,
    "mill": LAYER_MILL,
    "granary": LAYER_GRANARY,
    "lumber_camp": LAYER_LUMBER_CAMP,
    "quarry": LAYER_QUARRY,
    "mining_camp": LAYER_MINING_CAMP,
}

# Resource layers for tracking gathering activity
RESOURCE_LAYERS = {
    "wood": LAYER_TREE,
    "food_wheat": LAYER_WHEAT,
    "food_fish": LAYER_FISH,
    "food_bush": LAYER_BUSH,
    "stone": LAYER_STONE,
    "gold": LAYER_GOLD,
}

# Tint codes that indicate combat events
TINT_COMBAT_MIN = 1
TINT_COMBAT_MAX = 59
TINT_DEATH = 60

EXPECTED_OBS_LAYERS = 101

NUM_TEAMS = 8
AGENTS_PER_TEAM = 125


@dataclass
class TeamMetrics:
    """Per-team metrics for a single step."""

    population: int = 0
    idle_count: int = 0
    building_counts: dict[str, int] = field(default_factory=dict)
    combat_events: int = 0
    deaths: int = 0


def extract_team_metrics_fast(
    observations: np.ndarray,
    num_agents: int,
    obs_layers: int,
) -> dict[int, TeamMetrics]:
    """Vectorized extraction of per-team metrics from observation buffer.

    Uses numpy operations across all agents simultaneously for speed.
    """
    teams: dict[int, TeamMetrics] = {t: TeamMetrics() for t in range(NUM_TEAMS)}
    center = 5

    # Extract center-tile data for all agents at once
    # observations shape: (num_agents, obs_layers, 11, 11)
    all_team_raw = observations[:num_agents, LAYER_TEAM, center, center].astype(np.int32) if LAYER_TEAM < obs_layers else np.zeros(num_agents, dtype=np.int32)
    all_idle = observations[:num_agents, LAYER_IDLE, center, center].astype(np.int32) if LAYER_IDLE < obs_layers else np.zeros(num_agents, dtype=np.int32)
    all_tint = observations[:num_agents, LAYER_TINT, center, center].astype(np.int32) if LAYER_TINT < obs_layers else np.zeros(num_agents, dtype=np.int32)

    for team_id in range(NUM_TEAMS):
        team_mask = all_team_raw == (team_id + 1)
        tm = teams[team_id]
        tm.population = int(np.sum(team_mask))

        if tm.population == 0:
            for bname in BUILDING_LAYERS:
                tm.building_counts[bname] = 0
            continue

        tm.idle_count = int(np.sum(all_idle[team_mask] > 0))

        team_tints = all_tint[team_mask]
        tm.combat_events = int(np.sum((team_tints >= TINT_COMBAT_MIN) & (team_tints <= TINT_COMBAT_MAX)))
        tm.deaths = int(np.sum(team_tints == TINT_DEATH))

        # Building visibility: for each building type, count how many team agents
        # see it anywhere in their 11x11 view
        for bname, blayer in BUILDING_LAYERS.items():
            if blayer >= obs_layers:
                tm.building_counts[bname] = 0
                continue
            # Get building layer for all agents on this team
            team_obs = observations[:num_agents][team_mask]  # (team_pop, obs_layers, 11, 11)
            building_visible = team_obs[:, blayer, :, :].reshape(tm.population, -1).any(axis=1)
            tm.building_counts[bname] = int(np.sum(building_visible))

    return teams


def count_visible_resources(
    observations: np.ndarray,
    num_agents: int,
    obs_layers: int,
) -> dict[str, int]:
    """Count total resource tiles visible across all agents."""
    totals: dict[str, int] = {}
    for rname, rlayer in RESOURCE_LAYERS.items():
        if rlayer >= obs_layers:
            totals[rname] = 0
            continue
        # Sum all nonzero resource tiles across all agent views
        totals[rname] = int(np.sum(observations[:num_agents, rlayer, :, :] > 0))
    return totals


def run_metrics(
    steps: int,
    output_dir: Path,
    sample_interval: int = 1,
) -> None:
    """Run the game and collect metrics."""
    from tribal_village_env import TribalVillageEnv
    from tribal_village_env.config import EnvironmentConfig

    config = EnvironmentConfig(max_steps=steps + 100, ai_mode="builtin")
    env = TribalVillageEnv(config=config)

    num_agents = env.total_agents
    obs_layers = env.obs_layers

    assert obs_layers == EXPECTED_OBS_LAYERS, (
        f"Layer count mismatch: expected {EXPECTED_OBS_LAYERS}, got {obs_layers}. "
        f"Update LAYER_* constants in {__file__}."
    )

    print(f"Environment: {num_agents} agents, {obs_layers} obs layers, "
          f"{env.obs_width}x{env.obs_height} grid")
    print(f"Running for {steps} steps (sampling every {sample_interval} steps)...")

    # Reset
    obs_dict, _ = env.reset()

    # Storage for per-step data
    step_records: list[dict] = []
    # Track resource counts over time to compute gathering rates
    prev_resources: dict[str, int] | None = None
    cumulative_rewards = np.zeros(NUM_TEAMS, dtype=np.float64)

    wall_start = time.monotonic()
    step_start = wall_start

    for step_i in range(1, steps + 1):
        # Use NOOP actions (action 0 = verb 0 * 28 + arg 0 = NOOP)
        # The scripted AI in Nim handles the actual behavior
        actions = {f"agent_{i}": np.int32(0) for i in range(num_agents)}
        obs_dict, rewards, terminated, truncated, infos = env.step(actions)

        # Accumulate rewards by team
        for agent_id in range(num_agents):
            agent_key = f"agent_{agent_id}"
            if agent_key in rewards:
                # Determine team from observation center
                team_raw = int(env.observations[agent_id, LAYER_TEAM, 5, 5]) if LAYER_TEAM < obs_layers else 0
                if 1 <= team_raw <= NUM_TEAMS:
                    cumulative_rewards[team_raw - 1] += rewards[agent_key]

        if step_i % sample_interval != 0:
            continue

        now = time.monotonic()
        elapsed = now - step_start
        sps = sample_interval / elapsed if elapsed > 0 else 0.0
        step_start = now

        # Extract metrics
        team_metrics = extract_team_metrics_fast(
            env.observations, num_agents, obs_layers
        )
        resources = count_visible_resources(env.observations, num_agents, obs_layers)

        # Compute resource gathering rates (change per sample interval)
        gathering_rates: dict[str, float] = {}
        if prev_resources is not None:
            for rname in RESOURCE_LAYERS:
                # Resources disappearing from view means they were gathered
                delta = prev_resources.get(rname, 0) - resources.get(rname, 0)
                gathering_rates[rname] = max(0, delta) / sample_interval
        prev_resources = resources.copy()

        # Build CSV row
        row: dict[str, object] = {
            "step": step_i,
            "sps": round(sps, 1),
        }
        for tid in range(NUM_TEAMS):
            tm = team_metrics[tid]
            prefix = f"t{tid}"
            row[f"{prefix}_pop"] = tm.population
            row[f"{prefix}_idle"] = tm.idle_count
            row[f"{prefix}_idle_pct"] = (
                round(100.0 * tm.idle_count / tm.population, 1)
                if tm.population > 0 else 0.0
            )
            row[f"{prefix}_combat"] = tm.combat_events
            row[f"{prefix}_deaths"] = tm.deaths
            row[f"{prefix}_reward"] = round(float(cumulative_rewards[tid]), 2)
            for bname in BUILDING_LAYERS:
                row[f"{prefix}_bld_{bname}"] = tm.building_counts.get(bname, 0)

        for rname, rcount in resources.items():
            row[f"res_{rname}"] = rcount
        for rname, rate in gathering_rates.items():
            row[f"gather_{rname}"] = round(rate, 3)

        step_records.append(row)

        # Progress output every 100 steps
        if step_i % 100 == 0 or step_i == steps:
            total_pop = sum(team_metrics[t].population for t in range(NUM_TEAMS))
            total_idle = sum(team_metrics[t].idle_count for t in range(NUM_TEAMS))
            total_combat = sum(team_metrics[t].combat_events for t in range(NUM_TEAMS))
            print(f"  Step {step_i:5d} | SPS {sps:7.1f} | Pop {total_pop:4d} | "
                  f"Idle {total_idle:4d} | Combat {total_combat:3d}")

    wall_elapsed = time.monotonic() - wall_start
    env.close()

    # --- Write outputs ---
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = output_dir / "metrics.csv"
    if step_records:
        # Use the union of all keys across records so gathering rate columns
        # (absent from the first row) are included in the header.
        all_keys: list[str] = []
        seen: set[str] = set()
        for rec in step_records:
            for k in rec:
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, restval=0)
            writer.writeheader()
            writer.writerows(step_records)
        print(f"\nCSV written: {csv_path} ({len(step_records)} rows)")

    # JSON summary
    summary = build_summary(step_records, steps, wall_elapsed, num_agents)
    json_path = output_dir / "summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"JSON written: {json_path}")

    # Print summary table
    print_summary_table(summary)


def build_summary(
    records: list[dict],
    total_steps: int,
    wall_elapsed: float,
    num_agents: int,
) -> dict:
    """Build JSON-serializable summary from collected records."""
    if not records:
        return {"error": "No data collected"}

    summary: dict = {
        "total_steps": total_steps,
        "wall_time_seconds": round(wall_elapsed, 2),
        "avg_sps": round(total_steps / wall_elapsed, 1) if wall_elapsed > 0 else 0,
        "num_agents": num_agents,
        "num_teams": NUM_TEAMS,
        "samples": len(records),
    }

    # Per-team aggregated stats
    team_stats = {}
    for tid in range(NUM_TEAMS):
        prefix = f"t{tid}"
        pops = [r[f"{prefix}_pop"] for r in records]
        idles = [r[f"{prefix}_idle_pct"] for r in records]
        combats = [r[f"{prefix}_combat"] for r in records]
        deaths = [r[f"{prefix}_deaths"] for r in records]

        # Building counts from last sample
        last = records[-1]
        buildings = {
            bname: last.get(f"{prefix}_bld_{bname}", 0)
            for bname in BUILDING_LAYERS
        }

        total_buildings = sum(buildings.values())

        team_stats[f"team_{tid}"] = {
            "population": {
                "final": pops[-1],
                "min": min(pops),
                "max": max(pops),
                "mean": round(sum(pops) / len(pops), 1),
            },
            "idle_pct": {
                "final": idles[-1],
                "mean": round(sum(idles) / len(idles), 1),
            },
            "combat_events_total": sum(combats),
            "deaths_total": sum(deaths),
            "final_reward": last.get(f"{prefix}_reward", 0),
            "buildings_final": buildings,
            "buildings_total": total_buildings,
        }
    summary["teams"] = team_stats

    # Resource stats
    resource_stats = {}
    for rname in RESOURCE_LAYERS:
        vals = [r.get(f"res_{rname}", 0) for r in records]
        gather_key = f"gather_{rname}"
        rates = [r.get(gather_key, 0) for r in records if gather_key in r]
        resource_stats[rname] = {
            "visible_final": vals[-1] if vals else 0,
            "visible_mean": round(sum(vals) / len(vals), 1) if vals else 0,
            "gathering_rate_mean": round(sum(rates) / len(rates), 3) if rates else 0,
        }
    summary["resources"] = resource_stats

    # Key diagnostic flags
    any_gathering = any(
        resource_stats[r]["gathering_rate_mean"] > 0 for r in RESOURCE_LAYERS
    )
    pops = [records[-1].get(f"t{t}_pop", 0) for t in range(NUM_TEAMS)]
    max_pop = max(pops) if pops else 0
    min_pop = min(pops) if pops else 0
    pop_divergence = (max_pop - min_pop) / max(max_pop, 1)

    any_buildings = any(
        team_stats[f"team_{t}"]["buildings_total"] > 0 for t in range(NUM_TEAMS)
    )
    any_combat = any(
        team_stats[f"team_{t}"]["combat_events_total"] > 0 for t in range(NUM_TEAMS)
    )
    avg_idle = sum(
        team_stats[f"team_{t}"]["idle_pct"]["mean"] for t in range(NUM_TEAMS)
    ) / NUM_TEAMS

    summary["diagnostics"] = {
        "villagers_gathering": any_gathering,
        "buildings_being_built": any_buildings,
        "combat_occurring": any_combat,
        "avg_idle_pct": round(avg_idle, 1),
        "population_divergence": round(pop_divergence, 2),
        "economy_functional": any_gathering or any_buildings,
    }

    return summary


def print_summary_table(summary: dict) -> None:
    """Print a formatted summary table to stdout."""
    print("\n" + "=" * 72)
    print("GAMEPLAY METRICS SUMMARY")
    print("=" * 72)
    print(f"Steps: {summary['total_steps']}  |  "
          f"Wall time: {summary['wall_time_seconds']}s  |  "
          f"Avg SPS: {summary['avg_sps']}")
    print("-" * 72)

    # Per-team table
    header = f"{'Team':>6} {'Pop':>5} {'Idle%':>6} {'Combat':>7} {'Deaths':>7} {'Bldgs':>6} {'Reward':>8}"
    print(header)
    print("-" * 72)

    teams = summary.get("teams", {})
    for tid in range(NUM_TEAMS):
        ts = teams.get(f"team_{tid}", {})
        pop = ts.get("population", {}).get("final", 0)
        idle = ts.get("idle_pct", {}).get("mean", 0)
        combat = ts.get("combat_events_total", 0)
        deaths = ts.get("deaths_total", 0)
        bldgs = ts.get("buildings_total", 0)
        reward = ts.get("final_reward", 0)
        print(f"  T{tid:>3d} {pop:>5d} {idle:>5.1f}% {combat:>7d} {deaths:>7d} {bldgs:>6d} {reward:>8.1f}")

    print("-" * 72)

    # Resources
    print("\nResources (visible tiles / gathering rate per step):")
    resources = summary.get("resources", {})
    for rname, rs in resources.items():
        vis = rs.get("visible_final", 0)
        rate = rs.get("gathering_rate_mean", 0)
        print(f"  {rname:<15s}: {vis:>6d} visible  |  rate: {rate:.3f}/step")

    # Diagnostics
    print("\n" + "-" * 72)
    diag = summary.get("diagnostics", {})
    checks = [
        ("Villagers gathering?", diag.get("villagers_gathering", False)),
        ("Buildings being built?", diag.get("buildings_being_built", False)),
        ("Combat occurring?", diag.get("combat_occurring", False)),
        ("Economy functional?", diag.get("economy_functional", False)),
    ]
    for label, val in checks:
        status = "YES" if val else "NO"
        print(f"  {label:<30s} {status}")
    print(f"  {'Avg idle %:':<30s} {diag.get('avg_idle_pct', 0):.1f}%")
    print(f"  {'Population divergence:':<30s} {diag.get('population_divergence', 0):.2f}")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect gameplay metrics from Tribal Village simulation"
    )
    parser.add_argument(
        "--steps", type=int, default=1000,
        help="Number of simulation steps to run (default: 1000)"
    )
    parser.add_argument(
        "--output", type=str, default="/tmp/tv_metrics/",
        help="Output directory for CSV and JSON files (default: /tmp/tv_metrics/)"
    )
    parser.add_argument(
        "--sample-interval", type=int, default=1,
        help="Collect metrics every N steps (default: 1, every step)"
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    run_metrics(
        steps=args.steps,
        output_dir=output_dir,
        sample_interval=args.sample_interval,
    )


if __name__ == "__main__":
    main()
