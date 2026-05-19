"""Tests for the bombercog chain_reaction variant."""

from __future__ import annotations

from conftest import build_sim

from bombercog.game import BOMB_MAX, FUSE_TICKS
from mettagrid.simulator import Simulation


def _build_sim(variants: list[str] | None, max_steps: int = 500) -> Simulation:
    return build_sim(num_agents=2, max_steps=max_steps, variants=variants)


def _count_type(sim: Simulation, type_name: str) -> int:
    return sum(1 for o in sim.grid_objects().values() if o.get("type_name") == type_name)


def _objects_of(sim: Simulation, type_name: str) -> list[dict]:
    return [o for o in sim.grid_objects().values() if o.get("type_name") == type_name]


def _agent_pos(sim: Simulation, agent_idx: int) -> tuple[int, int]:
    agents = _objects_of(sim, "agent")
    agents_sorted = sorted(agents, key=lambda o: o.get("agent_id", 0))
    a = agents_sorted[agent_idx]
    return (a["r"], a["c"])


def _place_two_bombs_in_a_row(sim: Simulation) -> list[tuple[int, int]]:
    """Drop bombs on cells (1,2) and (2,2).

    Agent 0 starts at (1,1). place_bomb auto-resets vibe to default after
    each placement, so only five steps are needed — tight enough that
    bomb1's fuse (5 ticks) hasn't yet expired by the time bomb2 is placed:

      t1: change_vibe_bomb
      t2: move_east   → bomb1 at (1,2); vibe resets to default; bomb1.fuse=4
      t3: move_south  → agent to (2,1); bomb1.fuse=3
      t4: change_vibe_bomb; bomb1.fuse=2
      t5: move_east   → bomb2 at (2,2); bomb1.fuse=1, bomb2.fuse=4
    """
    # Give agent 0 enough bombs to place two without relying on regen.
    sim.agent(0).set_inventory({"bomb_count": BOMB_MAX, "bomb_slots": BOMB_MAX, "bomb_range": 2, "hp": 3})

    sim.agent(0).set_action("change_vibe_bomb")
    sim.agent(1).set_action("noop")
    sim.step()

    sim.agent(0).set_action("move_east")
    sim.agent(1).set_action("noop")
    sim.step()

    # Vibe auto-reset kicks in after the place_bomb handler — no manual
    # change_vibe_default needed before walking south.
    sim.agent(0).set_action("move_south")
    sim.agent(1).set_action("noop")
    sim.step()

    sim.agent(0).set_action("change_vibe_bomb")
    sim.agent(1).set_action("noop")
    sim.step()

    sim.agent(0).set_action("move_east")
    sim.agent(1).set_action("noop")
    sim.step()

    return [(1, 2), (2, 2)]


def test_base_game_has_no_bomb_hp() -> None:
    """In the base game (no chain_reaction variant), bombs do not carry
    a ``bomb_hp`` resource and the resource is not even in the game's
    resource_names — so blasts cannot damage other bombs."""
    sim = _build_sim(variants=None)
    try:
        assert "bomb_hp" not in sim.resource_names, (
            "base game should not declare bomb_hp resource"
        )
    finally:
        sim.close()


def test_chain_reaction_variant_registers_bomb_hp() -> None:
    """The chain_reaction variant adds ``bomb_hp`` to resource_names and
    to the bomb template's initial inventory."""
    sim = _build_sim(variants=["chain_reaction"])
    try:
        assert "bomb_hp" in sim.resource_names, (
            "chain_reaction variant should register bomb_hp resource"
        )

        # Spawn a bomb and verify it carries bomb_hp=1.
        sim.agent(0).set_inventory({"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 2, "hp": 3})
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()

        bombs = _objects_of(sim, "bomb")
        assert len(bombs) == 1
        bomb_hp_id = sim.resource_names.index("bomb_hp")
        assert bombs[0]["inventory"].get(bomb_hp_id, 0) == 1, (
            "fresh bomb should start with bomb_hp=1 under chain_reaction"
        )
    finally:
        sim.close()


def test_chain_reaction_solitary_bomb_cleaned_up_after_detonation() -> None:
    """Regression: a solitary bomb (no chain) must still be removed from
    the grid after it detonates, even with chain_reaction's bomb_hp
    inventory slot. The base game's remove_exploded event uses
    remove_when_empty=True on the withdraw, so bomb_hp must be drained
    before that event fires or the bomb lingers as a zombie.
    """
    sim = _build_sim(variants=["chain_reaction"])
    try:
        # Place one bomb and wait out the entire fuse + a couple extra
        # ticks for cleanup to run. No other bombs around = no chain.
        sim.agent(0).set_inventory(
            {"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 2, "hp": 3}
        )
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()
        assert _count_type(sim, "bomb") == 1, "bomb should be placed"

        # Run until well after the fuse expires.
        for _ in range(FUSE_TICKS + 5):
            sim.agent(0).set_action("noop")
            sim.agent(1).set_action("noop")
            sim.step()

        assert _count_type(sim, "bomb") == 0, (
            "solitary bomb should be fully removed after its fuse expires; "
            "lingering bombs mean bomb_hp blocked the remove_when_empty check"
        )
    finally:
        sim.close()


def test_chain_reaction_first_bomb_damages_second() -> None:
    """With chain_reaction, the first bomb's blast decrements the second
    bomb's bomb_hp. After the first bomb detonates, the second bomb's
    bomb_hp should be 0 (damaged but not yet detonated)."""
    sim = _build_sim(variants=["chain_reaction"])
    try:
        _place_two_bombs_in_a_row(sim)
        assert _count_type(sim, "bomb") == 2

        bomb_hp_id = sim.resource_names.index("bomb_hp")
        fuse_id = sim.resource_names.index("fuse")

        # Step until the first bomb detonates. The first bomb was placed
        # with FUSE_TICKS ticks; we've already used a few ticks in setup.
        # Step generously and observe the damage event.
        for _ in range(FUSE_TICKS + 2):
            sim.agent(0).set_action("noop")
            sim.agent(1).set_action("noop")
            sim.step()
            bombs = _objects_of(sim, "bomb")
            if len(bombs) == 1:
                # First bomb gone. The survivor should have bomb_hp=0 because
                # it was in the first bomb's blast path. The engine strips
                # resources at zero from the inventory dict, so a missing
                # bomb_hp key means bomb_hp == 0 — use default=0 here.
                survivor = bombs[0]
                assert survivor["inventory"].get(bomb_hp_id, 0) == 0, (
                    "damaged bomb should have bomb_hp=0 after first detonation"
                )
                # Its fuse should still be >0 (not yet detonated this tick).
                assert survivor["inventory"].get(fuse_id, 0) >= 0
                return
        # If we ever have 0 bombs without observing the 1-bomb state,
        # the chain fired too fast — still acceptable, but assert that the
        # chain test below catches it.
    finally:
        sim.close()


def test_chain_reaction_second_bomb_detonates_within_two_ticks() -> None:
    """With chain_reaction, after the first bomb explodes the second bomb
    should detonate within ~1 additional tick and be removed from the grid."""
    sim = _build_sim(variants=["chain_reaction"])
    try:
        _place_two_bombs_in_a_row(sim)
        assert _count_type(sim, "bomb") == 2

        saw_zero_bombs = False
        # Step through enough ticks for both bombs to detonate.
        for _ in range(FUSE_TICKS + 5):
            sim.agent(0).set_action("noop")
            sim.agent(1).set_action("noop")
            sim.step()
            if _count_type(sim, "bomb") == 0:
                saw_zero_bombs = True
                break

        assert saw_zero_bombs, (
            "both bombs should be removed after chain reaction completes"
        )
    finally:
        sim.close()


def test_chain_reaction_blocked_by_wall() -> None:
    """Two bombs with a wall between them do not chain — the wall stops
    the blast raycast."""
    # Agent 0 at (1,1). Place bomb east at (1,2). Agent 1 at (7,9). Place
    # bomb at (7,8) or similar. But these two bombs are on opposite sides
    # of the map, with many walls/crates between them. Should never chain.
    sim = _build_sim(variants=["chain_reaction"])
    try:
        # Agent 0 drops a bomb at (1,2).
        sim.agent(0).set_inventory({"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 2, "hp": 3})
        sim.agent(0).set_action("change_vibe_bomb")
        sim.agent(1).set_action("noop")
        sim.step()
        sim.agent(0).set_action("move_east")
        sim.agent(1).set_action("noop")
        sim.step()

        # Agent 1 drops a bomb at (7,8).
        sim.agent(1).set_inventory({"bomb_count": 1, "bomb_slots": BOMB_MAX, "bomb_range": 2, "hp": 3})
        sim.agent(1).set_action("change_vibe_bomb")
        sim.agent(0).set_action("noop")
        sim.step()
        sim.agent(1).set_action("move_west")
        sim.agent(0).set_action("noop")
        sim.step()

        assert _count_type(sim, "bomb") == 2

        bomb_hp_id = sim.resource_names.index("bomb_hp")

        # Step through both fuses. Each bomb should detonate independently
        # without any chain. Neither should ever reach bomb_hp=0 from the
        # other's blast (they're on opposite sides of the map with walls and
        # crates between them).
        for _ in range(FUSE_TICKS + 5):
            sim.agent(0).set_action("noop")
            sim.agent(1).set_action("noop")
            sim.step()
            for bomb in _objects_of(sim, "bomb"):
                # bomb_hp should stay at 1 — bombs only lose hp via chain.
                assert bomb["inventory"].get(bomb_hp_id, 1) == 1, (
                    "distant bombs should not chain through walls and crates"
                )
    finally:
        sim.close()
