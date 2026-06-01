"""Near-certain suspicion tests: witnessed kill + witnessed vent (design §10.1)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, Vent
from players.crewrift.crewborg.strategy.suspicion import (
    BODY_LINGER_MIN_TICKS,
    FOLLOW_MIN_TICKS,
    VENT_DWELL_MIN_TICKS,
    update_suspicion,
)
from players.crewrift.crewborg.types import Belief, PerceptionFrame, PlayerEvent, PlayerRecord


def _frame(tick: int, players=None, bodies=None, camera=(0, 0), mask=None) -> PerceptionFrame:
    return PerceptionFrame(
        tick=tick, camera_x=camera[0], camera_y=camera[1],
        players=dict(players or {}), bodies=dict(bodies or {}), visible_mask=mask,
    )


def _belief(prev: PerceptionFrame, curr: PerceptionFrame, **kwargs) -> Belief:
    kwargs.setdefault("self_role", "crewmate")
    return Belief(last_tick=curr.tick, recent_frames=[prev, curr], **kwargs)


def _vent_map() -> MapData:
    return MapData(
        width=200, height=200, tasks=(),
        vents=(Vent(x=50, y=50, w=8, h=8, group="g", group_index=1),),  # rect [50,58)x[50,58)
        rooms=(), button=MapRect(x=0, y=0, w=4, h=4), home=MapPoint(x=10, y=10),
    )


# --- witnessed kill ---------------------------------------------------------


def test_lone_neighbor_of_a_just_killed_victim_is_confirmed() -> None:
    prev = _frame(4, players={"red": (100, 100), "green": (110, 100)})  # together, alive
    curr = _frame(5, players={"green": (110, 100)}, bodies={"red": (100, 100)})  # red now a body
    belief = _belief(prev, curr)
    update_suspicion(belief)
    assert "green" in belief.believed_imposters


def test_kill_is_not_attributed_when_two_players_were_in_range() -> None:
    prev = _frame(4, players={"red": (100, 100), "green": (110, 100), "blue": (115, 100)})
    curr = _frame(5, players={"green": (110, 100), "blue": (115, 100)}, bodies={"red": (100, 100)})
    belief = _belief(prev, curr)
    update_suspicion(belief)
    assert not belief.believed_imposters  # ambiguous → no accusation


def test_kill_with_no_visible_neighbor_implicates_no_one() -> None:
    prev = _frame(4, players={"red": (100, 100), "green": (200, 100)})  # green far (>kill range)
    curr = _frame(5, players={"green": (200, 100)}, bodies={"red": (100, 100)})
    belief = _belief(prev, curr)
    update_suspicion(belief)
    assert not belief.believed_imposters


def test_non_consecutive_frames_are_not_read_as_a_kill() -> None:
    prev = _frame(2, players={"red": (100, 100), "green": (110, 100)})  # a meeting-sized gap
    curr = _frame(5, players={"green": (110, 100)}, bodies={"red": (100, 100)})
    belief = _belief(prev, curr)
    update_suspicion(belief)
    assert not belief.believed_imposters


def test_imposter_observer_accrues_no_suspicion() -> None:
    prev = _frame(4, players={"red": (100, 100), "green": (110, 100)})
    curr = _frame(5, players={"green": (110, 100)}, bodies={"red": (100, 100)})
    belief = _belief(prev, curr, self_role="imposter")
    update_suspicion(belief)
    assert not belief.suspicion and not belief.believed_imposters


# --- witnessed vent: emergence (a) ------------------------------------------


def test_player_emerging_into_a_watched_clear_vent_is_confirmed() -> None:
    prev = _frame(4, players={}, camera=(0, 0))  # vent + margin in view, no one near it
    curr = _frame(5, players={"red": (53, 53)}, camera=(0, 0))  # now inside the vent rect
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert "red" in belief.believed_imposters


def test_emergence_requires_the_vent_to_have_been_watched() -> None:
    prev = _frame(4, players={}, camera=(400, 400))  # vent off-screen last frame
    curr = _frame(5, players={"red": (53, 53)}, camera=(0, 0))
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters  # we weren't watching → can't conclude emergence


def test_a_player_near_the_vent_last_frame_blocks_an_emergence_call() -> None:
    prev = _frame(4, players={"red": (48, 53)}, camera=(0, 0))  # within the walk margin of the vent
    curr = _frame(5, players={"red": (53, 53)}, camera=(0, 0))  # could have walked in
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters


# --- witnessed vent: submersion (b) -----------------------------------------


def test_player_vanishing_from_a_visible_vent_is_confirmed() -> None:
    prev = _frame(4, players={"red": (53, 53)}, camera=(0, 0))  # standing in the vent rect
    curr = _frame(5, players={}, camera=(0, 0))  # gone, but the vent is still in view
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert "red" in belief.believed_imposters


def test_submersion_requires_the_vent_to_still_be_in_view() -> None:
    prev = _frame(4, players={"red": (53, 53)}, camera=(0, 0))
    curr = _frame(5, players={}, camera=(400, 400))  # vent off-screen now → maybe just walked off
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters


def test_a_player_standing_on_a_vent_is_not_a_venter() -> None:
    prev = _frame(4, players={"red": (53, 53)}, camera=(0, 0))
    curr = _frame(5, players={"red": (54, 53)}, camera=(0, 0))  # still visible on the vent
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters


# --- line-of-sight gating (the decoded shadow mask) -------------------------


def test_emergence_is_suppressed_when_the_vent_is_occluded() -> None:
    occluded = np.ones((128, 128), dtype=bool)
    occluded[47:61, 47:61] = False  # vent + walk margin out of line of sight
    prev = _frame(4, players={}, camera=(0, 0), mask=occluded)  # "clear" only because occluded
    curr = _frame(5, players={"red": (53, 53)}, camera=(0, 0), mask=np.ones((128, 128), dtype=bool))
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters  # couldn't actually see the vent was clear


def test_emergence_fires_when_the_vent_is_truly_in_sight() -> None:
    lit = np.ones((128, 128), dtype=bool)
    prev = _frame(4, players={}, camera=(0, 0), mask=lit)
    curr = _frame(5, players={"red": (53, 53)}, camera=(0, 0), mask=lit)
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert "red" in belief.believed_imposters


def test_submersion_is_suppressed_when_the_vent_is_occluded_now() -> None:
    prev = _frame(4, players={"red": (53, 53)}, camera=(0, 0), mask=np.ones((128, 128), dtype=bool))
    occluded = np.ones((128, 128), dtype=bool)
    occluded[50:58, 50:58] = False  # the vent is no longer in sight this frame
    curr = _frame(5, players={}, camera=(0, 0), mask=occluded)
    belief = _belief(prev, curr, map=_vent_map())
    update_suspicion(belief)
    assert not belief.believed_imposters  # player gone, but maybe they just walked behind a wall


# --- graded event-log scoring (tier 2) --------------------------------------


def _with_events(color: str, events: list[PlayerEvent], **rec_kwargs) -> Belief:
    belief = Belief(self_role="crewmate", last_tick=200)
    belief.roster[color] = PlayerRecord(color=color, life_status="alive", events=events, **rec_kwargs)
    return belief


def test_one_graded_signal_raises_suspicion_but_does_not_flee() -> None:
    belief = _with_events(
        "red", [PlayerEvent(kind="vent", start_tick=1, end_tick=1 + VENT_DWELL_MIN_TICKS, region_index=0)]
    )
    update_suspicion(belief)
    assert belief.suspicion.get("red", 0.0) > 0  # scored...
    assert "red" not in belief.believed_imposters  # ...but a single soft cue isn't enough


def test_corroborating_graded_signals_cross_the_flee_bar() -> None:
    belief = _with_events(
        "red",
        [
            PlayerEvent(kind="vent", start_tick=1, end_tick=1 + VENT_DWELL_MIN_TICKS, region_index=0),
            PlayerEvent(
                kind="near_body", start_tick=50, end_tick=50 + BODY_LINGER_MIN_TICKS,
                target_color="blue", min_dist=8,
            ),
        ],
    )
    update_suspicion(belief)
    assert "red" in belief.believed_imposters  # two corroborating cues ⇒ flee


def test_brief_or_distant_cues_do_not_score() -> None:
    belief = _with_events(
        "red",
        [
            PlayerEvent(kind="vent", start_tick=1, end_tick=3, region_index=0),  # too brief
            PlayerEvent(kind="near_body", start_tick=10, end_tick=10 + BODY_LINGER_MIN_TICKS,
                        target_color="blue", min_dist=40),  # too far
            PlayerEvent(kind="proximity", start_tick=20, end_tick=24, target_color="green", min_dist=5),  # brief
        ],
    )
    update_suspicion(belief)
    assert "red" not in belief.suspicion


def test_following_a_victim_to_death_scores_only_when_they_died() -> None:
    end = 40 + FOLLOW_MIN_TICKS  # a sustained-enough following interval
    follow = PlayerEvent(kind="proximity", start_tick=40, end_tick=end, target_color="yellow", min_dist=10)
    # Victim alive ⇒ no score.
    alive = _with_events("orange", [follow])
    alive.roster["yellow"] = PlayerRecord(color="yellow", life_status="alive")
    update_suspicion(alive)
    assert "orange" not in alive.suspicion

    # Victim dead, the following ended near when we found the body ⇒ scores.
    dead = _with_events("orange", [follow])
    dead.roster["yellow"] = PlayerRecord(color="yellow", life_status="dead", death_seen_tick=end + 10)
    update_suspicion(dead)
    assert dead.suspicion.get("orange", 0.0) > 0


def test_graded_scoring_ignores_dead_subjects() -> None:
    belief = _with_events(
        "red", [PlayerEvent(kind="vent", start_tick=1, end_tick=1 + VENT_DWELL_MIN_TICKS, region_index=0)]
    )
    belief.roster["red"].life_status = "dead"
    update_suspicion(belief)
    assert "red" not in belief.suspicion


def test_a_confirmation_outweighs_everything_and_flees() -> None:
    belief = _belief(_frame(4, players={}), _frame(5, players={"red": (53, 53)}), map=_vent_map())
    # Mask makes the vent watched+clear last frame (emergence) → confirmed.
    update_suspicion(belief)
    assert "red" in belief.confirmed_imposters and "red" in belief.believed_imposters
    assert belief.suspicion["red"] >= 1000.0


# --- believed-imposters maintenance -----------------------------------------


def test_a_confirmed_imposter_is_cleared_once_dead() -> None:
    prev = _frame(4, players={"red": (53, 53)}, camera=(0, 0))
    curr = _frame(5, players={}, camera=(0, 0))
    belief = _belief(prev, curr, map=_vent_map())
    belief.roster["red"] = PlayerRecord(color="red", life_status="alive")
    update_suspicion(belief)
    assert "red" in belief.believed_imposters

    belief.roster["red"].life_status = "dead"
    update_suspicion(belief)
    assert "red" not in belief.believed_imposters
