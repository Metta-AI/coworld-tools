"""
Integration test: verify AoE-style gameplay feel end-to-end.

Runs the environment for 2000 steps with random actions and validates
that core game systems are functioning: population, buildings, resources,
combat, and rendering.

This test exercises the ExternalNN path (Python → Nim FFI) which is the
production path for RL training. The scripted AI (BuiltinAI) is NOT active
in this mode; agents follow the actions provided by Python.

Run with: pytest tests/test_aoe_gameplay_feel.py -v
"""

from __future__ import annotations

import ctypes

import numpy as np
import pytest

from tribal_village_env.environment import TribalVillageEnv, ACTION_SPACE_SIZE
from tribal_village_env.config import EnvironmentConfig

# Observation layer indices matching the compiled libtribal_village.so.
# The .so was built before TerrainMountainLayer and ThingWaterfall*Layer
# were added to ObservationName in src/types.nim, so all thing layers are
# shifted -1 (missing mountain terrain) and meta layers are shifted -5
# (missing mountain + 4 waterfall things).  Update these when the .so is
# recompiled from current source.
LAYER_AGENT = 17
LAYER_TREE = 20
LAYER_WHEAT = 21
LAYER_STONE = 24
LAYER_GOLD = 25
LAYER_TOWN_CENTER = 50
LAYER_HOUSE = 51
LAYER_BARRACKS = 52
LAYER_GUARD_TOWER = 41
LAYER_MILL = 43
LAYER_GRANARY = 44
LAYER_LUMBER_CAMP = 45
LAYER_QUARRY = 46
LAYER_MINING_CAMP = 47
LAYER_TEAM = 81
LAYER_IDLE = 84
LAYER_TINT = 85

NUM_TEAMS = 8
CENTER = 5  # Center of 11x11 observation window


def _collect_snapshot(env: TribalVillageEnv) -> dict:
    """Extract a metrics snapshot from the current observation buffer."""
    num_agents = env.total_agents
    obs = env.observations

    snapshot: dict = {
        "team_pop": {},
        "team_idle": {},
        "team_combat": {},
        "resources": {},
        "buildings": {},
    }

    for tid in range(NUM_TEAMS):
        mask = obs[:num_agents, LAYER_TEAM, CENTER, CENTER].astype(np.int32) == (tid + 1)
        pop = int(np.sum(mask))
        snapshot["team_pop"][tid] = pop
        if pop > 0:
            snapshot["team_idle"][tid] = int(
                np.sum(obs[:num_agents, LAYER_IDLE, CENTER, CENTER][mask] > 0)
            )
            tints = obs[:num_agents, LAYER_TINT, CENTER, CENTER][mask]
            snapshot["team_combat"][tid] = int(np.sum((tints >= 1) & (tints <= 59)))
        else:
            snapshot["team_idle"][tid] = 0
            snapshot["team_combat"][tid] = 0

    for name, layer in [
        ("wood", LAYER_TREE),
        ("wheat", LAYER_WHEAT),
        ("stone", LAYER_STONE),
        ("gold", LAYER_GOLD),
    ]:
        snapshot["resources"][name] = int(
            np.sum(obs[:num_agents, layer, :, :] > 0)
        )

    for name, layer in [
        ("town_center", LAYER_TOWN_CENTER),
        ("house", LAYER_HOUSE),
        ("barracks", LAYER_BARRACKS),
        ("granary", LAYER_GRANARY),
        ("lumber_camp", LAYER_LUMBER_CAMP),
        ("quarry", LAYER_QUARRY),
        ("mining_camp", LAYER_MINING_CAMP),
    ]:
        snapshot["buildings"][name] = int(
            np.sum(obs[:num_agents, layer, :, :] > 0)
        )

    snapshot["total_pop"] = sum(snapshot["team_pop"].values())
    snapshot["total_combat"] = sum(snapshot["team_combat"].values())
    snapshot["total_buildings"] = sum(snapshot["buildings"].values())
    return snapshot


@pytest.fixture(scope="module")
def gameplay_run():
    """Run the game for 2000 steps with random actions, return snapshots."""
    config = EnvironmentConfig(max_steps=2100)
    env = TribalVillageEnv(config=config)
    num_agents = env.total_agents

    env.reset()
    rng = np.random.RandomState(42)

    snapshots = {}
    capture_steps = [0, 100, 300, 500, 1000, 2000]
    snapshots[0] = _collect_snapshot(env)

    for step in range(1, 2001):
        actions = {
            f"agent_{i}": int(rng.randint(0, ACTION_SPACE_SIZE))
            for i in range(num_agents)
        }
        env.step(actions)
        if step in capture_steps:
            snapshots[step] = _collect_snapshot(env)

    yield {
        "snapshots": snapshots,
        "env": env,
        "num_agents": num_agents,
    }
    env.close()


class TestEnvironmentBootstrap:
    """Verify the environment initializes correctly."""

    def test_agent_count(self, gameplay_run):
        assert gameplay_run["num_agents"] == 1006

    def test_initial_population_nonzero(self, gameplay_run):
        snap = gameplay_run["snapshots"][0]
        assert snap["total_pop"] > 0, "Initial population must be > 0"

    def test_initial_buildings_exist(self, gameplay_run):
        snap = gameplay_run["snapshots"][0]
        assert snap["buildings"]["town_center"] > 0, "Must start with town centers"
        assert snap["buildings"]["house"] > 0, "Must start with houses"


class TestPopulationDynamics:
    """Population should be nonzero and change over the run."""

    def test_population_persists(self, gameplay_run):
        """Population stays nonzero throughout the run."""
        for step, snap in gameplay_run["snapshots"].items():
            assert snap["total_pop"] > 0, f"Population dropped to 0 at step {step}"

    def test_population_grows(self, gameplay_run):
        """Population at step 2000 should exceed initial population."""
        pop_0 = gameplay_run["snapshots"][0]["total_pop"]
        pop_2000 = gameplay_run["snapshots"][2000]["total_pop"]
        assert pop_2000 > pop_0, (
            f"Population didn't grow: step 0={pop_0}, step 2000={pop_2000}"
        )

    def test_multiple_teams_have_agents(self, gameplay_run):
        """At least 4 teams should have surviving agents at step 1000."""
        snap = gameplay_run["snapshots"][1000]
        teams_with_pop = sum(1 for p in snap["team_pop"].values() if p > 0)
        assert teams_with_pop >= 4, (
            f"Only {teams_with_pop} teams alive at step 1000"
        )


class TestBuildingProgression:
    """Buildings should exist and accumulate."""

    def test_town_centers_always_present(self, gameplay_run):
        for step, snap in gameplay_run["snapshots"].items():
            assert snap["buildings"]["town_center"] > 0, (
                f"No town centers visible at step {step}"
            )

    def test_buildings_increase(self, gameplay_run):
        bld_0 = gameplay_run["snapshots"][0]["total_buildings"]
        bld_2000 = gameplay_run["snapshots"][2000]["total_buildings"]
        assert bld_2000 > bld_0, (
            f"Buildings didn't increase: step 0={bld_0}, step 2000={bld_2000}"
        )

    def test_drop_off_buildings_exist(self, gameplay_run):
        """Drop-off buildings (granary, lumber camp, etc) should be visible."""
        snap = gameplay_run["snapshots"][1000]
        drop_offs = (
            snap["buildings"].get("granary", 0)
            + snap["buildings"].get("lumber_camp", 0)
            + snap["buildings"].get("quarry", 0)
            + snap["buildings"].get("mining_camp", 0)
        )
        assert drop_offs > 0, "No drop-off buildings visible at step 1000"


class TestResourceVisibility:
    """Resources should be visible on the map."""

    def test_wood_visible(self, gameplay_run):
        snap = gameplay_run["snapshots"][0]
        assert snap["resources"]["wood"] > 0, "No wood visible at start"

    def test_wheat_visible(self, gameplay_run):
        snap = gameplay_run["snapshots"][0]
        assert snap["resources"]["wheat"] > 0, "No wheat visible at start"

    def test_resources_visible_at_step_500(self, gameplay_run):
        snap = gameplay_run["snapshots"][500]
        total_res = sum(snap["resources"].values())
        assert total_res > 0, "No resources visible at step 500"


class TestCombatSystem:
    """With random actions, combat should eventually occur."""

    def test_combat_events_occur(self, gameplay_run):
        """At least some combat should happen by step 1000 with random actions."""
        total_combat = sum(
            gameplay_run["snapshots"][step]["total_combat"]
            for step in [500, 1000, 2000]
        )
        assert total_combat > 0, "No combat events in entire 2000-step run"


class TestRGBRendering:
    """Verify RGB rendering produces valid output."""

    def test_rgb_render_succeeds(self, gameplay_run):
        env = gameplay_run["env"]
        lib = env.lib
        map_w = lib.tribal_village_get_map_width()
        map_h = lib.tribal_village_get_map_height()
        render_w = map_w * 2
        render_h = map_h * 2

        rgb = np.zeros((render_h, render_w, 3), dtype=np.uint8)
        rgb_ptr = rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        success = lib.tribal_village_render_rgb(
            env.env_ptr,
            rgb_ptr,
            ctypes.c_int32(render_w),
            ctypes.c_int32(render_h),
        )
        assert success == 1, "RGB render failed"

    def test_rgb_not_blank(self, gameplay_run):
        env = gameplay_run["env"]
        lib = env.lib
        map_w = lib.tribal_village_get_map_width()
        map_h = lib.tribal_village_get_map_height()
        render_w = map_w * 2
        render_h = map_h * 2

        rgb = np.zeros((render_h, render_w, 3), dtype=np.uint8)
        rgb_ptr = rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        lib.tribal_village_render_rgb(
            env.env_ptr,
            rgb_ptr,
            ctypes.c_int32(render_w),
            ctypes.c_int32(render_h),
        )
        assert rgb.mean() > 10, "RGB render is mostly black"
        assert rgb.std() > 5, "RGB render has no variation (single color)"

    def test_rgb_has_agent_pixels(self, gameplay_run):
        env = gameplay_run["env"]
        lib = env.lib
        map_w = lib.tribal_village_get_map_width()
        map_h = lib.tribal_village_get_map_height()
        render_w = map_w * 2
        render_h = map_h * 2

        rgb = np.zeros((render_h, render_w, 3), dtype=np.uint8)
        rgb_ptr = rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        lib.tribal_village_render_rgb(
            env.env_ptr,
            rgb_ptr,
            ctypes.c_int32(render_w),
            ctypes.c_int32(render_h),
        )
        flat = rgb.reshape(-1, 3)
        # Agents render as yellow (255, 255, 0)
        agent_pixels = (
            (flat[:, 0] > 200) & (flat[:, 1] > 200) & (flat[:, 2] < 50)
        ).sum()
        assert agent_pixels > 0, "No agent pixels found in RGB render"


class TestPerformance:
    """Basic performance sanity check."""

    def test_sps_above_minimum(self, gameplay_run):
        """Steps per second should be reasonable (>50 SPS)."""
        import time

        config = EnvironmentConfig(max_steps=200)
        perf_env = TribalVillageEnv(config=config)
        perf_env.reset()

        rng = np.random.RandomState(123)
        t0 = time.monotonic()
        for _ in range(100):
            actions = {
                f"agent_{i}": int(rng.randint(0, ACTION_SPACE_SIZE))
                for i in range(perf_env.total_agents)
            }
            perf_env.step(actions)
        elapsed = time.monotonic() - t0
        sps = 100 / elapsed
        perf_env.close()
        assert sps > 50, f"SPS too low: {sps:.1f} (expected >50)"
