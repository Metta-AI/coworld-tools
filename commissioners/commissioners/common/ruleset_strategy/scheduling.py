from __future__ import annotations

import random
import time
from collections import defaultdict
from math import ceil
from typing import Any

from openskill.models import PlackettLuce

from commissioners.common.models import PolicyPool, PolicyPoolEntry, PoolConfig
from commissioners.common.protocol import EpisodeRequest as CommissionerEpisodeRequest
from commissioners.common.protocol import ScheduleEpisodes as CommissionerScheduleEpisodes
from commissioners.common.utils import (
    _build_entry_indices,
    _build_rolling_window_entry_indices,
    _build_sliding_window_entry_indices,
    _entry_index_offset,
    _pool_episode_count,
)
from commissioners.common.ruleset_strategy.config import (
    AdaptiveScheduleConfig,
    RulesetStrategyCommissionerConfig,
)
from commissioners.common.ruleset_strategy.uncertainty import entrant_uncertainties, episode_budget


def _two_team_round_robin_pair(job_index: int, *, num_entries: int) -> tuple[int, int]:
    """Circle-method round-robin pairing for two-team episodes.

    Episodes are scheduled in cycles of num_entries//2 pairs; each cycle every entrant
    plays exactly once, except that an odd field adds a bye slot to the ring and the
    entrant drawn against it sits the cycle out. Entry 0 stays fixed while the rest of
    the ring rotates one step per cycle, so consecutive cycles pair every entrant against
    a different opponent (the standard round-robin tournament schedule).
    """
    ring_size = num_entries + (num_entries % 2)  # odd fields get a bye slot
    pairs_per_cycle = num_entries // 2  # the bye pair is not an episode
    cycle, pair_index = divmod(job_index, pairs_per_cycle)
    ring = [0] + [1 + (i + cycle) % (ring_size - 1) for i in range(ring_size - 1)]
    pairs = [(ring[i], ring[ring_size - 1 - i]) for i in range(ring_size // 2)]
    real_pairs = [pair for pair in pairs if pair[0] < num_entries and pair[1] < num_entries]
    return real_pairs[pair_index]


def _two_team_episode_count(*, num_entries: int, pool_config: PoolConfig) -> int:
    """Episode count that honors min_episodes_per_entrant under the bye schedule.

    An odd field sits each entrant out once every num_entries cycles, so the generic
    entrant-appearances/episode arithmetic undercounts: schedule enough whole cycles that
    even the entrant with the most byes reaches min_episodes_per_entrant appearances.
    """
    min_episodes = pool_config.min_episodes_per_entrant or 1
    if num_entries % 2 == 0:
        return max(pool_config.num_episodes, ceil(num_entries * min_episodes / 2))
    cycles = min_episodes
    while cycles - ceil(cycles / num_entries) < min_episodes:
        cycles += 1
    return max(pool_config.num_episodes, cycles * (num_entries // 2))


def _leaderboard_leader(
    entries: list[PolicyPoolEntry],
    recent_results: list[Any],
) -> PolicyPoolEntry | None:
    """The division's current unique leaderboard leader among the entrants.

    Approximates the platform's EWMA board from the recent results the protocol
    provides: the unique best mean round score. Returns None when no entrant
    has a result yet or the top mean score is shared, so a cold or tied board
    decorates nobody rather than someone arbitrary.
    """
    scores: dict[Any, list[float]] = defaultdict(list)
    entry_ids = {entry.policy_version_id for entry in entries}
    for result in recent_results:
        if result.policy_version_id in entry_ids:
            scores[result.policy_version_id].append(result.score)
    if not scores:
        return None
    means = {policy_id: sum(s) / len(s) for policy_id, s in scores.items()}
    top = max(means.values())
    leaders = [policy_id for policy_id, mean in means.items() if mean == top]
    if len(leaders) != 1:
        return None
    return next(entry for entry in entries if entry.policy_version_id == leaders[0])


def _decorate_leader_slots(
    episodes: list[CommissionerEpisodeRequest],
    *,
    leader: PolicyPoolEntry | None,
    base_game_config: dict[str, Any],
    slot_config: dict[str, Any],
) -> list[CommissionerEpisodeRequest]:
    """Merges leader_slot_config into the leader's slots[] of each episode it plays.

    Episodes seat policies by slot index (policy_version_ids[i] plays slot i), so
    the leader's seats are exactly the indices holding its policy version. The
    episode gets a deep-ish copy of the effective game config with those slots[]
    entries extended; existing per-slot keys (team, color, token) are preserved
    and slots[] grows to num_agents if the base config declares fewer entries.
    Episodes without the leader keep their original game_config untouched.
    """
    if leader is None:
        return episodes
    decorated: list[CommissionerEpisodeRequest] = []
    for episode in episodes:
        seat_indices = [
            index
            for index, policy_version_id in enumerate(episode.policy_version_ids)
            if policy_version_id == leader.policy_version_id
        ]
        if not seat_indices:
            decorated.append(episode)
            continue
        game_config = dict(base_game_config)
        slots = [dict(slot) for slot in game_config.get("slots") or []]
        while len(slots) < len(episode.policy_version_ids):
            slots.append({})
        for index in seat_indices:
            slots[index] = slots[index] | slot_config
        game_config["slots"] = slots
        decorated.append(episode.model_copy(update={"game_config": game_config}))
    return decorated


def schedule_entries(
    *,
    pool: PolicyPool,
    primary_entries: list[PolicyPoolEntry],
    filler_entries: list[PolicyPoolEntry],
    num_agents: int,
    variant_id: str,
    game_config: dict[str, Any] | None,
    config: RulesetStrategyCommissionerConfig,
    recent_results: list[Any] | None = None,
    division_id: Any = None,
) -> CommissionerScheduleEpisodes:
    if not primary_entries:
        raise ValueError("pool must have at least one primary entry")
    pool_config = PoolConfig.model_validate(pool.config)
    if pool_config.self_play:
        episodes_per_entrant = pool_config.min_episodes_per_entrant or pool_config.num_episodes
        return CommissionerScheduleEpisodes(
            episodes=[
                CommissionerEpisodeRequest(
                    request_id=str(entry_index * episodes_per_entrant + episode_index),
                    variant_id=variant_id,
                    game_config=game_config,
                    policy_version_ids=[entry.policy_version_id] * num_agents,
                    tags={"pool_id": str(pool.id)},
                )
                for entry_index, entry in enumerate(primary_entries)
                for episode_index in range(episodes_per_entrant)
            ]
        )

    if config.seating in ("team_blocks", "team_interleaved"):
        team_count = config.defaults.team_count
        if len(primary_entries) < team_count:
            raise ValueError(f"{config.seating} seating requires at least {team_count} primary entries")
        if num_agents % team_count != 0:
            raise ValueError(f"{config.seating} seating requires num_agents divisible by {team_count}")

        team_size = num_agents // team_count
        seat_entries = primary_entries
        adaptive_pairs: list[tuple[int, int]] | None = None
        if team_count == 2 and len(primary_entries) >= 2:
            adaptive = config.defaults.adaptive
            if adaptive.enabled and recent_results is not None:
                # Uncertainty-weighted budgets: settled entrants play the stage floor,
                # new/moving entrants play up to the stage ceiling. Entries are shuffled
                # per scheduling (wall-clock seed, like shuffled_window) so ring coverage
                # precesses across rounds instead of replaying cycle 0 forever.
                seat_entries = _round_shuffled_entries(primary_entries)
                adaptive_pairs = _adaptive_two_team_pairs(
                    seat_entries,
                    recent_results=_division_results(recent_results, division_id),
                    pool_config=pool_config,
                    adaptive=adaptive,
                )
                num_episodes = len(adaptive_pairs)
            else:
                num_episodes = _two_team_episode_count(
                    num_entries=len(primary_entries),
                    pool_config=pool_config,
                )
        else:
            num_episodes = _pool_episode_count(
                config=pool_config,
                num_entries=len(primary_entries),
                num_agents=team_count,
            )
        episodes: list[CommissionerEpisodeRequest] = []
        for job_index in range(num_episodes):
            if adaptive_pairs is not None:
                entry_indices = list(adaptive_pairs[job_index])
            elif team_count == 2 and len(primary_entries) >= 2:
                # Circle-method round-robin: the stride schedule below degenerates to a FIXED
                # pairing for two-team fields — an even field locks every entrant to a single
                # opponent all round, an odd field to its two ring neighbors — so a pocket of
                # mutually-drawing policies never meets the rest of the field. Rotate the
                # ring each cycle so every entrant faces a different opponent per cycle.
                entry_indices = list(
                    _two_team_round_robin_pair(job_index, num_entries=len(primary_entries))
                )
            else:
                entry_indices = [
                    (job_index * team_count + team_index) % len(primary_entries) for team_index in range(team_count)
                ]
            rotation = job_index % team_count
            entry_indices = entry_indices[rotation:] + entry_indices[:rotation]
            if config.seating == "team_blocks":
                # One contiguous block of seats per team: [A]*size + [B]*size + ...
                seat_entry_indices = [entry_index for entry_index in entry_indices for _slot in range(team_size)]
            else:
                # Interleaved team seats for games that assign teams by slot parity
                # (slot mod team_count), e.g. CTF: [A, B, A, B, ...].
                seat_entry_indices = [entry_index for _slot in range(team_size) for entry_index in entry_indices]
            episodes.append(
                CommissionerEpisodeRequest(
                    request_id=str(job_index),
                    variant_id=variant_id,
                    game_config=game_config,
                    policy_version_ids=[
                        seat_entries[entry_index].policy_version_id for entry_index in seat_entry_indices
                    ],
                    tags={"pool_id": str(pool.id)},
                )
            )
        return CommissionerScheduleEpisodes(episodes=episodes)

    if config.seating == "leaderboard_neighbors":
        return _schedule_leaderboard_neighbors(
            pool=pool,
            pool_config=pool_config,
            primary_entries=primary_entries,
            filler_entries=filler_entries,
            num_agents=num_agents,
            variant_id=variant_id,
            game_config=game_config,
            recent_results=recent_results or [],
        )

    if config.seating == "shuffled_window":
        # baseline_window / rolling_window seat a fixed-width window of CONSECUTIVE entries in a
        # seed order that is stable across rounds, so two entries co-occur only when their circular
        # distance is below num_agents -- distant entries never share an episode no matter how many
        # rounds run (a banded matchup graph, not a round-robin). shuffled_window permutes the entry
        # order each time a round is scheduled so the band precesses and full pairwise coverage
        # accrues across rounds (the granularity the EWMA leaderboard aggregates at) while preserving
        # balanced per-entrant appearances. The permutation is seeded from the wall clock, not from
        # any round/pool id, so a re-scheduled round never reuses its previous order.
        primary_entries = _round_shuffled_entries(primary_entries)

    if config.seating == "mmr_neighbors":
        # Order entries by current skill (OpenSkill mu, replayed from recent results) and then
        # rolling-window seat below, so each episode is a cohort of num_agents skill-neighbours --
        # close, informative matches whose outcome actually moves ratings, instead of uniformly
        # random cohorts. The overlapping windows keep the whole field connected (a skill chain) so
        # the MMR ranker can still order across it; a small wall-clock jitter breaks near-ties so
        # cohorts vary round to round and unrated policies (all at the default mu -- e.g. a cold
        # start with no results yet) are seated randomly among themselves.
        primary_entries = _mmr_ordered_entries(primary_entries, recent_results or [])

    num_episodes = _pool_episode_count(
        config=pool_config,
        num_entries=len(primary_entries),
        num_agents=num_agents,
    )
    return CommissionerScheduleEpisodes(
        episodes=[
            CommissionerEpisodeRequest(
                request_id=str(job_index),
                variant_id=variant_id,
                game_config=game_config,
                policy_version_ids=[
                    entry.policy_version_id
                    for entry in episode_entries(
                        job_index,
                        primary_entries=primary_entries,
                        filler_entries=filler_entries,
                        num_agents=num_agents,
                        config=config,
                    )
                ],
                tags={"pool_id": str(pool.id)},
            )
            for job_index in range(num_episodes)
        ]
    )


def _division_results(recent_results: list[Any], division_id: Any) -> list[Any]:
    """Restrict history to the scheduled division when the caller identifies one.

    The platform's recent_results are league-wide; qualifier crash-check rounds
    (self-play, near-guaranteed wins) would otherwise count as settling evidence
    for a brand-new champion.
    """
    if division_id is None:
        return recent_results
    return [
        result
        for result in recent_results
        if getattr(result, "division_id", division_id) == division_id
    ]


def _adaptive_two_team_pairs(
    entries: list[PolicyPoolEntry],
    *,
    recent_results: list[Any],
    pool_config: PoolConfig,
    adaptive: AdaptiveScheduleConfig,
) -> list[tuple[int, int]]:
    """Budget-filtered circle round-robin for two-team episodes.

    Every entrant gets an episode budget between the stage floor and ceiling based on
    its score uncertainty, then circle-method cycles run until every budget is met,
    keeping only pairs where at least one side still needs episodes. Movers stay in
    nearly every cycle and face ~the whole field (their round win rate stays an
    unbiased estimate with more samples); settled entrants play their floor plus
    incidental episodes when a mover's cycle drafts them, which the rotating ring
    spreads evenly. Both sides of every episode are scored as usual.
    """
    num_entries = len(entries)
    min_episodes = pool_config.min_episodes_per_entrant or 1
    max_episodes = max(pool_config.max_episodes_per_entrant or min_episodes, min_episodes)
    uncertainties = entrant_uncertainties(
        [entry.policy_version_id for entry in entries],
        recent_results,
        adaptive,
        fallback_episodes_per_round=min_episodes,
    )
    budgets = [
        episode_budget(
            uncertainties[entry.policy_version_id].value,
            min_episodes=min_episodes,
            max_episodes=max_episodes,
        )
        for entry in entries
    ]

    remaining = list(budgets)
    pairs: list[tuple[int, int]] = []
    pairs_per_cycle = num_entries // 2
    # Bye slack: an odd field sits each entrant out once per ring rotation, so a few
    # extra cycles may be needed beyond the largest budget. Fixed bound => terminates.
    max_cycles = 2 * max_episodes + 2
    for cycle in range(max_cycles):
        if not any(remaining):
            break
        for pair_index in range(pairs_per_cycle):
            first, second = _two_team_round_robin_pair(
                cycle * pairs_per_cycle + pair_index,
                num_entries=num_entries,
            )
            if remaining[first] > 0 or remaining[second] > 0:
                pairs.append((first, second))
                remaining[first] = max(0, remaining[first] - 1)
                remaining[second] = max(0, remaining[second] - 1)
    if adaptive.max_round_episodes is not None:
        pairs = pairs[: adaptive.max_round_episodes]

    appearances = [0] * num_entries
    for first, second in pairs:
        appearances[first] += 1
        appearances[second] += 1
    for entry, budget, played in zip(entries, budgets, appearances, strict=True):
        parts = uncertainties[entry.policy_version_id]
        print(
            f"adaptive_schedule: policy {entry.policy_version_id} budget={budget} episodes={played} "
            f"u={parts.value:.2f} (new={parts.newness:.2f} vol={parts.volatility:.2f} "
            f"trend={parts.trend:.2f}, {parts.rounds_on_record} rounds on record)"
        )
    print(
        f"adaptive_schedule: {num_entries} entrants, {len(pairs)} episodes "
        f"(floor={min_episodes} ceiling={max_episodes})"
    )
    return pairs


def episode_entries(
    job_index: int,
    *,
    primary_entries: list[PolicyPoolEntry],
    filler_entries: list[PolicyPoolEntry],
    num_agents: int,
    config: RulesetStrategyCommissionerConfig,
) -> list[PolicyPoolEntry]:
    if len(primary_entries) >= num_agents:
        if config.seating == "baseline_window":
            indices = _build_entry_indices(
                num_entries=len(primary_entries),
                num_agents=num_agents,
                offset=_entry_index_offset(
                    job_index=job_index,
                    num_entries=len(primary_entries),
                    num_agents=num_agents,
                ),
            )
        elif config.seating == "mmr_neighbors":
            # Non-wrapping sliding window over the (skill-ordered) entries: cohorts are
            # skill-neighbours and the top never wraps around to face the bottom. Adjacent windows
            # overlap by num_agents-1, so the field stays a single connected chain.
            indices = _build_sliding_window_entry_indices(
                job_index=job_index,
                num_entries=len(primary_entries),
                num_agents=num_agents,
            )
        else:
            indices = _build_rolling_window_entry_indices(
                job_index=job_index,
                num_entries=len(primary_entries),
                num_agents=num_agents,
            )
        return [primary_entries[index] for index in indices]

    seats = list(primary_entries)
    if config.insufficient_players.strategy == "strict":
        raise ValueError(f"not enough primary entries to fill {num_agents} seats")
    if config.insufficient_players.strategy == "fill_from_divisions":
        seats.extend(cycled(filler_entries, num_agents - len(seats), offset=job_index))
    if len(seats) < num_agents and config.insufficient_players.duplicate_after_fill:
        seats.extend(cycled(seats or primary_entries, num_agents - len(seats), offset=job_index))
    if len(seats) < num_agents:
        raise ValueError(f"not enough entries to fill {num_agents} seats")
    return seats[:num_agents]


def cycled(entries: list[PolicyPoolEntry], count: int, *, offset: int = 0) -> list[PolicyPoolEntry]:
    if count <= 0 or not entries:
        return []
    return [entries[(offset + index) % len(entries)] for index in range(count)]


def _round_shuffle_seed() -> int:
    # Wall-clock seed so each scheduling draws a fresh, never-reused permutation (a round id would be
    # reused if the same round were re-scheduled). Isolated in a function so tests can pin it.
    return time.time_ns()


def _round_shuffled_entries(entries: list[PolicyPoolEntry]) -> list[PolicyPoolEntry]:
    shuffled = list(entries)
    random.Random(_round_shuffle_seed()).shuffle(shuffled)
    return shuffled


def _rate_mu_from_recent(recent_results: list[Any]) -> dict[Any, float]:
    """Replay recent round results through OpenSkill and return each policy's current mu.

    Each round is one free-for-all match (policies ordered by finishing rank), replayed oldest-first
    by round number. Mirrors the MMR ranker, but here we only need the mean skill estimate (mu) to
    seat skill-neighbours, so the conservative ordinal and player priors are not applied.
    """
    by_round: dict[Any, list[Any]] = defaultdict(list)
    round_number: dict[Any, Any] = {}
    for result in recent_results:
        round_id = result.round_id
        by_round[round_id].append(result)
        round_number[round_id] = getattr(result, "round_number", 0)

    model = PlackettLuce()
    ratings: dict[Any, Any] = {}
    for round_id in sorted(by_round, key=lambda r: round_number[r]):
        results = by_round[round_id]
        if len(results) < 2:
            continue  # a one-policy round is not a match
        for result in results:
            if result.policy_version_id not in ratings:
                ratings[result.policy_version_id] = model.rating()
        ordered = sorted(results, key=lambda r: r.rank)
        rated = model.rate(
            [[ratings[r.policy_version_id]] for r in ordered],
            ranks=[r.rank for r in ordered],
        )
        for result, team in zip(ordered, rated, strict=True):
            ratings[result.policy_version_id] = team[0]
    return {policy_version_id: rating.mu for policy_version_id, rating in ratings.items()}


def _mmr_ordered_entries(entries: list[PolicyPoolEntry], recent_results: list[Any]) -> list[PolicyPoolEntry]:
    mu_by_policy = _rate_mu_from_recent(recent_results)
    base = PlackettLuce().rating()
    # Wall-clock jitter (~a quarter of the default sigma) breaks near-ties so cohorts vary round to
    # round and unrated policies (all at the default mu) don't form a fixed block, without overriding
    # real skill gaps. Unrated policies sort at the default mu (mid-field) until they earn results.
    rng = random.Random(_round_shuffle_seed())
    jitter_scale = base.sigma * 0.25

    def sort_key(entry: PolicyPoolEntry) -> float:
        mu = mu_by_policy.get(entry.policy_version_id, base.mu)
        return -(mu + rng.gauss(0.0, jitter_scale))

    return sorted(entries, key=sort_key)


def _schedule_leaderboard_neighbors(
    *,
    pool: PolicyPool,
    pool_config: PoolConfig,
    primary_entries: list[PolicyPoolEntry],
    filler_entries: list[PolicyPoolEntry],
    num_agents: int,
    variant_id: str,
    game_config: dict[str, Any] | None,
    recent_results: list[Any],
) -> CommissionerScheduleEpisodes:
    if num_agents != 2:
        raise ValueError("leaderboard_neighbors seating requires a two-player variant")

    episodes_per_entrant = pool_config.min_episodes_per_entrant or pool_config.num_episodes
    ordered_primary_entries = _leaderboard_ordered_entries(primary_entries, recent_results)
    opponent_entries = _dedupe_entries([*ordered_primary_entries, *filler_entries])
    if len(opponent_entries) < 2:
        return CommissionerScheduleEpisodes(episodes=[])

    episodes: list[CommissionerEpisodeRequest] = []
    for anchor_index, anchor in enumerate(ordered_primary_entries):
        ordered_opponents = [entry for entry in opponent_entries if entry.policy_version_id != anchor.policy_version_id]
        if not ordered_opponents:
            continue
        if opponent_entries == ordered_primary_entries:
            neighbors = _leaderboard_neighbors(
                ordered_primary_entries,
                anchor_index,
                episodes_per_entrant,
            )
        else:
            neighbors = _repeat_to_count(ordered_opponents, episodes_per_entrant)
        for opponent in neighbors:
            episodes.append(
                CommissionerEpisodeRequest(
                    request_id=str(len(episodes)),
                    variant_id=variant_id,
                    game_config=game_config,
                    policy_version_ids=[anchor.policy_version_id, opponent.policy_version_id],
                    tags={"pool_id": str(pool.id)},
                )
            )
    return CommissionerScheduleEpisodes(episodes=episodes)


def _leaderboard_ordered_entries(
    entries: list[PolicyPoolEntry],
    recent_results: list[Any],
) -> list[PolicyPoolEntry]:
    entries = _dedupe_entries(entries)
    entry_index = {entry.policy_version_id: index for index, entry in enumerate(entries)}
    scores: dict[Any, list[float]] = {entry.policy_version_id: [] for entry in entries}
    ranks: dict[Any, list[float]] = {entry.policy_version_id: [] for entry in entries}

    for result in recent_results:
        policy_version_id = getattr(result, "policy_version_id", None)
        if policy_version_id not in entry_index:
            continue
        scores[policy_version_id].append(float(getattr(result, "score")))
        ranks[policy_version_id].append(float(getattr(result, "rank")))

    def sort_key(entry: PolicyPoolEntry) -> tuple[int, float, float, int]:
        policy_scores = scores[entry.policy_version_id]
        if not policy_scores:
            return (1, 0.0, float("inf"), entry_index[entry.policy_version_id])
        mean_score = sum(policy_scores) / len(policy_scores)
        mean_rank = sum(ranks[entry.policy_version_id]) / max(1, len(ranks[entry.policy_version_id]))
        return (0, -mean_score, mean_rank, entry_index[entry.policy_version_id])

    return sorted(entries, key=sort_key)


def _leaderboard_neighbors(
    ordered_entries: list[PolicyPoolEntry],
    anchor_index: int,
    count: int,
) -> list[PolicyPoolEntry]:
    max_unique = len(ordered_entries) - 1
    if count <= 0 or max_unique <= 0:
        return []

    below_target = (count + 1) // 2
    above_target = count // 2
    selected: list[PolicyPoolEntry] = []
    selected.extend(_below(ordered_entries, anchor_index, start=1, count=below_target))
    selected.extend(_above(ordered_entries, anchor_index, start=1, count=above_target))

    if len(selected) < min(count, max_unique):
        selected.extend(_below(ordered_entries, anchor_index, start=below_target + 1, count=count))
    if len(selected) < min(count, max_unique):
        selected.extend(_above(ordered_entries, anchor_index, start=above_target + 1, count=count))

    return _repeat_to_count(_dedupe_entries(selected), count)


def _below(
    ordered_entries: list[PolicyPoolEntry],
    anchor_index: int,
    *,
    start: int,
    count: int,
) -> list[PolicyPoolEntry]:
    if count <= 0:
        return []
    first = anchor_index + start
    return ordered_entries[first : first + count]


def _above(
    ordered_entries: list[PolicyPoolEntry],
    anchor_index: int,
    *,
    start: int,
    count: int,
) -> list[PolicyPoolEntry]:
    if count <= 0:
        return []
    first = anchor_index - start
    last = max(-1, first - count)
    return [ordered_entries[index] for index in range(first, last, -1) if index >= 0]


def _repeat_to_count(entries: list[PolicyPoolEntry], count: int) -> list[PolicyPoolEntry]:
    if count <= 0 or not entries:
        return []
    return [entries[index % len(entries)] for index in range(count)]


def _dedupe_entries(entries: list[PolicyPoolEntry]) -> list[PolicyPoolEntry]:
    seen: set[Any] = set()
    deduped: list[PolicyPoolEntry] = []
    for entry in entries:
        if entry.policy_version_id in seen:
            continue
        seen.add(entry.policy_version_id)
        deduped.append(entry)
    return deduped
