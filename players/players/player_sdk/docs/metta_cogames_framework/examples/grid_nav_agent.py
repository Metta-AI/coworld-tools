"""Exploring an unknown maze with ``players.player_sdk.nav_grid``.

Executable documentation for the grid-navigation per-tick caller contract
under *partial observability*: two agents wake up in an ASCII maze they have
never seen, each perceiving only a small window around itself, and sweep it
with frontier exploration — dead-reckoning their own positions the whole way
(no ground-truth coordinates, exactly like a limited-information game).

The loop each tick, per agent, is the contract from ``nav_grid/README.md``:

    1. update_position(nav, last_dir, succeeded)   # fold last move result
    2. view = observe(nav, frozen_tags, obs_center)
    3. target = frontier_bfs(...)                  # explore.py picks WHERE
    4. direction = next_move_cached(nav, view, target)   # core.py picks HOW
    5. record_step(nav)

Run from the repo root with:

    python players/player_sdk/docs/metta_cogames_framework/examples/grid_nav_agent.py
"""

from __future__ import annotations

from players.player_sdk.nav_grid import (
    MOVE_DELTAS,
    Coordinate,
    ExploreConfig,
    ExploreState,
    GridNavConfig,
    GridNavState,
    frontier_bfs,
    next_move_cached,
    note_observed,
    observe,
    record_step,
    update_position,
)

MAZE = [
    "####################",
    "#........#.........#",
    "#.######.#.#######.#",
    "#.#....#.#.#.....#.#",
    "#.#.##.#.#.#.###.#.#",
    "#.#.#..#...#...#.#.#",
    "#.#.#.#######.#..#.#",
    "#...#.........#..#.#",
    "#.###.###.###.####.#",
    "#.....#.....#......#",
    "####################",
]

TAG_WALL = 0
VIEW_RADIUS = 2  # each agent sees a 5x5 window around itself
SPAWNS = [(1, 1), (9, 18)]


def wall_at(world_rc: Coordinate) -> bool:
    r, c = world_rc
    if not (0 <= r < len(MAZE) and 0 <= c < len(MAZE[0])):
        return True
    return MAZE[r][c] == "#"


class Agent:
    """One dead-reckoning explorer. Local frame: its spawn is (0, 0)."""

    def __init__(self, agent_id: int, spawn: Coordinate) -> None:
        self.agent_id = agent_id
        self.spawn = spawn
        self.world = spawn  # engine truth — used ONLY to simulate the env
        self.nav = GridNavState(config=GridNavConfig(wall_tag_ids=frozenset({TAG_WALL})))
        self.explore = ExploreState()
        self.explore_cfg = ExploreConfig()
        self.last_dir: str | None = None
        self.last_succeeded = True
        self.done = False

    def sense(self) -> dict[Coordinate, frozenset[int]]:
        """The env's observation: tags for every cell in the local window,
        keyed by window coordinate (the agent's own cell is the center)."""
        tags: dict[Coordinate, frozenset[int]] = {}
        for dr in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
            for dc in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
                world = (self.world[0] + dr, self.world[1] + dc)
                tags[(dr, dc)] = frozenset({TAG_WALL}) if wall_at(world) else frozenset()
        return tags

    def tick(self, step: int) -> None:
        # 1. Fold the previous move attempt into position/blocked.
        update_position(self.nav, self.last_dir, self.last_succeeded)

        # 2. Classify this tick's window (center = (0, 0) window coord).
        frozen_tags = self.sense()
        view = observe(self.nav, frozen_tags, obs_center=(0, 0))
        note_observed(self.explore, view, self.nav, step)

        # 3. WHERE: nearest never-observed cell (frontier exploration).
        target = frontier_bfs(self.explore, view, self.nav, self.explore_cfg, step)
        if target is None:
            self.last_dir = None
            self.done = True  # nothing left to explore from here
            return

        # 4. HOW: cost-shaped A* with a cached plan.
        direction = next_move_cached(self.nav, view, target)
        record_step(self.nav)  # 5. push the tabu trail

        # --- the "engine": attempt the move against ground truth ---
        self.last_dir = direction
        if direction is None:
            self.last_succeeded = False
            return
        dr, dc = MOVE_DELTAS[direction]
        nxt = (self.world[0] + dr, self.world[1] + dc)
        self.last_succeeded = not wall_at(nxt)
        if self.last_succeeded:
            self.world = nxt


def render(agents: list[Agent]) -> str:
    open_cells = sum(row.count(".") for row in MAZE)
    # An agent's local (0,0) is its spawn: world = spawn + local.
    observed = {
        (a.spawn[0] + lr, a.spawn[1] + lc)
        for a in agents
        for (lr, lc) in a.explore.cell_last_seen
    }
    stood_on = {
        (a.spawn[0] + lr, a.spawn[1] + lc) for a in agents for (lr, lc) in a.nav.visited
    }
    rows = []
    for r, row in enumerate(MAZE):
        chars = []
        for c, ch in enumerate(row):
            marker = ch
            if ch == "." and (r, c) in stood_on:
                marker = "·"
            for a in agents:
                if (r, c) == a.world:
                    marker = str(a.agent_id)
            chars.append(marker)
        rows.append("".join(chars))
    n_observed = sum(1 for cell in observed if not wall_at(cell))
    rows.append(f"observed {n_observed}/{open_cells} open cells "
                f"(stood on {sum(1 for cell in stood_on if not wall_at(cell))})")
    return "\n".join(rows)


def main() -> None:
    agents = [Agent(i, spawn) for i, spawn in enumerate(SPAWNS)]
    final_step = 0
    for step in range(1, 401):
        final_step = step
        for agent in agents:
            agent.tick(step)
        if all(a.done for a in agents):
            break
    print(f"--- exploration finished at step {final_step} ---")
    print(render(agents))
    print("\n'·' = cells an agent stood on (dead-reckoned); digits = agents.")


if __name__ == "__main__":
    main()
