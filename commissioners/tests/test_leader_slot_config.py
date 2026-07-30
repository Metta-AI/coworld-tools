"""leader_slot_config: decorating the board leader's seats (e.g. the CTF crown skin)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import yaml

from commissioners.common.commissioners import RulesetStrategyCommissioner
from commissioners.common.protocol import (
    DivisionInfo,
    LeagueInfo,
    MembershipInfo,
    RecentResult,
    RoundStart,
    VariantInfo,
)

CONFIG_DIR = (
    Path(__file__).parents[1]
    / "commissioners"
    / "ruleset_strategy_commissioner"
    / "configs"
)

NUM_AGENTS = 16


def _ctf_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "ctf.yaml").read_text())


def _ctf_game_config() -> dict:
    # The CTF variant shape: parity-teamed slots with per-slot tokens.
    return {
        "num_agents": NUM_AGENTS,
        "slots": [
            {"team": "red" if index % 2 == 0 else "blue", "token": f"tok_{index}"}
            for index in range(NUM_AGENTS)
        ],
    }


def _round_start(
    *,
    policy_version_ids: list[UUID],
    recent_results: list[RecentResult] | None = None,
    division_id: UUID | None = None,
    game_config: dict | None = None,
) -> RoundStart:
    active_division_id = division_id or uuid4()
    league_id = uuid4()
    return RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(id=league_id, commissioner_config={}),
        divisions=[
            DivisionInfo(
                id=active_division_id, name="Competition", level=1, type="competition"
            )
        ],
        memberships=[
            MembershipInfo(
                id=uuid4(),
                league_id=league_id,
                division_id=active_division_id,
                policy_version_id=policy_version_id,
                player_id=f"player-{index}",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(policy_version_ids)
        ],
        recent_results=recent_results or [],
        variants=[
            VariantInfo(
                id="default",
                name="Default",
                game_config=game_config or _ctf_game_config(),
            )
        ],
        state=None,
    )


def _results(
    policy_scores: dict[UUID, list[float]],
    *,
    division_id: UUID,
) -> list[RecentResult]:
    rounds: dict[int, UUID] = {}
    results: list[RecentResult] = []
    for policy_version_id, scores in policy_scores.items():
        for round_number, score in enumerate(scores):
            round_id = rounds.setdefault(round_number, uuid4())
            results.append(
                RecentResult(
                    round_id=round_id,
                    division_id=division_id,
                    round_number=round_number,
                    policy_version_id=policy_version_id,
                    rank=1,
                    score=score,
                )
            )
    return results


def _decorated_seats(episode, key: str = "skin") -> list[int]:
    slots = (episode.game_config or {}).get("slots") or []
    return [index for index, slot in enumerate(slots) if key in slot]


def _leader_seats(episode, leader: UUID) -> list[int]:
    return [
        index
        for index, policy_version_id in enumerate(episode.policy_version_ids)
        if policy_version_id == leader
    ]


def test_leader_seats_get_the_crown_and_only_those() -> None:
    division_id = uuid4()
    leader, chaser = uuid4(), uuid4()
    round_start = _round_start(
        policy_version_ids=[leader, chaser],
        division_id=division_id,
        recent_results=_results(
            {leader: [0.9, 0.8], chaser: [0.2, 0.3]}, division_id=division_id
        ),
    )
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    assert schedule.episodes
    for episode in schedule.episodes:
        leader_seats = _leader_seats(episode, leader)
        assert _decorated_seats(episode) == leader_seats
        if leader_seats:
            slots = episode.game_config["slots"]
            for index in leader_seats:
                assert slots[index]["skin"] == "crown"
                # Existing per-slot keys survive the merge.
                assert slots[index]["token"] == f"tok_{index}"
                assert slots[index]["team"] in ("red", "blue")


def test_no_history_crowns_nobody() -> None:
    round_start = _round_start(policy_version_ids=[uuid4(), uuid4()])
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    assert schedule.episodes
    for episode in schedule.episodes:
        assert _decorated_seats(episode) == []


def test_tied_top_score_crowns_nobody() -> None:
    division_id = uuid4()
    first, second = uuid4(), uuid4()
    round_start = _round_start(
        policy_version_ids=[first, second],
        division_id=division_id,
        recent_results=_results(
            {first: [0.5, 0.5], second: [0.5, 0.5]}, division_id=division_id
        ),
    )
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    for episode in schedule.episodes:
        assert _decorated_seats(episode) == []


def test_other_division_results_do_not_crown() -> None:
    # Qualifier (self-play) wins land in recent_results league-wide; leader
    # standing must come from the scheduled division's slice only.
    division_id = uuid4()
    entrant, other = uuid4(), uuid4()
    round_start = _round_start(
        policy_version_ids=[entrant, other],
        division_id=division_id,
        recent_results=_results({entrant: [1.0]}, division_id=uuid4()),
    )
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    for episode in schedule.episodes:
        assert _decorated_seats(episode) == []


def test_config_without_leader_slot_config_is_untouched() -> None:
    division_id = uuid4()
    leader, chaser = uuid4(), uuid4()
    config = _ctf_config()
    del config["defaults"]["leader_slot_config"]
    round_start = _round_start(
        policy_version_ids=[leader, chaser],
        division_id=division_id,
        recent_results=_results(
            {leader: [0.9], chaser: [0.1]}, division_id=division_id
        ),
    )
    schedule = RulesetStrategyCommissioner(config).schedule_episodes_for_round_start(round_start)
    assert schedule.episodes
    for episode in schedule.episodes:
        assert episode.game_config is None
        assert _decorated_seats(episode) == []


def test_leader_episode_game_config_materializes_variant_config() -> None:
    # Undecorated episodes ride the variant config via game_config=None; a
    # decorated episode must carry the FULL variant config plus the skin, not
    # a config containing only slots.
    division_id = uuid4()
    leader, chaser = uuid4(), uuid4()
    round_start = _round_start(
        policy_version_ids=[leader, chaser],
        division_id=division_id,
        recent_results=_results(
            {leader: [0.9], chaser: [0.1]}, division_id=division_id
        ),
    )
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    crowned = [e for e in schedule.episodes if _decorated_seats(e)]
    assert crowned
    for episode in crowned:
        assert episode.game_config["num_agents"] == NUM_AGENTS
        assert len(episode.game_config["slots"]) == NUM_AGENTS


def test_short_variant_slots_grow_to_num_agents() -> None:
    division_id = uuid4()
    leader, chaser = uuid4(), uuid4()
    game_config = {"num_agents": NUM_AGENTS, "slots": [{"team": "red"}]}
    round_start = _round_start(
        policy_version_ids=[leader, chaser],
        division_id=division_id,
        game_config=game_config,
        recent_results=_results(
            {leader: [0.9], chaser: [0.1]}, division_id=division_id
        ),
    )
    schedule = RulesetStrategyCommissioner(_ctf_config()).schedule_episodes_for_round_start(round_start)
    crowned = [e for e in schedule.episodes if _decorated_seats(e)]
    assert crowned
    for episode in crowned:
        slots = episode.game_config["slots"]
        assert len(slots) == NUM_AGENTS
        assert slots[0]["team"] == "red"  # the declared entry survives


def test_leader_crown_preserves_mixed_mode_game_config() -> None:
    """The crown must decorate ON TOP of a mode overlay, not replace it.

    Paintbot 4ffa episodes carry {teams: 4, mapPath: gen}; rebuilding the
    leader's episode config from the pre-mode base would silently revert
    the crowned player's 4ffa games to the 2-team shape.
    """
    division_id = uuid4()
    entrants = [uuid4() for _ in range(4)]
    leader = entrants[0]
    round_start = _round_start(
        policy_version_ids=entrants,
        division_id=division_id,
        recent_results=_results(
            {
                entrants[0]: [0.9, 0.9],
                entrants[1]: [0.4, 0.3],
                entrants[2]: [0.3, 0.2],
                entrants[3]: [0.2, 0.1],
            },
            division_id=division_id,
        ),
    )
    config = yaml.safe_load((CONFIG_DIR / "ctf_doubles.yaml").read_text())
    schedule = RulesetStrategyCommissioner(config).schedule_episodes_for_round_start(round_start)
    assert schedule.episodes
    saw_leader_ffa = False
    for episode in schedule.episodes:
        game_config = episode.game_config or {}
        mode = episode.tags.get("mode")
        assert game_config.get("mapPath") == "gen"
        assert game_config.get("teams") == (4 if mode == "4ffa" else 2)
        leader_seats = _leader_seats(episode, leader)
        assert _decorated_seats(episode) == leader_seats
        if leader_seats and mode == "4ffa":
            saw_leader_ffa = True
    # A 4-entrant field seats the leader in every episode, half of them 4ffa.
    assert saw_leader_ffa
