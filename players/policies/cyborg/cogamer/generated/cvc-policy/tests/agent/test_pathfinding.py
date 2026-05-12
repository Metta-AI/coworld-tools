"""Tests for cvc.agent.pathfinding."""

from __future__ import annotations

from cvc_policy.agent.pathfinding import (
    NavigationObservation,
    astar_next_step,
    detect_extractor_oscillation,
)

# ---------------------------------------------------------------------------
# astar_next_step
# ---------------------------------------------------------------------------


class TestAstarNextStep:
    """Tests for astar_next_step."""

    def test_same_position_returns_none(self):
        assert astar_next_step((3, 3), (3, 3), set()) is None

    def test_adjacent_north(self):
        assert astar_next_step((5, 5), (5, 4), set()) == (5, 4)

    def test_adjacent_south(self):
        assert astar_next_step((5, 5), (5, 6), set()) == (5, 6)

    def test_adjacent_east(self):
        assert astar_next_step((5, 5), (6, 5), set()) == (6, 5)

    def test_adjacent_west(self):
        assert astar_next_step((5, 5), (4, 5), set()) == (4, 5)

    def test_adjacent_blocked_still_returns_target(self):
        # Manhattan distance == 1 returns target without checking blocked
        result = astar_next_step((5, 5), (6, 5), {(6, 5)})
        assert result == (6, 5)

    def test_straight_line_no_obstacles(self):
        # From (0, 0) to (3, 0) — should step east first
        step = astar_next_step((0, 0), (3, 0), set())
        assert step == (1, 0)

    def test_straight_line_vertical(self):
        step = astar_next_step((0, 0), (0, 3), set())
        assert step == (0, 1)

    def test_diagonal_target(self):
        # (0,0) to (2,2): first step should reduce distance
        step = astar_next_step((0, 0), (2, 2), set())
        assert step is not None
        # Must be one of the 4 cardinal neighbors of (0,0)
        assert step in [(1, 0), (0, 1), (-1, 0), (0, -1)]

    def test_wall_requiring_detour(self):
        # Wall along x=5 from y=3 to y=7, path from (4,5) to (6,5)
        wall = {(5, y) for y in range(3, 8)}
        step = astar_next_step((4, 5), (6, 5), wall)
        assert step is not None
        # First step must be a valid neighbor of (4,5) and not blocked
        assert step not in wall
        dx = step[0] - 4
        dy = step[1] - 5
        assert (abs(dx) + abs(dy)) == 1
        # Must go up or down to route around the wall
        assert step in [(4, 4), (4, 6), (3, 5)]

    def test_wall_path_reaches_target(self):
        # Verify the full path around a wall is feasible by stepping repeatedly
        wall = {(5, y) for y in range(3, 8)}
        current = (4, 5)
        target = (6, 5)
        visited = {current}
        for _ in range(50):
            step = astar_next_step(current, target, wall)
            if step is None:
                break
            assert step not in wall
            current = step
            visited.add(current)
            if current == target:
                break
        assert current == target

    def test_completely_surrounded_returns_greedy_step(self):
        # Block all A* paths but leave one neighbor open — greedy fallback
        current = (10, 10)
        target = (15, 10)
        # Create a box around current that has a gap only to the south
        blocked = set()
        for x in range(8, 13):
            for y in range(8, 13):
                if (x, y) != current and (x, y) != (10, 11):
                    blocked.add((x, y))
        # Also block everything between current and target except the path
        # through south — create a massive wall
        for x in range(11, 15):
            for y in range(8, 13):
                blocked.add((x, y))
        result = astar_next_step(current, target, blocked)
        # Should still return something (greedy fallback or A* detour)
        assert result is not None

    def test_all_neighbors_blocked_returns_none(self):
        current = (10, 10)
        target = (15, 10)
        # Block all 4 cardinal neighbors
        blocked = {(10, 9), (10, 11), (9, 10), (11, 10)}
        result = astar_next_step(current, target, blocked)
        # greedy_step also has no candidates, so returns None
        assert result is None

    def test_large_distance(self):
        step = astar_next_step((0, 0), (20, 20), set())
        assert step is not None
        assert step in [(1, 0), (0, 1)]

    def test_negative_coordinates(self):
        step = astar_next_step((-5, -5), (-2, -5), set())
        assert step == (-4, -5)

    def test_bound_margin_limits_search(self):
        # With a tiny bound_margin, a detour might be outside bounds
        # Wall at x=5, y=3..7; path from (4,5) to (6,5)
        wall = {(5, y) for y in range(3, 8)}
        # bound_margin=0 means search box is [4,6] x [5,5] — no room to detour
        step = astar_next_step((4, 5), (6, 5), wall, bound_margin=0)
        # A* can't find path, falls back to greedy
        assert step is not None


# ---------------------------------------------------------------------------
# detect_extractor_oscillation
# ---------------------------------------------------------------------------


def _obs(
    pos: tuple[int, int],
    subtask: str = "mine_iron",
    target_kind: str = "iron_extractor",
    target_position: tuple[int, int] | None = (20, 20),
) -> NavigationObservation:
    return NavigationObservation(
        position=pos,
        subtask=subtask,
        target_kind=target_kind,
        target_position=target_position,
    )


class TestDetectExtractorOscillation:
    """Tests for detect_extractor_oscillation."""

    def test_empty_list(self):
        assert detect_extractor_oscillation([]) == 0

    def test_single_observation(self):
        assert detect_extractor_oscillation([_obs((1, 1))]) == 0

    def test_two_step_oscillation(self):
        obs = [_obs((1, 1)), _obs((2, 2))]
        assert detect_extractor_oscillation(obs) == 2

    def test_four_step_oscillation(self):
        obs = [_obs((1, 1)), _obs((2, 2)), _obs((1, 1)), _obs((2, 2))]
        assert detect_extractor_oscillation(obs) == 4

    def test_six_step_oscillation(self):
        obs = [
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
        ]
        assert detect_extractor_oscillation(obs) == 6

    def test_returns_largest_window(self):
        # 4 observations that form a valid oscillation of length 4
        # Also valid as length 2 from the tail, but 4 is larger
        obs = [_obs((1, 1)), _obs((2, 2)), _obs((1, 1)), _obs((2, 2))]
        assert detect_extractor_oscillation(obs) == 4

    def test_no_oscillation_different_subtasks(self):
        obs = [
            _obs((1, 1), subtask="mine_iron"),
            _obs((2, 2), subtask="mine_gold"),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_not_mining_subtask(self):
        obs = [
            _obs((1, 1), subtask="move_to"),
            _obs((2, 2), subtask="move_to"),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_not_extractor_target_kind(self):
        obs = [
            _obs((1, 1), target_kind="iron_mine"),
            _obs((2, 2), target_kind="iron_mine"),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_same_position_repeated(self):
        obs = [_obs((1, 1)), _obs((1, 1)), _obs((1, 1)), _obs((1, 1))]
        assert detect_extractor_oscillation(obs) == 0

    def test_target_position_none(self):
        obs = [
            _obs((1, 1), target_position=None),
            _obs((2, 2), target_position=None),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_different_target_positions(self):
        obs = [
            _obs((1, 1), target_position=(10, 10)),
            _obs((2, 2), target_position=(20, 20)),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_different_target_kinds(self):
        obs = [
            _obs((1, 1), target_kind="iron_extractor"),
            _obs((2, 2), target_kind="gold_extractor"),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_three_distinct_positions_still_detects_tail(self):
        # a, b, c — window of 3 fails (c != a), but window of 2 (b, c) is valid
        obs = [_obs((1, 1)), _obs((2, 2)), _obs((3, 3))]
        assert detect_extractor_oscillation(obs) == 2

    def test_no_oscillation_when_subtask_varies_across_all(self):
        # Even the 2-element tail has different subtasks
        obs = [
            _obs((1, 1), subtask="mine_iron"),
            _obs((2, 2), subtask="mine_gold"),
            _obs((3, 3), subtask="mine_copper"),
        ]
        assert detect_extractor_oscillation(obs) == 0

    def test_oscillation_only_in_tail(self):
        # First observations break the pattern, but last 2 are valid
        obs = [
            _obs((5, 5)),
            _obs((6, 6)),
            _obs((1, 1)),
            _obs((2, 2)),
        ]
        # Window of 4: positions (5,5),(6,6),(1,1),(2,2) — not alternating
        # Window of 3: (6,6),(1,1),(2,2) — first=(6,6), second=(1,1),
        # check (6,6),(1,1),(2,2) — pos[2] should be (6,6) but is (2,2) — no
        # Window of 2: (1,1),(2,2) — valid oscillation
        assert detect_extractor_oscillation(obs) == 2

    def test_max_history_limits_window(self):
        obs = [
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
        ]
        # max_history=4 means we check windows of size 4, 3, 2
        result = detect_extractor_oscillation(obs, max_history=4)
        assert result == 4

    def test_max_history_2(self):
        obs = [
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
        ]
        result = detect_extractor_oscillation(obs, max_history=2)
        assert result == 2

    def test_odd_window_oscillation(self):
        # 3-step window: a, b, a — valid oscillation
        obs = [_obs((1, 1)), _obs((2, 2)), _obs((1, 1))]
        assert detect_extractor_oscillation(obs) == 3

    def test_five_step_oscillation(self):
        obs = [
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
            _obs((2, 2)),
            _obs((1, 1)),
        ]
        assert detect_extractor_oscillation(obs) == 5

    def test_long_history_capped_at_max_history(self):
        # 10 observations but max_history defaults to 6
        obs = [_obs((1, 1)), _obs((2, 2))] * 5
        result = detect_extractor_oscillation(obs)
        assert result == 6
