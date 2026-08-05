"""The imposter/crew contrast axes: one scalar per player-game.

Every behavioral statistic runs over ``playing & alive`` samples: ghosts
keep moving (through walls) and completing tasks, and meetings teleport
everyone to the Bridge, so an unmasked metric measures the engine, not the
policy. Distance additionally refuses to sum across sample gaps wider than
the snapshot stride, so a teleport or dropout can never fabricate travel.

There is deliberately **no task-completion or task-assignment axis**: the
engine assigns imposters zero tasks, so those axes separate perfectly by
construction and say nothing about behavior. Station occupancy is the
legitimate version of the same idea; nothing stops an imposter from
standing at a station.

NaN marks "undefined for this player-game" (never voted, never spoke...);
:func:`aggregate_contrast` drops NaN per side before the rank AUC.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from episode_analysis.stats import rank_auc

from .events import Episode

__all__ = ["AXES", "AxisContrast", "AxisSpec", "aggregate_contrast", "player_game_metrics"]

NAN = float("nan")


@dataclass(frozen=True)
class AxisSpec:
    key: str
    label: str
    fmt: str  # per-axis number format for the contrast table
    fn: Callable[[Episode, int], float]


@dataclass(frozen=True)
class AxisContrast:
    """One aggregated axis: group means plus rank-AUC separation, with
    imposters as the group of interest (``auc > 0.5`` = imposter higher)."""

    key: str
    label: str
    fmt: str
    crew_mean: float
    imposter_mean: float
    auc: float
    separation: float
    n_crew: int
    n_imposter: int


def _own_votes(ep: Episode, slot: int):
    return [v for v in ep.votes if v.voter == slot]


def _own_chats(ep: Episode, slot: int):
    return [c for c in ep.chats if c.speaker == slot]


def _player_sightings(ep: Episode, slot: int):
    return ep.sightings_of(slot, kind="player")


def station_occupancy(ep: Episode, slot: int) -> float:
    track = ep.tracks.get(slot)
    if track is None:
        return NAN
    mask = track.playing_alive()
    if not mask.any():
        return NAN
    return float((track.active_task[mask] >= 0).mean())


def vote_accuracy(ep: Episode, slot: int) -> float:
    real = [v for v in _own_votes(ep, slot) if v.target is not None]
    if not real:
        return NAN
    hits = sum(ep.players[v.target].role == "imposter" for v in real if v.target in ep.players)
    return hits / len(real)


def vote_order(ep: Episode, slot: int) -> float:
    ranks = []
    for m in ep.meetings:
        cast = sorted(
            (v for v in ep.votes if v.meeting == m.index), key=lambda v: (v.tick, v.voter)
        )
        for rank, v in enumerate(cast):
            if v.voter == slot:
                ranks.append(rank / (len(cast) - 1) if len(cast) > 1 else 0.5)
                break
    return float(np.mean(ranks)) if ranks else NAN


def meetings_called(ep: Episode, slot: int) -> float:
    return float(sum(m.caller == slot for m in ep.meetings))


def distance(ep: Episode, slot: int) -> float:
    track = ep.tracks.get(slot)
    if track is None or track.ticks.size < 2:
        return NAN
    mask = track.playing_alive()
    ok = mask[:-1] & mask[1:] & (np.diff(track.ticks) <= ep.snapshot_stride)
    return float(np.hypot(np.diff(track.x), np.diff(track.y))[ok].sum())


def chars_per_message(ep: Episode, slot: int) -> float:
    chats = _own_chats(ep, slot)
    return float(np.mean([len(c.text) for c in chats])) if chats else NAN


def speak_to_vote_lead(ep: Episode, slot: int) -> float:
    """Signed ticks from each chat to the own vote nearest in time (positive
    = spoke before voting), averaged over the player's chats."""
    chats = _own_chats(ep, slot)
    votes = _own_votes(ep, slot)
    if not chats or not votes:
        return NAN
    leads = [min((v.tick - c.tick for v in votes), key=abs) for c in chats]
    return float(np.mean(leads))


def names_per_message(ep: Episode, slot: int) -> float:
    chats = _own_chats(ep, slot)
    if not chats:
        return NAN
    others = [p.color for s, p in ep.players.items() if s != slot and p.color]
    if not others:
        return 0.0
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, others)) + r")\b", re.IGNORECASE)
    return float(np.mean([len(pattern.findall(c.text)) for c in chats]))


def messages_sent(ep: Episode, slot: int) -> float:
    return float(len(_own_chats(ep, slot)))


def skip_share(ep: Episode, slot: int) -> float:
    votes = _own_votes(ep, slot)
    if not votes:
        return NAN
    return sum(v.target is None for v in votes) / len(votes)


def ticks_visible(ep: Episode, slot: int) -> float:
    return float(sum(s.ticks() for s in _player_sightings(ep, slot)))


def distinct_observers(ep: Episode, slot: int) -> float:
    return float(len({s.observer for s in _player_sightings(ep, slot)}))


AXES: tuple[AxisSpec, ...] = (
    AxisSpec("station_occupancy", "station occupancy", "{:.1%}", station_occupancy),
    AxisSpec("vote_accuracy", "vote accuracy", "{:.0%}", vote_accuracy),
    AxisSpec("vote_order", "vote arrival order", "{:.2f}", vote_order),
    AxisSpec("meetings_called", "meetings called", "{:.1f}", meetings_called),
    AxisSpec("distance", "distance travelled", "{:.0f}", distance),
    AxisSpec("chars_per_message", "characters per message", "{:.0f}", chars_per_message),
    AxisSpec("speak_to_vote_lead", "speak-to-vote lead", "{:.0f}", speak_to_vote_lead),
    AxisSpec("names_per_message", "players named per message", "{:.2f}", names_per_message),
    AxisSpec("messages_sent", "messages sent", "{:.1f}", messages_sent),
    AxisSpec("skip_share", "skip share", "{:.0%}", skip_share),
    AxisSpec("ticks_visible", "ticks visible", "{:.0f}", ticks_visible),
    AxisSpec("distinct_observers", "distinct observers", "{:.1f}", distinct_observers),
)


def player_game_metrics(ep: Episode) -> dict[int, dict[str, float]]:
    """All axes for every seated player in one episode."""
    return {slot: {ax.key: ax.fn(ep, slot) for ax in AXES} for slot in ep.players}


def aggregate_contrast(episodes: Iterable[Episode]) -> list[AxisContrast]:
    """Pool player-games across episodes and rank-AUC each axis, imposters
    as the group of interest. Returns the axes in registry order (the chart
    sorts by separation itself)."""
    crew_vals: dict[str, list[float]] = {ax.key: [] for ax in AXES}
    imp_vals: dict[str, list[float]] = {ax.key: [] for ax in AXES}
    for ep in episodes:
        for slot, vals in player_game_metrics(ep).items():
            side = imp_vals if ep.players[slot].role == "imposter" else crew_vals
            for key, value in vals.items():
                side[key].append(value)

    out = []
    for ax in AXES:
        crew = [v for v in crew_vals[ax.key] if math.isfinite(v)]
        imp = [v for v in imp_vals[ax.key] if math.isfinite(v)]
        if crew and imp:
            auc, separation = rank_auc(imp, crew)
        else:
            auc = separation = NAN
        out.append(
            AxisContrast(
                key=ax.key,
                label=ax.label,
                fmt=ax.fmt,
                crew_mean=float(np.mean(crew)) if crew else NAN,
                imposter_mean=float(np.mean(imp)) if imp else NAN,
                auc=auc,
                separation=separation,
                n_crew=len(crew),
                n_imposter=len(imp),
            )
        )
    return out
