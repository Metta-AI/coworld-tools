"""Scenario tests for players.player_sdk.nav_grid (core).

Ported 1:1 from the embedded smoke test of the original ``swgy_nav.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

import heapq
from collections import deque

from players.player_sdk.nav_grid.core import (
    MOVE_DELTAS,
    Coordinate,
    GridNavConfig,
    GridNavState,
    GridNavView,
    TeamMemberTrack,
    _direction_from_delta,
    arrived,
    is_bump_target,
    next_move,
    next_move_cached,
    observe,
    plan_path,
    record_step,
    record_team_observations,
    update_position,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def _ref_manhattan_astar(
    start: Coordinate,
    goal: Coordinate,
    blocked: set[Coordinate],
    max_expansions: int = 5000,
) -> str | None:
    """Reference implementation: pure Manhattan A*, uniform cost, used
    by scenario 11 below to verify identity with vanilla A*. Lives in the
    test file (moved out of the shipped module during extraction)."""
    if start == goal:
        return None
    if goal in blocked:
        blocked = set(blocked) - {goal}

    def h(n: Coordinate) -> float:
        return abs(n[0] - goal[0]) + abs(n[1] - goal[1])

    open_heap: list[tuple[float, int, Coordinate, str | None]] = []
    heapq.heappush(open_heap, (h(start), 0, start, None))
    best_g: dict[Coordinate, float] = {start: 0.0}
    counter = 0
    exp = 0
    while open_heap and exp < max_expansions:
        _, _, cur, first_dir = heapq.heappop(open_heap)
        exp += 1
        if cur == goal:
            return first_dir
        if best_g.get(cur) is None:
            continue
        for d, (dr, dc) in MOVE_DELTAS.items():
            n = (cur[0] + dr, cur[1] + dc)
            if n in blocked:
                continue
            g = best_g[cur] + 1.0
            if best_g.get(n, float("inf")) <= g:
                continue
            best_g[n] = g
            chosen = first_dir if first_dir is not None else d
            counter += 1
            heapq.heappush(open_heap, (g + h(n), counter, n, chosen))
    return None


def test_core_smoke_scenarios() -> None:

    # Helper: build a default view at obs center (0, 0) (so local == obs).
    def empty_view() -> GridNavView:
        return GridNavView(obs_center=(0, 0))

    # 1. Vacuous A*: empty grid, target straight east.
    s = GridNavState()
    d = next_move(s, empty_view(), (0, 3))
    check("1 vacuous A*", d == "east", f"got {d}")

    # 2. Wall in the way: must detour.
    s = GridNavState()
    s.blocked.add((0, 1))
    d = next_move(s, empty_view(), (0, 3))
    check("2 wall detour", d in ("north", "south"), f"got {d}")

    # 3. Tabu trail recorded in newest-first order.
    cfg = GridNavConfig(tabu_strength=1.0, tabu_length=4)
    s = GridNavState(config=cfg)
    for col in range(1, 6):
        s.position = (0, col)
        record_step(s)
    expected_head = (0, 5)
    check(
        "3 tabu newest-first",
        len(s.position_history) == 4 and s.position_history[0] == expected_head,
        f"history={s.position_history}",
    )

    # 4. Stand-still tabu: no growth.
    cfg = GridNavConfig(tabu_strength=1.0, tabu_length=8)
    s = GridNavState(config=cfg)
    s.position = (0, 0)
    for _ in range(5):
        record_step(s)
    check("4 stand-still tabu", len(s.position_history) == 1, f"history={s.position_history}")

    # 5. Tabu pruning to length cap.
    cfg = GridNavConfig(tabu_strength=1.0, tabu_length=10)
    s = GridNavState(config=cfg)
    for col in range(1, 201):
        s.position = (0, col)
        record_step(s)
    check("5 tabu pruning", len(s.position_history) == 10, f"len={len(s.position_history)}")

    # 6. Stranger spacing forces a detour.
    # Strategy: target due east at (0, 4); plant a stranger at (0, 2)
    # with strong repulsion. Without repulsion, vanilla A* would happily
    # walk through (0, 2) (we hard-block it via blocker_locals). With
    # repulsion + a clear north corridor, A* should pick a detour.
    cfg = GridNavConfig(
        stranger_repulsion=200.0,
        stranger_spacing=2,
        stranger_falloff="linear",
    )
    s = GridNavState(config=cfg)
    view = GridNavView(obs_center=(0, 0))
    view.stranger_locals.add((0, 2))
    view.visible_tagged_locals.add((0, 2))  # hard block at the stranger's cell
    d = next_move(s, view, (0, 4))
    check("6 stranger detour", d in ("north", "south"), f"got {d}")

    # 7. Attractor pull bends the path. Target east at (0, 4); attractor
    # south at (4, 0) with full radius. With heuristic_mode="auto" and
    # an attractor present, switches to Dijkstra. First step should be
    # one of {south, east} (both are reasonable optima depending on
    # tie-breaking; the assert is just that the path doesn't go away
    # from both attractor and target).
    cfg = GridNavConfig(attractor_weight=20.0, attractor_radius=10)
    s = GridNavState(config=cfg)
    d = next_move(s, empty_view(), (0, 4), attractors=[(4, 0)])
    check("7 attractor pull", d in ("south", "east"), f"got {d}")

    # 8. target == position returns None, no mutation.
    s = GridNavState()
    before = (s.position, set(s.blocked), set(s.visited))
    d = next_move(s, empty_view(), s.position)
    check(
        "8 target==position",
        d is None
        and (s.position, set(s.blocked), set(s.visited)) == before,
        f"got {d}",
    )

    # 9. target in blocked: A* exempts goal, returns a move toward it.
    s = GridNavState()
    s.blocked.add((0, 3))
    d = next_move(s, empty_view(), (0, 3))
    check("9 goal-in-blocked", d in ("east", "north", "south"), f"got {d}")

    # 10. Budget exhaustion returns None.
    cfg = GridNavConfig(max_expansions=2)
    s = GridNavState(config=cfg)
    d = next_move(s, empty_view(), (0, 50))
    check("10 budget exhaustion", d is None, f"got {d}")

    # 11. Identity with vanilla A* under neutral config.
    cfg = GridNavConfig(
        base_terrain_weight=1.0,
        cost_floor=1.0,
        max_repulsion_per_step=0.0,
        max_attraction_per_step=0.0,
    )
    s = GridNavState(config=cfg)
    s.blocked = {(0, 2), (1, 2)}
    target = (0, 4)
    ours = next_move(s, empty_view(), target)
    ref = _ref_manhattan_astar(s.position, target, set(s.blocked))
    check("11 identity vs vanilla A*", ours == ref, f"ours={ours} ref={ref}")

    # 12. Tabu doesn't trap the agent: standing on a tabu cell, target
    # one east, should still go east (tabu cost is on the destination,
    # not the start).
    cfg = GridNavConfig(tabu_strength=1000.0, tabu_length=8, tabu_radius=0)
    s = GridNavState(config=cfg)
    s.position_history = [(0, 0)]
    d = next_move(s, empty_view(), (0, 1))
    check("12 tabu not trapping start", d == "east", f"got {d}")

    # 13. Team-trail tail-1 hard-block breaks the head-on deadlock.
    # Stranger 7 walked (1,3) -> (1,2) over two ticks.  Self at (1,2),
    # goal due east at (1,5).  Stranger's tail-1 is (1,3) — without
    # avoidance the planner will route through (1,3); with a hard tail-1
    # repulsion the planner detours via (0,3) or (2,3).
    cfg = GridNavConfig(
        team_trail_stranger_tail_hard_repulsion=400.0,
        team_trail_avoid_tail_stranger=1,
        max_repulsion_per_step=400.0,
    )
    s = GridNavState(config=cfg, position=(1, 2))
    track = TeamMemberTrack(
        agent_id=7, is_owned=False,
        positions=deque([(0, (1, 3)), (1, (1, 2))], maxlen=8),
        last_seen_step=1,
    )
    s.team_trails[7] = track
    d = next_move(s, empty_view(), (1, 5))
    check("13 trail tail-1 detour", d in ("north", "south"),
          f"got {d} (expected non-east)")

    # 14. Team-trail predicted-cell soft penalty steers around a stranger
    # heading our way, but does not hard-block (path through still
    # possible if cheaper alternatives exhausted).
    cfg = GridNavConfig(
        team_trail_stranger_predicted_repulsion=50.0,
        base_terrain_weight=10.0,
        max_repulsion_per_step=400.0,
    )
    s = GridNavState(config=cfg, position=(0, 0))
    # Stranger walking south at (1,2) -> (2,2); predicted (3,2).
    track = TeamMemberTrack(
        agent_id=9, is_owned=False,
        positions=deque([(0, (1, 2)), (1, (2, 2))], maxlen=8),
        last_seen_step=1,
    )
    s.team_trails[9] = track
    # Goal at (3,2) coincides with the predicted cell, but the goal
    # exemption means we still arrive (cost paid once at destination).
    d = next_move(s, empty_view(), (5, 2))
    check("14 predicted soft does not stall", d is not None, f"got {d}")

    # 15. Disabled trail (all weights 0): identity behavior — same
    # decision as without any team_trails.
    cfg = GridNavConfig()
    s = GridNavState(config=cfg, position=(1, 2))
    track = TeamMemberTrack(
        agent_id=7, is_owned=False,
        positions=deque([(0, (1, 3)), (1, (1, 2))], maxlen=8),
        last_seen_step=1,
    )
    s.team_trails[7] = track
    d_with_trails = next_move(s, empty_view(), (1, 5))
    s2 = GridNavState(config=cfg, position=(1, 2))
    d_without = next_move(s2, empty_view(), (1, 5))
    check("15 trail disabled => no behavior change",
          d_with_trails == d_without,
          f"with_trails={d_with_trails} without={d_without}")

    # 16. record_team_observations populates the trail.
    cfg = GridNavConfig(
        teammate_tag_ids=frozenset({100}),
        stranger_tag_ids=frozenset({100}),
        team_trail_stranger_predicted_repulsion=10.0,  # activate recording
    )
    s = GridNavState(config=cfg, position=(0, 0))
    AGENT_TAG = 200
    OWN_TEAM = 100
    obs_center = (5, 5)
    # Two ticks of observation: stranger 42 at obs (5,8) then (5,7).
    record_team_observations(
        s,
        frozen_tags={(5, 8): frozenset({OWN_TEAM, AGENT_TAG})},
        agent_id_at={(5, 8): 42},
        own_team_tag_ids=frozenset({OWN_TEAM}),
        agent_tag_id=AGENT_TAG,
        owned_agent_ids=frozenset({0}),
        step=0,
        obs_center=obs_center,
    )
    record_team_observations(
        s,
        frozen_tags={(5, 7): frozenset({OWN_TEAM, AGENT_TAG})},
        agent_id_at={(5, 7): 42},
        own_team_tag_ids=frozenset({OWN_TEAM}),
        agent_tag_id=AGENT_TAG,
        owned_agent_ids=frozenset({0}),
        step=1,
        obs_center=obs_center,
    )
    track = s.team_trails.get(42)
    check("16a record creates track", track is not None, "track is None")
    if track is not None:
        positions = list(track.positions)
        # obs(5,8) - obs_center(5,5) + position(0,0) = (0, 3)
        # obs(5,7) - obs_center(5,5) + position(0,0) = (0, 2)
        check("16b record correct local positions",
              positions == [(0, (0, 3)), (1, (0, 2))],
              f"got {positions}")
        check("16c record marks stranger", not track.is_owned,
              f"is_owned={track.is_owned}")

    # 17. Detour within budget routes via detour.
    # Empty grid, target (0, 5), detour (2, 0), budget 4.
    # Direct = 5 steps; via-detour = len(start->detour) + len(detour->target)
    # = 2 + 7 = 9; extra = 4 → fits the budget exactly.  First move should
    # head toward the detour (south); plan length 9; final cell is target.
    s = GridNavState()
    plan = plan_path(s, empty_view(), (0, 5), detour=(2, 0), max_detour_steps=4)
    check("17a detour-in-budget plan exists", plan is not None, "plan=None")
    if plan is not None:
        check("17b detour-in-budget plan length",
              len(plan) == 9, f"len={len(plan)}")
        check("17c detour-in-budget reaches target",
              plan[-1] == (0, 5), f"last={plan[-1]}")
        check("17d detour-in-budget visits detour",
              (2, 0) in plan, f"detour missing from plan={plan}")
        check("17e detour-in-budget first step toward detour",
              plan[0] == (1, 0), f"first={plan[0]}")

    # 18. Detour over budget falls back to direct.
    # Same setup, budget 2.  Extra = 4 > 2 → drop the detour, return
    # direct path of length 5.
    s = GridNavState()
    plan = plan_path(s, empty_view(), (0, 5), detour=(2, 0), max_detour_steps=2)
    check("18a detour-over-budget plan exists", plan is not None, "plan=None")
    if plan is not None:
        check("18b detour-over-budget direct length",
              len(plan) == 5, f"len={len(plan)}")
        check("18c detour-over-budget skips detour",
              (2, 0) not in plan, f"detour wrongly in plan={plan}")
        check("18d detour-over-budget reaches target",
              plan[-1] == (0, 5), f"last={plan[-1]}")

    # 19. Cache hit: a successful step does NOT trigger a replan.
    # First call plans and pops one cell.  After a successful east-move,
    # the second call should consume the next cached cell without
    # bumping cached_path_planned_step.
    s = GridNavState()
    d1 = next_move_cached(s, empty_view(), (0, 5), replan_every=10)
    check("19a first call returns east", d1 == "east", f"got {d1}")
    planned_first = s.cached_path_planned_step
    update_position(s, "east", True)
    record_step(s)
    d2 = next_move_cached(s, empty_view(), (0, 5), replan_every=10)
    check("19b cache survives successful step",
          s.cached_path_planned_step == planned_first,
          f"planned was {planned_first}, now {s.cached_path_planned_step}")
    check("19c second call returns east", d2 == "east", f"got {d2}")
    check("19d cache shrinks by 1",
          len(s.cached_path_cells) == 3,
          f"cells={s.cached_path_cells}")

    # 20. Cache invalidation on failed move.
    # Mark the previous attempted east as failed (transient agent
    # collision).  Next call must replan; cached_path_planned_step
    # advances.
    s = GridNavState()
    next_move_cached(s, empty_view(), (0, 5))
    planned_first = s.cached_path_planned_step
    update_position(s, "east", False, failed_into_agent=True)
    record_step(s)
    d2 = next_move_cached(s, empty_view(), (0, 5))
    check("20 failed-move triggers replan",
          s.cached_path_planned_step > planned_first and d2 is not None,
          f"planned {s.cached_path_planned_step} vs {planned_first}, d={d2}")

    # 21. Cache invalidation on newly-blocked next cell.
    # Successful first step, then a wall appears at the next cached
    # cell; next call must replan around it.
    s = GridNavState()
    next_move_cached(s, empty_view(), (0, 5))
    update_position(s, "east", True)
    record_step(s)
    s.blocked.add((0, 2))  # next cached cell becomes a wall
    planned_first = s.cached_path_planned_step
    d2 = next_move_cached(s, empty_view(), (0, 5))
    check("21 newly-blocked cell triggers replan",
          s.cached_path_planned_step > planned_first
          and d2 in ("north", "south"),
          f"planned {s.cached_path_planned_step} vs {planned_first}, d={d2}")

    # 22. Cache invalidation on N-step timer.
    # replan_every=2.  Advance state to make the timer condition
    # (step_counter - planned_step >= replan_every) true while leaving
    # the drift / failed-move / blocked-next-cell triggers all
    # negative; the timer is then the only reason to replan.
    s = GridNavState()
    next_move_cached(s, empty_view(), (0, 10), replan_every=2)
    planned_first = s.cached_path_planned_step  # = 0
    s.position = (0, 1)
    s.last_move_direction = "east"
    s.last_move_succeeded = True
    s.step_counter = 3  # 3 - 0 >= 2 → replan
    next_move_cached(s, empty_view(), (0, 10), replan_every=2)
    check("22 N-step timer triggers replan",
          s.cached_path_planned_step == 3
          and s.cached_path_planned_step > planned_first,
          f"planned was {planned_first}, now {s.cached_path_planned_step}")

    # 23. Target change forces replan; cached_path_target updates.
    s = GridNavState()
    next_move_cached(s, empty_view(), (0, 5))
    d2 = next_move_cached(s, empty_view(), (3, 0))
    check("23a target change updates cached_path_target",
          s.cached_path_target == (3, 0),
          f"cached_target={s.cached_path_target}")
    check("23b target change replans to new target",
          s.cached_path_cells and s.cached_path_cells[-1] == (3, 0),
          f"cells={s.cached_path_cells}")
    check("23c target change first move toward new target",
          d2 == "south", f"d={d2}")

    # 24. Detour unreachable falls back to direct.
    s = GridNavState()
    for cell in [(4, 5), (6, 5), (5, 4), (5, 6)]:
        s.blocked.add(cell)
    plan = plan_path(s, empty_view(), (0, 3), detour=(5, 5), max_detour_steps=100)
    check("24 unreachable detour falls back to direct",
          plan is not None and len(plan) == 3 and plan[-1] == (0, 3),
          f"plan={plan}")

    # 25. plan_path first-cell direction matches next_move under same
    # config and inputs (no detour).  Confirms the full-path
    # reconstruction agrees with the first-step-only A*.
    target = (3, 4)
    s_a = GridNavState()
    s_b = GridNavState()
    plan = plan_path(s_a, empty_view(), target)
    direct = next_move(s_b, empty_view(), target)
    plan_first_dir = None
    if plan:
        delta = (plan[0][0] - s_a.position[0], plan[0][1] - s_a.position[1])
        plan_first_dir = _direction_from_delta(delta)
    check("25 plan_path first-step matches next_move",
          plan_first_dir == direct,
          f"plan_first={plan_first_dir} direct={direct}")

    # 26. direct=True ignores nav.blocked.
    s = GridNavState()
    s.blocked.add((0, 1))  # would block default mode
    d_default = next_move(s, empty_view(), (0, 3))
    d_direct = next_move(s, empty_view(), (0, 3), direct=True)
    check("26 direct ignores nav.blocked",
          d_default in ("north", "south") and d_direct == "east",
          f"default={d_default} direct={d_direct}")

    # 27. direct=True still respects walls in view.blocker_locals.
    v = GridNavView(obs_center=(0, 0))
    v.blocker_locals.add((0, 1))
    s = GridNavState()
    d_direct = next_move(s, v, (0, 3), direct=True)
    check("27 direct respects view walls",
          d_direct in ("north", "south"),
          f"got {d_direct}")

    # 28. direct=True ignores stranger-repulsion.
    cfg = GridNavConfig(stranger_repulsion=400.0, stranger_spacing=5)
    s = GridNavState(config=cfg)
    v = GridNavView(obs_center=(0, 0))
    v.stranger_locals.add((0, 1))
    v.visible_tagged_locals.add((0, 1))  # how observe() also classifies
    d_default = next_move(s, v, (0, 3))
    d_direct = next_move(s, v, (0, 3), direct=True)
    check("28 direct ignores soft fields",
          d_direct == "east",
          f"default={d_default} direct={d_direct}")

    # 29. is_bump_target: cell in bump_target_locals.
    v = GridNavView(obs_center=(0, 0))
    v.bump_target_locals.add((1, 0))
    check("29 is_bump_target hit", is_bump_target((1, 0), v))
    check("29b is_bump_target miss", not is_bump_target((2, 2), v))

    # 30. arrived(): exact match always counts.
    s = GridNavState()
    s.position = (3, 3)
    v = GridNavView(obs_center=(0, 0))
    check("30 arrived exact match", arrived(s, (3, 3), v))

    # 31. arrived(): Manhattan=1 from a bump cell counts (env is
    # 4-connected; only orthogonal neighbors can fire the bump on
    # this tick).
    s = GridNavState()
    s.position = (0, 0)
    v = GridNavView(obs_center=(0, 0))
    v.bump_target_locals.add((1, 0))
    check("31 arrived orthogonal-adjacent to bump", arrived(s, (1, 0), v))

    # 31b. arrived(): a diagonal cell (Cheb=1, Manhattan=2) is NOT
    # adjacent for bump purposes — must take one more cardinal step.
    s = GridNavState()
    s.position = (0, 0)
    v = GridNavView(obs_center=(0, 0))
    v.bump_target_locals.add((1, 1))
    check("31b arrived diagonal-to-bump does not count",
          not arrived(s, (1, 1), v))

    # 32. arrived(): Manhattan=1 from non-bump cell does NOT count.
    s = GridNavState()
    s.position = (0, 0)
    v = GridNavView(obs_center=(0, 0))
    check("32 arrived non-bump adjacent does not count",
          not arrived(s, (1, 0), v))

    # 33. arrived(): Manhattan=2 from a bump cell does not count.
    s = GridNavState()
    s.position = (0, 0)
    v = GridNavView(obs_center=(0, 0))
    v.bump_target_locals.add((2, 2))
    check("33 arrived Chebyshev=2 from bump does not count",
          not arrived(s, (2, 2), v))

    # 34. observe() populates bump_target_locals from bump_target_tag_ids.
    HUB_TAG = 100
    cfg = GridNavConfig(bump_target_tag_ids=frozenset({HUB_TAG}))
    s = GridNavState(config=cfg)
    s.position = (0, 0)
    frozen = {(0, 1): frozenset({HUB_TAG})}
    v = observe(s, frozen, obs_center=(0, 0))
    check("34 observe populates bump_target_locals",
          (0, 1) in v.bump_target_locals)
