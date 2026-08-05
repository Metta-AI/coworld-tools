"""Hand-computed expectations for every contrast axis on the fixture."""

from __future__ import annotations

import math

import pytest

from crewrift_analysis.metrics import AXES, aggregate_contrast, player_game_metrics


@pytest.fixture
def pm(episode):
    return player_game_metrics(episode)


def test_station_occupancy(pm):
    assert pm[0]["station_occupancy"] == 0.0  # the imposter never touched a station
    assert pm[3]["station_occupancy"] == pytest.approx(21 / 190)  # ticks 60..120 of 190
    assert pm[4]["station_occupancy"] == 0.0  # ghost-working never counts
    assert pm[1]["station_occupancy"] == 0.0


def test_vote_accuracy(pm):
    assert pm[1]["vote_accuracy"] == 1.0
    assert pm[2]["vote_accuracy"] == 1.0  # skip votes are not in the denominator
    assert pm[3]["vote_accuracy"] == 1.0
    assert pm[0]["vote_accuracy"] == 0.0
    assert math.isnan(pm[4]["vote_accuracy"])  # dead before any meeting


def test_vote_order(pm):
    assert pm[1]["vote_order"] == 0.0  # first in both meetings
    assert pm[0]["vote_order"] == pytest.approx(2 / 3)  # ranks 1/3 then 3/3
    assert pm[2]["vote_order"] == pytest.approx(0.5)  # ranks 2/3 then 1/3
    assert pm[3]["vote_order"] == pytest.approx(5 / 6)  # ranks 3/3 then 2/3
    assert math.isnan(pm[4]["vote_order"])


def test_meetings_called(pm):
    assert pm[1]["meetings_called"] == 1.0  # reported the body
    assert pm[2]["meetings_called"] == 1.0  # pressed the button
    assert pm[0]["meetings_called"] == 0.0
    assert pm[4]["meetings_called"] == 0.0


def test_distance(pm):
    # Slot s advances (s+1) px per sample over 188 playing-and-alive pairs;
    # slot 0 additionally pays 4 y-jumps of 107 px moving to/from the
    # station row; slot 4's 73 pairs stop at the murder.
    assert pm[1]["distance"] == pytest.approx(376.0)
    assert pm[2]["distance"] == pytest.approx(564.0)
    assert pm[3]["distance"] == pytest.approx(752.0)
    assert pm[4]["distance"] == pytest.approx(365.0)
    assert pm[0]["distance"] == pytest.approx(184.0 + 4 * math.hypot(1, 107))


def test_chat_axes(pm):
    assert pm[1]["chars_per_message"] == len("I saw red near navigation")
    assert pm[0]["chars_per_message"] == len("it was blue")
    assert math.isnan(pm[2]["chars_per_message"])
    assert pm[1]["messages_sent"] == 1.0
    assert pm[2]["messages_sent"] == 0.0
    assert pm[1]["names_per_message"] == 1.0  # "red" names another player
    assert pm[0]["names_per_message"] == 1.0  # "blue"
    assert math.isnan(pm[3]["names_per_message"])


def test_speak_to_vote_lead(pm):
    assert pm[1]["speak_to_vote_lead"] == pytest.approx(8.0)  # chat 322, vote 330
    assert pm[0]["speak_to_vote_lead"] == pytest.approx(45.0)  # chat 710, vote 755
    assert math.isnan(pm[2]["speak_to_vote_lead"])  # never spoke


def test_skip_share(pm):
    assert pm[2]["skip_share"] == 0.5
    assert pm[3]["skip_share"] == 0.5
    assert pm[0]["skip_share"] == 0.0
    assert pm[1]["skip_share"] == 0.0
    assert math.isnan(pm[4]["skip_share"])


def test_visibility_axes(pm):
    assert pm[0]["ticks_visible"] == 41.0
    assert pm[1]["ticks_visible"] == 31.0
    assert pm[2]["ticks_visible"] == 41.0
    assert pm[3]["ticks_visible"] == 61.0
    assert pm[4]["ticks_visible"] == 0.0  # the body sighting is not a player sighting
    assert pm[0]["distinct_observers"] == 1.0
    assert pm[4]["distinct_observers"] == 0.0


def test_no_task_completion_axis_exists():
    keys = {ax.key for ax in AXES}
    assert len(AXES) == 12
    assert not any("task" in k or "assign" in k for k in keys)
    assert "station_occupancy" in keys  # the behavioral stand-in


def test_aggregate_contrast(episode):
    contrasts = aggregate_contrast([episode, episode])
    assert [c.key for c in contrasts] == [ax.key for ax in AXES]
    by_key = {c.key: c for c in contrasts}

    occ = by_key["station_occupancy"]
    assert (occ.n_imposter, occ.n_crew) == (2, 8)
    assert occ.imposter_mean == 0.0
    assert occ.crew_mean == pytest.approx(2 * (21 / 190) / 8)
    assert occ.auc < 0.5  # imposters lower: the amber row points at crew

    acc = by_key["vote_accuracy"]
    assert (acc.n_imposter, acc.n_crew) == (2, 6)  # slot 4 NaN dropped
    assert acc.auc == 0.0 and acc.separation == 1.0

    for c in contrasts:
        assert math.isnan(c.separation) or 0.0 <= c.separation <= 1.0
