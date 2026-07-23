"""Tests for the expand_replay JSONL adapter."""

from __future__ import annotations

import json

import pytest

from crewrift_analysis.events import CrewriftLogError, Kill, load_episode, parse_episode
from crewrift_analysis.testing import synthetic_lines


def test_roster(episode):
    assert len(episode.players) == 5
    assert episode.imposters == [0]
    assert episode.crew == [1, 2, 3, 4]
    p0 = episode.players[0]
    assert (p0.role, p0.color, p0.label, p0.address) == ("imposter", "red", "red(0)", "policy-0")
    assert p0.assigned_tasks == ()
    assert episode.players[3].assigned_tasks == (1, 2, 3, 4)


def test_geometry_and_metadata(episode):
    assert (episode.map_w, episode.map_h) == (1235, 659)
    assert len(episode.tasks) == 41
    assert episode.tasks[0] == (17, 407)
    assert len(episode.vents) == 11
    assert episode.config["imposter_count"] == 1
    assert episode.snapshot_stride == 3
    assert episode.end_tick == 800


def test_playing_spans_and_meetings(episode):
    assert episode.playing_spans == [(30, 300), (400, 700)]
    assert len(episode.meetings) == 2
    m0, m1 = episode.meetings
    assert (m0.start, m0.end, m0.kind, m0.caller, m0.body_owner) == (300, 400, "body", 1, 4)
    assert (m1.start, m1.end, m1.kind, m1.caller, m1.body_owner) == (700, 800, "button", 2, -1)


def test_votes(episode):
    assert len(episode.votes) == 8
    skips = [v for v in episode.votes if v.target is None]
    assert [(v.tick, v.voter) for v in skips] == [(350, 2), (745, 3)]
    assert all(isinstance(v.target, int) for v in episode.votes if v.target is not None)
    assert all(v.meeting == 0 for v in episode.votes if v.tick <= 400)
    assert all(v.meeting == 1 for v in episode.votes if v.tick >= 700)


def test_deaths_mix_murder_and_ejection(episode):
    assert episode.deaths == {4: 250, 0: 780}
    assert episode.alive_at(4, 249) and not episode.alive_at(4, 251)
    assert episode.alive_at(1, 800)


def test_kills_join_body_state(episode):
    assert episode.kills == [Kill(tick=250, killer=0, victim=4, x=610, y=300, room="hall")]


def test_tracks_masks(episode):
    t0 = episode.tracks[0]
    assert t0.playing.sum() == 190  # 90 samples in span 1 + 100 in span 2
    assert t0.playing_alive().sum() == 190  # ejection happens outside Playing
    t4 = episode.tracks[4]
    assert t4.playing.sum() == 190  # ghosts keep sampling...
    assert t4.playing_alive().sum() == 74  # ...but alive ends at tick 250
    assert t4.window(30, 39).sum() == 4  # 30, 33, 36, 39


def test_sightings_split_by_kind(episode):
    assert [s.ticks() for s in episode.sightings_of(0)] == [41]
    assert episode.sightings_of(4) == []
    assert [s.ticks() for s in episode.sightings_of(4, kind="body")] == [7]


def test_load_episode_uses_stem(tmp_path, lines):
    path = tmp_path / "ep42.jsonl"
    path.write_text("\n".join(lines))
    assert load_episode(path).episode_id == "ep42"


def test_stride_falls_back_to_sample_spacing(lines):
    without_meta = [ln for ln in lines if '"episode_metadata"' not in ln]
    assert parse_episode(without_meta, episode_id="x").snapshot_stride == 3


def test_missing_snapshots_raise(lines):
    no_state = [ln for ln in lines if '"player_state"' not in ln]
    with pytest.raises(CrewriftLogError, match="--snapshot-every"):
        parse_episode(no_state, episode_id="x")
    no_geometry = [ln for ln in lines if '"map_geometry"' not in ln]
    with pytest.raises(CrewriftLogError, match="--snapshot-every"):
        parse_episode(no_geometry, episode_id="x")


def test_missing_manifest_raises(lines):
    no_manifest = [ln for ln in lines if '"player_manifest"' not in ln]
    with pytest.raises(CrewriftLogError, match="player_manifest"):
        parse_episode(no_manifest, episode_id="x")


def test_malformed_line_names_the_line(lines):
    broken = [*lines[:3], "{not json", *lines[3:]]
    with pytest.raises(CrewriftLogError, match="line 4"):
        parse_episode(broken, episode_id="x")


def test_skip_without_target_field_is_skip():
    # Defensive: a vote_cast with neither target nor target_slot reads as skip.
    base = [ln for ln in synthetic_lines()]
    base.append(json.dumps({"ts": 331, "player": 4, "key": "vote_cast", "value": {"actor_role": "crew"}}))
    ep = parse_episode(base, episode_id="x")
    ghost_vote = [v for v in ep.votes if v.voter == 4]
    assert len(ghost_vote) == 1 and ghost_vote[0].target is None
