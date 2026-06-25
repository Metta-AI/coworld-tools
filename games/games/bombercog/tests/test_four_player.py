"""Tests for the bombercog four_player variant."""

from __future__ import annotations

from conftest import build_sim

from bombercog.variants.four_player import MAP_13x11, NUM_PLAYERS
from mettagrid.simulator import Simulation


def _build_sim(num_agents: int = NUM_PLAYERS, max_steps: int = 500) -> Simulation:
    return build_sim(num_agents=num_agents, max_steps=max_steps, variants=["four_player"])


def _objects_of(sim: Simulation, type_name: str) -> list[dict]:
    return [o for o in sim.grid_objects().values() if o.get("type_name") == type_name]


def test_four_player_spawns_four_agents() -> None:
    """The four_player variant puts 4 agents on the grid."""
    sim = _build_sim()
    try:
        agents = _objects_of(sim, "agent")
        assert len(agents) == NUM_PLAYERS, f"expected {NUM_PLAYERS} agents, got {len(agents)}"
    finally:
        sim.close()


def test_four_player_map_is_13x11() -> None:
    """The variant replaces the map with the 13x11 grid."""
    sim = _build_sim()
    try:
        # The map has a 13-wide, 11-tall grid — confirmed by counting wall
        # positions on the outer border.
        walls = _objects_of(sim, "wall")
        # Outer border = 2*13 + 2*(11-2) = 26 + 18 = 44 wall cells.
        assert len(walls) >= 44, (
            f"expected at least 44 outer wall cells (13x11 perimeter), got {len(walls)}"
        )
    finally:
        sim.close()


def test_four_player_spawn_adjacent_to_crate() -> None:
    """Every agent spawn has at least one crate neighbour — each player
    has a meaningful first bomb."""
    sim = _build_sim()
    try:
        agents = _objects_of(sim, "agent")
        crate_positions = {(c["r"], c["c"]) for c in _objects_of(sim, "crate")}

        for a in agents:
            r, c = a["r"], a["c"]
            neighbors = {(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)}
            assert neighbors & crate_positions, (
                f"agent at ({r},{c}) has no adjacent crate; neighbours={neighbors}"
            )
    finally:
        sim.close()


def test_four_player_map_constant_shape() -> None:
    """Sanity check the map constant — all rows are 13 chars, 11 rows."""
    assert len(MAP_13x11) == 11, f"expected 11 rows, got {len(MAP_13x11)}"
    for i, row in enumerate(MAP_13x11):
        assert len(row) == 13, f"row {i} has {len(row)} cols, expected 13"
    # Exactly 4 spawn markers.
    spawn_count = sum(row.count("@") for row in MAP_13x11)
    assert spawn_count == NUM_PLAYERS, (
        f"expected {NUM_PLAYERS} '@' spawns in map constant, got {spawn_count}"
    )


def test_four_player_variant_compatible_with_num_agents_param() -> None:
    """Passing num_agents=4 alongside the variant works (the two agree)."""
    sim = _build_sim(num_agents=NUM_PLAYERS)
    try:
        assert len(_objects_of(sim, "agent")) == NUM_PLAYERS
    finally:
        sim.close()
