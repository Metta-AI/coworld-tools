"""Integration tests for bombercog.

These tests build the real game via the conftest ``build_sim`` helper and
exercise the bomb placement, fuse countdown, blast damage, and cleanup
mechanics against a stepped ``Simulation``.
"""

from __future__ import annotations

from conftest import build_sim

from bombercog.game import (
    BLAST_RANGE,
    BOMB_MAX,
    BOMB_REGEN_COST,
    BOMB_RANGE_MAX,
    FUSE_TICKS,
    HP_MAX,
    BombercogMission,
)
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.simulator import Simulation

# ===== Helpers =====


def _build_sim(max_steps: int = 500) -> Simulation:
    return build_sim(num_agents=2, max_steps=max_steps)


def _count_type(sim: Simulation, type_name: str) -> int:
    return sum(1 for o in sim.grid_objects().values() if o.get("type_name") == type_name)


def _objects_of(sim: Simulation, type_name: str) -> list[dict]:
    return [o for o in sim.grid_objects().values() if o.get("type_name") == type_name]


def _agent_pos(sim: Simulation, agent_idx: int) -> tuple[int, int]:
    agents = _objects_of(sim, "agent")
    assert len(agents) > agent_idx, f"agent {agent_idx} not found"
    # Sort by agent_id so indices are deterministic.
    agents_sorted = sorted(agents, key=lambda o: o.get("agent_id", 0))
    a = agents_sorted[agent_idx]
    return (a["r"], a["c"])


def _step_both_noop(sim: Simulation, ticks: int) -> None:
    for _ in range(ticks):
        sim.agent(0).set_action("noop")
        sim.agent(1).set_action("noop")
        sim.step()


# ===== Tests =====


def test_bombercog_registers_and_builds() -> None:
    """Sanity: the game config builds a working simulation with the expected
    initial state (walls, crates, two agents, no bombs)."""
    sim = _build_sim()
    try:
        assert _count_type(sim, "wall") > 0
        assert _count_type(sim, "crate") > 0
        assert _count_type(sim, "agent") == 2
        assert _count_type(sim, "bomb") == 0
        assert _count_type(sim, "explosion") == 0
        assert sim.agent(0).inventory.get("hp") == HP_MAX
        assert sim.agent(0).inventory.get("bomb_count") == BOMB_MAX
        assert sim.agent(0).inventory.get("bomb_range") == BLAST_RANGE
    finally:
        sim.close()


def test_bomb_placement_via_vibe_and_move() -> None:
    """Agent in bomb vibe moves east into an empty cell and drops a bomb
    there. The agent does NOT move; bomb_count decrements by 1."""
    sim = _build_sim()
    try:
        start_pos = _agent_pos(sim, 0)
        assert sim.agent(0).inventory.get("bomb_count") == BOMB_MAX

        # Switch agent 0 to bomb vibe.
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()

        # Agent 0's east cell is '.' (empty) in the redesigned map. Move east.
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()

        # Agent did not move.
        assert _agent_pos(sim, 0) == start_pos, "agent moved — place_bomb handler should block move"

        # One bomb exists.
        bombs = _objects_of(sim, "bomb")
        assert len(bombs) == 1, f"expected 1 bomb, got {len(bombs)}"

        # bomb_count decremented by 1.
        assert sim.agent(0).inventory.get("bomb_count", 0) == BOMB_MAX - 1, (
            f"bomb_count should be {BOMB_MAX - 1} after placement"
        )
    finally:
        sim.close()


def test_bomb_placement_requires_bomb_vibe() -> None:
    """With default vibe, moving east just walks into the empty cell —
    no bomb is placed."""
    sim = _build_sim()
    try:
        start_pos = _agent_pos(sim, 0)
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()
        assert _count_type(sim, "bomb") == 0
        # Agent should have moved east.
        new_pos = _agent_pos(sim, 0)
        assert new_pos != start_pos, "agent in default vibe should have walked east"
    finally:
        sim.close()


def test_bomb_placement_auto_resets_vibe() -> None:
    """After placing a bomb, the agent's vibe snaps back to default so the
    next move is a walk, not a second placement.

    To distinguish vibe-reset from bomb-count-exhausted: give the agent 2
    bombs up front. If the vibe weren't reset, the second move would drop
    another bomb (bomb_count allows it). If the vibe WAS reset, the agent
    walks and bomb_count stays at 1.
    """
    sim = _build_sim()
    try:
        # Give agent enough bombs that two consecutive placements would
        # both succeed if the vibe stays.
        sim.agent(0).set_inventory(
            {"bomb_count": 2, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
        )
        start_pos = _agent_pos(sim, 0)

        # Switch to bomb vibe.
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()

        # Place the first bomb by moving east.
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()
        assert _count_type(sim, "bomb") == 1, "first bomb should have been placed"
        assert _agent_pos(sim, 0) == start_pos, "agent should not have moved"
        assert sim.agent(0).inventory.get("bomb_count") == 1, (
            "bomb_count should have dropped from 2 to 1"
        )

        # Next step: move south. If vibe were still "bomb", a second bomb
        # would drop at the south cell (bomb_count would go 1→0). With
        # the auto-reset, the agent walks south instead.
        sim.agent(0).set_action("move_south")
        sim.agent(1).set_action("noop")
        sim.step()

        assert _count_type(sim, "bomb") == 1, (
            "no second bomb should drop — vibe should have been reset to default"
        )
        assert sim.agent(0).inventory.get("bomb_count") == 1, (
            "bomb_count should stay at 1 — no second placement"
        )
        new_pos = _agent_pos(sim, 0)
        assert new_pos == (start_pos[0] + 1, start_pos[1]), (
            f"agent should have walked south; started at {start_pos}, now at {new_pos}"
        )
    finally:
        sim.close()


def _place_bomb_east(sim: Simulation) -> None:
    """Drop a bomb on agent 0's east cell.

    Step 1: change to bomb vibe.
    Step 2: move_east (spawns the bomb at that cell, agent stays in place).

    With actions-before-events tick ordering, events (including fuse_tick)
    fire on the same step the bomb is placed, so the fuse is already
    decremented by 1 after this helper returns.
    """
    sim.agent(0).set_action("change_vibe_bomb")
    sim.agent(1).set_action("noop")
    sim.step()
    sim.agent(0).set_action("move_east")
    sim.agent(1).set_action("noop")
    sim.step()


# After _place_bomb_east, the fuse has already been decremented once
# (actions run before events, so fuse_tick fires on the placement tick).
# We need FUSE_TICKS - 1 more noop steps to reach detonation.
NOOP_STEPS_TO_DETONATE = FUSE_TICKS - 1


def test_bomb_fuse_countdown_and_explosion() -> None:
    """After placing a bomb, step through the remaining fuse ticks. The bomb
    is removed and explosion markers are spawned."""
    sim = _build_sim()
    try:
        _place_bomb_east(sim)
        assert _count_type(sim, "bomb") == 1, "bomb should be placed"
        assert _count_type(sim, "explosion") == 0

        _step_both_noop(sim, NOOP_STEPS_TO_DETONATE)

        assert _count_type(sim, "bomb") == 0, "bomb should be removed after explosion"
        assert _count_type(sim, "explosion") >= 1, "explosion markers should be visible"
    finally:
        sim.close()


def test_bomb_destroys_adjacent_crate() -> None:
    """A bomb placed at agent 0's east cell has the crate at (3, 2) in its
    south blast range (distance 2). Stepping through the fuse should remove
    that crate from the grid."""
    sim = _build_sim()
    try:
        initial_crates = _count_type(sim, "crate")
        assert initial_crates > 0

        _place_bomb_east(sim)
        _step_both_noop(sim, NOOP_STEPS_TO_DETONATE)

        after_crates = _count_type(sim, "crate")
        assert after_crates < initial_crates, (
            f"blast should destroy at least 1 crate (before={initial_crates}, after={after_crates})"
        )
    finally:
        sim.close()


def test_bomb_damages_agent_in_blast_radius() -> None:
    """Agent 0 drops a bomb immediately east of itself, then stands still
    through the fuse. The west arm of the blast reaches agent 0's cell
    (non-blocker objects don't stop the ray), so agent 0 should lose 1 HP
    when the bomb goes off."""
    sim = _build_sim()
    try:
        assert sim.agent(0).inventory.get("hp") == HP_MAX

        _place_bomb_east(sim)
        _step_both_noop(sim, NOOP_STEPS_TO_DETONATE)

        hp_after = sim.agent(0).inventory.get("hp", 0)
        assert hp_after == HP_MAX - 1, (
            f"agent 0 should lose exactly 1 hp from its own blast (expected {HP_MAX - 1}, got {hp_after})"
        )
    finally:
        sim.close()


def test_explosion_markers_cleanup() -> None:
    """Explosion markers spawn with life=2 and are removed by
    ``bomb_3_cleanup_explosion``. After a few noop ticks, no explosion
    markers should remain on the grid."""
    sim = _build_sim()
    try:
        _place_bomb_east(sim)
        _step_both_noop(sim, NOOP_STEPS_TO_DETONATE)
        assert _count_type(sim, "explosion") >= 1, "expected explosion markers to spawn"

        # Step enough additional ticks for cleanup to finish (life starts at 2,
        # cleanup decrements by 1 each tick, so <=2 more ticks suffice).
        _step_both_noop(sim, 3)
        assert _count_type(sim, "explosion") == 0, "all explosion markers should be cleaned up after life expires"
    finally:
        sim.close()


def test_bomb_regen_replenishes_budget() -> None:
    """After placing one bomb, agent 0's ``bomb_count`` drops by 1.
    The ``bomb_regen`` resource accumulates +1 per tick (only while below
    max bombs), and converts to a new bomb when it reaches BOMB_REGEN_COST.

    Note: a resource at 0 is erased from the inventory dict by the engine
    (see ``inventory.cpp``), so we always use ``inventory.get(name, 0)``.
    """
    sim = _build_sim(max_steps=500)
    try:
        _place_bomb_east(sim)
        assert sim.agent(0).inventory.get("bomb_count", 0) == BOMB_MAX - 1, (
            f"bomb_count should be {BOMB_MAX - 1} after placement"
        )

        # Step enough ticks for regen to accumulate to BOMB_REGEN_COST.
        # The placement step already ticked regen once, so we need a few
        # more. Use BOMB_REGEN_COST + a small buffer.
        _step_both_noop(sim, BOMB_REGEN_COST + 2)
        assert sim.agent(0).inventory.get("bomb_count", 0) == BOMB_MAX, (
            "bomb_count should have regenerated back to BOMB_MAX"
        )

        # Run long enough to hit the cap and confirm it clamps.
        _step_both_noop(sim, BOMB_REGEN_COST * (BOMB_MAX + 2))
        assert sim.agent(0).inventory.get("bomb_count", 0) == BOMB_MAX, f"bomb_count should cap at {BOMB_MAX}"

        # At max bombs, bomb_regen should NOT accumulate.
        regen_at_max = sim.agent(0).inventory.get("bomb_regen", 0)
        _step_both_noop(sim, 5)
        regen_after = sim.agent(0).inventory.get("bomb_regen", 0)
        assert regen_after == regen_at_max, (
            f"bomb_regen should not accumulate at max bombs (was {regen_at_max}, now {regen_after})"
        )
    finally:
        sim.close()


def test_survival_reward_scales_with_hp() -> None:
    """The per-tick survival reward is 0.1 * hp. At full HP (3) across N
    noop ticks, the accumulated reward should be 0.3 * N (with some small
    floating-point slack)."""
    sim = _build_sim()
    try:
        ticks = 20
        total = 0.0
        for _ in range(ticks):
            sim.agent(0).set_action("noop")
            sim.agent(1).set_action("noop")
            sim.step()
            total += sim.agent(0).step_reward

        expected = 0.1 * HP_MAX * ticks
        assert abs(total - expected) < 1e-3, (
            f"survival reward at full HP should be {expected} over {ticks} ticks, got {total}"
        )
    finally:
        sim.close()


def test_bomb_blast_stopped_by_walls_and_crates() -> None:
    """Walls and crates block blast rays (OR-semantic blocker filter).

    For a bomb at (1, 2) with BLAST_RANGE=2 on the default map:

        ###########   row 0 (wall)
        #@X.......#   row 1: agent at (1,1), bomb at X=(1,2)
        #...C.C...#   row 2: crate at (2,4) is off-axis
        #.C..C..C.#   row 3: crate at (3,2) is south distance 2

    Expected explosion marker positions:
      - North: (0, 2) is wall → no spawn
      - South: (2, 2) empty spawn; (3, 2) is a crate blocker → no spawn (ray stops)
      - East:  (1, 3), (1, 4) both empty → 2 spawns
      - West:  (1, 1) agent non-blocker (skipped); (1, 0) wall blocker → no spawn

    Total 3 markers at exactly {(2, 2), (1, 3), (1, 4)}.
    """
    sim = _build_sim()
    try:
        _place_bomb_east(sim)
        _step_both_noop(sim, NOOP_STEPS_TO_DETONATE)

        explosion_positions = {(o["r"], o["c"]) for o in _objects_of(sim, "explosion")}
        assert explosion_positions == {(2, 2), (1, 3), (1, 4)}, (
            f"unexpected explosion positions: {sorted(explosion_positions)}"
        )
        # Crate directly destroyed: (3, 2). Off-axis crates at (2, 4), (2, 6),
        # (3, 5), (3, 8), (4, 3), (4, 7), (5, 2), (5, 5), (5, 8), (6, 4),
        # (6, 6) must all survive.
        crate_positions = {(o["r"], o["c"]) for o in _objects_of(sim, "crate")}
        assert (3, 2) not in crate_positions, "crate at (3, 2) should be destroyed by south blast"
        for off_axis in [(2, 4), (2, 6), (4, 3), (4, 7)]:
            assert off_axis in crate_positions, f"off-axis crate at {off_axis} should survive"
    finally:
        sim.close()


# ===== Agent body-blocks the blast =====


def _build_bodyblock_sim(map_rows: list[str]) -> Simulation:
    """Build a bombercog sim from a custom ASCII map.

    Expects exactly two `@` spawns and any mix of walls (`#`), empty cells
    (`.`), and crates (`C`). Used for isolated blast-propagation tests.
    """
    mission = BombercogMission(
        name="bombercog",
        description="bodyblock test",
        map_builder=AsciiMapBuilder.Config(
            map_data=[list(row) for row in map_rows],
            char_to_map_name={
                "#": "wall",
                ".": "empty",
                "@": "agent.agent",
                "C": "crate",
            },
        ),
        num_cogs=2,
        min_cogs=2,
        max_cogs=4,
        max_steps=100,
    )
    env = mission.make_env()
    return Simulation(env, seed=42)


def test_agent_bodyblocks_blast_protecting_crate_behind() -> None:
    """Agent 1 standing between the bomb and a crate absorbs the hit and
    shields the crate. The same bomb without agent 1 in the path would
    destroy the crate.

    Layout (single row of play, bomb_range=5 via set_inventory):
        # # # # # # # # #
        # @ . @ . . . C #     agent0 at (1,1), agent1 at (1,3), crate at (1,7)
        # # # # # # # # #

    Agent 0 places a bomb at (1,2). East arm distances from (1,2):
        (1,3)=agent1 dist 1, (1,4) dist 2, (1,5) dist 3, (1,6) dist 4,
        (1,7)=crate dist 5. With bomb_range=5 the ray covers the whole
        row; with agent 1 as a blocker the ray stops at (1,3) and the
        crate at (1,7) survives.
    """
    sim = _build_bodyblock_sim(
        [
            "#########",
            "#@.@...C#",
            "#########",
        ]
    )
    try:
        # Pre-condition: one crate on the map.
        assert _count_type(sim, "crate") == 1

        # Max-out bomb_range so WITHOUT the bodyblock the blast reaches
        # the crate at col 7 (distance 5 from bomb at col 2).
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BOMB_RANGE_MAX, "hp": HP_MAX}
        )
        # Keep agent 1 alive during the test.
        sim.agent(1).set_inventory(
            {"bomb_count": 0, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": HP_MAX}
        )

        # Place bomb east: bomb lands at (1,2), agent 0 stays at (1,1).
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()

        bombs = _objects_of(sim, "bomb")
        assert len(bombs) == 1 and (bombs[0]["r"], bombs[0]["c"]) == (1, 2)

        # Let the fuse burn down.
        _step_both_noop(sim, FUSE_TICKS + 2)

        # Crate at (1,7) must survive — agent 1 at (1,3) body-blocked the east arm.
        crate_positions = {(o["r"], o["c"]) for o in _objects_of(sim, "crate")}
        assert (1, 7) in crate_positions, (
            "crate at (1,7) should survive because agent 1 at (1,3) blocked the east arm"
        )
        # Agent 1 took the hit.
        assert sim.agent(1).inventory.get("hp", 0) == HP_MAX - 1, (
            "agent 1 should take 1 hp damage from the body-blocked blast"
        )
    finally:
        sim.close()


def test_agent_absent_blast_extends_to_crate() -> None:
    """Control case for the bodyblock test: with no agent standing in the
    east arm, the same bomb_range=4 blast from (1,2) destroys the crate
    at (1,7). Confirms the crate is reachable in principle."""
    sim = _build_bodyblock_sim(
        [
            "#########",
            "#@.....C#",
            "#...@...#",  # put agent 1 out of the east arm
            "#########",
        ]
    )
    try:
        assert _count_type(sim, "crate") == 1

        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 5, "hp": HP_MAX}
        )

        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()

        bombs = _objects_of(sim, "bomb")
        assert len(bombs) == 1 and (bombs[0]["r"], bombs[0]["c"]) == (1, 2)

        _step_both_noop(sim, FUSE_TICKS + 2)

        # With no bodyblock, the crate at (1,7) is destroyed.
        assert _count_type(sim, "crate") == 0, (
            "crate at (1,7) should be destroyed when nothing blocks the east arm"
        )
    finally:
        sim.close()
