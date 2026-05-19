"""Tests for the bombercog powerups variant (loot crates)."""

from __future__ import annotations

from conftest import build_sim

from bombercog.game import BLAST_RANGE, BOMB_MAX, FUSE_TICKS
from mettagrid.simulator import Simulation


def _build_sim(max_steps: int = 500) -> Simulation:
    return build_sim(num_agents=2, max_steps=max_steps, variants=["powerups"])


def _count_type(sim: Simulation, type_name: str) -> int:
    return sum(1 for o in sim.grid_objects().values() if o.get("type_name") == type_name)


def _objects_of(sim: Simulation, type_name: str) -> list[dict]:
    return [o for o in sim.grid_objects().values() if o.get("type_name") == type_name]


def _agent_pos(sim: Simulation, agent_idx: int) -> tuple[int, int]:
    agents = _objects_of(sim, "agent")
    agents_sorted = sorted(agents, key=lambda o: o.get("agent_id", 0))
    a = agents_sorted[agent_idx]
    return (a["r"], a["c"])


def _step(sim: Simulation, a0: str, a1: str) -> None:
    sim.agent(0).set_action(a0)
    sim.agent(1).set_action(a1)
    sim.step()


def _step_both_noop(sim: Simulation, ticks: int) -> None:
    for _ in range(ticks):
        _step(sim, "noop", "noop")


# ===== Map-layout sanity =====


def test_powerups_map_has_loot_crates() -> None:
    """The powerups map starts with some crates carrying loot markers.

    All crates share type_name="crate"; distinguishing them requires peeking
    at their inventory (has_range_loot / has_count_loot).
    """
    sim = _build_sim()
    try:
        resource_names = sim.resource_names
        range_id = resource_names.index("has_range_loot")
        count_id = resource_names.index("has_count_loot")

        range_crates = [
            c for c in _objects_of(sim, "crate")
            if c["inventory"].get(range_id, 0) == 1
        ]
        count_crates = [
            c for c in _objects_of(sim, "crate")
            if c["inventory"].get(count_id, 0) == 1
        ]
        plain_crates = [
            c for c in _objects_of(sim, "crate")
            if c["inventory"].get(range_id, 0) == 0
            and c["inventory"].get(count_id, 0) == 0
        ]
        assert len(range_crates) > 0, "map should contain range crates"
        assert len(count_crates) > 0, "map should contain count crates"
        assert len(plain_crates) > 0, "map should still contain plain crates"
    finally:
        sim.close()


# ===== Loot drop mechanics =====


def _blast_adjacent_range_crate(sim: Simulation) -> None:
    """Set up agent 0 to blast the range crate at (2,2) with a bomb at (1,2).

    Agent 0 spawns at (1,1). Drop a bomb east, step out of its west arm,
    then wait for the fuse.
    """
    # Ensure bomb_count / bomb_slots are at their usual defaults.
    sim.agent(0).set_inventory(
        {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
    )
    _step(sim, "change_vibe_bomb", "noop")
    _step(sim, "move_east", "noop")          # places bomb at (1,2); agent stays at (1,1)
    _step(sim, "change_vibe_default", "noop")
    _step(sim, "move_south", "noop")         # agent to (2,1), out of west arm
    # Fuse has already ticked FUSE_TICKS - (steps since place) times; step until detonation.
    _step_both_noop(sim, FUSE_TICKS)         # generous — crate will definitely be destroyed by end


def test_destroyed_range_crate_drops_range_up() -> None:
    """Blasting a range crate leaves a range_up pickup in its cell."""
    sim = _build_sim()
    try:
        assert _count_type(sim, "range_up") == 0, "no pickups present before destruction"
        # Range crate at (2,2) from POWERUPS_MAP row 2.
        _blast_adjacent_range_crate(sim)

        range_ups = _objects_of(sim, "range_up")
        assert len(range_ups) == 1, f"expected exactly 1 range_up, got {len(range_ups)}"
        assert (range_ups[0]["r"], range_ups[0]["c"]) == (2, 2), (
            f"range_up should spawn at destroyed crate's cell (2,2); got "
            f"({range_ups[0]['r']},{range_ups[0]['c']})"
        )
    finally:
        sim.close()


def test_destroyed_plain_crate_drops_nothing() -> None:
    """A plain crate (no loot markers) leaves an empty cell when blasted."""
    sim = _build_sim()
    try:
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
        )
        # Row 2 has C at (2,4). Agent at (1,1). Path: east to (1,3), then east
        # places a bomb at (1,4) whose south arm hits (2,4)=plain crate.
        _step(sim, "move_east", "noop")   # (1,1) → (1,2)
        _step(sim, "move_east", "noop")   # (1,2) → (1,3)
        _step(sim, "change_vibe_bomb", "noop")
        _step(sim, "move_east", "noop")   # bomb at (1,4), agent stays at (1,3)
        _step(sim, "change_vibe_default", "noop")
        # Step out of the bomb's west arm.
        _step(sim, "move_west", "noop")   # (1,3) → (1,2)
        _step_both_noop(sim, FUSE_TICKS)

        # No pickups should appear.
        assert _count_type(sim, "range_up") == 0, "plain crate should not drop range_up"
        assert _count_type(sim, "count_up") == 0, "plain crate should not drop count_up"
    finally:
        sim.close()


def test_destroyed_count_crate_drops_count_up() -> None:
    """Blasting a count crate leaves a count_up pickup in its cell.

    Count crate B at (3,5) on the powerups map. Bombing from (3,4) places
    the count crate in the east arm of the blast (distance 1).
    """
    sim = _build_sim()
    try:
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
        )
        # Agent 0 at (1,1) → (2,1) → (3,1) → (3,2)? Row 3 has C at (3,2), blocked.
        # Try: (1,1) → (1,2) → (1,3) → (2,3) → (3,3) → bomb east at (3,4).
        # Row 1: #@........#  row 2: #.R.C.C.R.#  row 3: #.C..B..C.#
        # (2,3) is '.', (3,3) is '.', (3,4) is '.', (3,5)=B, (3,6)=.
        _step(sim, "move_east", "noop")   # (1,1) → (1,2)
        _step(sim, "move_east", "noop")   # (1,2) → (1,3)
        _step(sim, "move_south", "noop")  # (1,3) → (2,3)
        _step(sim, "move_south", "noop")  # (2,3) → (3,3)
        _step(sim, "change_vibe_bomb", "noop")
        _step(sim, "move_east", "noop")   # bomb at (3,4), agent stays at (3,3)
        _step(sim, "change_vibe_default", "noop")
        # Step out of west arm of bomb at (3,4): agent at (3,3) is in west arm.
        # Move further west: (3,2)=C (crate, blocked). Move north: (2,3)=empty.
        _step(sim, "move_north", "noop")  # (3,3) → (2,3)
        _step_both_noop(sim, FUSE_TICKS)

        # Blast from (3,4): east arm (3,5)=B (dist 1) → destroyed → count_up spawns.
        count_ups = _objects_of(sim, "count_up")
        assert len(count_ups) == 1, f"expected 1 count_up, got {len(count_ups)}"
        assert (count_ups[0]["r"], count_ups[0]["c"]) == (3, 5), (
            f"count_up should spawn at (3,5); got ({count_ups[0]['r']},{count_ups[0]['c']})"
        )
    finally:
        sim.close()


# ===== Pickup collection (end-to-end) =====


def test_collect_range_up_from_destroyed_crate() -> None:
    """End-to-end: destroy a range crate, walk onto the range_up pickup,
    confirm bomb_range incremented."""
    sim = _build_sim()
    try:
        _blast_adjacent_range_crate(sim)  # range_up at (2,2), agent at (2,1)
        assert _count_type(sim, "range_up") == 1

        initial_range = sim.agent(0).inventory.get("bomb_range", 0)
        # Walk onto the pickup at (2,2): agent at (2,1) → move east.
        _step(sim, "move_east", "noop")

        assert sim.agent(0).inventory.get("bomb_range", 0) == initial_range + 1, (
            "bomb_range should increase by 1 after collecting range_up"
        )
        assert _count_type(sim, "range_up") == 0, "pickup should be consumed"
    finally:
        sim.close()


def test_collect_count_up_from_destroyed_crate() -> None:
    """End-to-end: destroy a count crate, walk onto the count_up pickup,
    confirm bomb_slots incremented."""
    sim = _build_sim()
    try:
        # Navigate same way as test_destroyed_count_crate_drops_count_up.
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
        )
        _step(sim, "move_east", "noop")
        _step(sim, "move_east", "noop")
        _step(sim, "move_south", "noop")
        _step(sim, "move_south", "noop")
        _step(sim, "change_vibe_bomb", "noop")
        _step(sim, "move_east", "noop")     # bomb at (3,4)
        _step(sim, "change_vibe_default", "noop")
        _step(sim, "move_north", "noop")    # (3,3) → (2,3)
        _step_both_noop(sim, FUSE_TICKS)

        count_ups = _objects_of(sim, "count_up")
        assert len(count_ups) == 1 and (count_ups[0]["r"], count_ups[0]["c"]) == (3, 5)

        initial_slots = sim.agent(0).inventory.get("bomb_slots", 0)
        # Walk onto the pickup at (3,5) from (2,3): south south, east east.
        _step(sim, "move_south", "noop")    # (2,3) → (3,3)
        _step(sim, "move_east", "noop")     # (3,3) → (3,4)
        _step(sim, "move_east", "noop")     # (3,4) → bump into count_up at (3,5), collects

        assert sim.agent(0).inventory.get("bomb_slots", 0) == initial_slots + 1
        assert _count_type(sim, "count_up") == 0
    finally:
        sim.close()


# ===== Cap behaviours (preserved from pre-loot design) =====


def test_range_up_caps_at_max() -> None:
    """Picking up range_up doesn't exceed BOMB_RANGE_MAX=5.

    Agent starts at bomb_range=2. Set it to BOMB_RANGE_MAX first, then
    collect a range_up — range should stay at the cap.
    """
    sim = _build_sim()
    try:
        # Destroy range crate, get the pickup.
        _blast_adjacent_range_crate(sim)
        # Pre-cap bomb_range. BOMB_RANGE_MAX = 5 in game.py.
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 5, "hp": 3}
        )
        # Walk onto pickup.
        _step(sim, "move_east", "noop")

        assert sim.agent(0).inventory.get("bomb_range", 0) == 5, (
            "bomb_range should stay capped at BOMB_RANGE_MAX=5"
        )
    finally:
        sim.close()


def test_count_up_raises_bomb_count_ceiling() -> None:
    """Collecting count_up raises bomb_slots (which scales the bomb_count cap).
    Afterward the agent can hold BOMB_MAX+1 bombs."""
    sim = _build_sim()
    try:
        # Destroy count crate, walk onto pickup.
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": BLAST_RANGE, "hp": 3}
        )
        _step(sim, "move_east", "noop")
        _step(sim, "move_east", "noop")
        _step(sim, "move_south", "noop")
        _step(sim, "move_south", "noop")
        _step(sim, "change_vibe_bomb", "noop")
        _step(sim, "move_east", "noop")
        _step(sim, "change_vibe_default", "noop")
        _step(sim, "move_north", "noop")
        _step_both_noop(sim, FUSE_TICKS)
        _step(sim, "move_south", "noop")
        _step(sim, "move_east", "noop")
        _step(sim, "move_east", "noop")     # collect count_up

        assert sim.agent(0).inventory.get("bomb_slots", 0) == BOMB_MAX + 1

        # Now verify bomb_count can hold BOMB_MAX + 1 (cap raised).
        sim.agent(0).set_inventory(
            {
                "bomb_count": BOMB_MAX + 1,
                "bomb_slots": BOMB_MAX + 1,
                "bomb_range": BLAST_RANGE,
                "hp": 3,
            }
        )
        _step(sim, "noop", "noop")
        assert sim.agent(0).inventory.get("bomb_count", 0) == BOMB_MAX + 1, (
            "bomb_count should hold 4 when bomb_slots = 4 (cap raised)"
        )
    finally:
        sim.close()


def test_placed_bomb_carries_upgraded_range() -> None:
    """After collecting range_up, a bomb placed by the agent carries the
    upgraded bomb_range in its bomb_range_transfer slot."""
    sim = _build_sim()
    try:
        _blast_adjacent_range_crate(sim)
        # Collect pickup.
        _step(sim, "move_east", "noop")
        upgraded_range = sim.agent(0).inventory.get("bomb_range", 0)
        assert upgraded_range == BLAST_RANGE + 1

        # Place a bomb. Agent is at (2,2); move_east places bomb at (2,3) if
        # (2,3) is empty. Row 2: #.R.C.C.R.# — (2,3) is '.', (2,4) is C.
        # Actually, after earlier events, crate (2,2) was destroyed. Agent
        # walked onto (2,2). Let's place east.
        sim.agent(0).set_inventory(
            {
                "bomb_count": 1,
                "bomb_slots": BOMB_MAX,
                "bomb_range": upgraded_range,
                "hp": 3,
            }
        )
        _step(sim, "change_vibe_bomb", "noop")
        _step(sim, "move_east", "noop")     # bomb at (2,3)

        bombs = _objects_of(sim, "bomb")
        assert len(bombs) == 1
        bomb = bombs[0]
        transfer_id = sim.resource_names.index("bomb_range_transfer")
        assert bomb["inventory"].get(transfer_id, 0) == upgraded_range, (
            f"placed bomb should carry bomb_range_transfer={upgraded_range}"
        )
    finally:
        sim.close()
