"""The vote ladder: who voted for whom, per meeting, on role-shaded lanes.

Maps one episode onto ``episode_analysis.charts.ladder``. Lanes and arrows
are colored by **true role** (the figure knows ground truth; that is its
point), with imposters pinned to the top. Player identity lives in the lane
labels, not the colors — red-the-role and red-the-player would collide.

Arrival-order numerals at the arrow tails answer "in what order": the
numeral is the ballot's position among all of that meeting's votes,
including skips, so a late accusation reads as late even when earlier
voters skipped.
"""

from __future__ import annotations

from episode_analysis.charts import LadderActor, LadderArrow, LadderPanel, render_lane_ladder

from ..events import Episode
from ..palette import ROLE_COLORS

__all__ = ["ladder_inputs", "render_vote_ladder"]


def ladder_inputs(ep: Episode) -> tuple[list[LadderActor], list[LadderPanel], str]:
    """Actors (imposters first), one panel per meeting, and the payoff
    footnote. Raises ``ValueError`` when the episode has no meetings."""
    if not ep.meetings:
        raise ValueError(f"{ep.episode_id}: episode has no meetings, nothing to ladder")

    order = ep.imposters + ep.crew
    lane = {slot: i for i, slot in enumerate(order)}
    actors = [
        LadderActor(label=ep.players[s].label, color=ROLE_COLORS.get(ep.players[s].role, ROLE_COLORS["crew"]))
        for s in order
    ]

    panels = []
    for m in ep.meetings:
        cast = sorted((v for v in ep.votes if v.meeting == m.index), key=lambda v: (v.tick, v.voter))
        vote_tick = {v.voter: v.tick for v in cast}
        panels.append(
            LadderPanel(
                title=f"meeting {m.index + 1}" + (f" ({m.kind})" if m.kind else ""),
                arrows=tuple(
                    LadderArrow(lane[v.voter], lane[v.target], str(i + 1))
                    for i, v in enumerate(cast)
                    if v.target is not None and v.target in lane
                ),
                skips=tuple(lane[v.voter] for v in cast if v.target is None),
                marked=tuple(
                    lane[s]
                    for s in order
                    if any(
                        m.start <= c.tick <= vote_tick.get(s, m.end)
                        for c in ep.chats
                        if c.speaker == s
                    )
                ),
                inactive=tuple(lane[s] for s in order if not ep.alive_at(s, m.start)),
            )
        )

    imposter_votes = [
        v for v in ep.votes if ep.players[v.voter].role == "imposter" and v.target is not None
    ]
    on_imposter = sum(
        v.target in ep.players and ep.players[v.target].role == "imposter" for v in imposter_votes
    )
    footnote = (
        "lanes and arrows colored by true role (red imposter, blue crew); "
        f"{on_imposter} of {len(imposter_votes)} imposter votes landed on an imposter."
    )
    return actors, panels, footnote


def render_vote_ladder(ep: Episode, *, title: str | None = None, wrap: int = 6) -> bytes:
    """Render the episode's vote ladder to PNG bytes."""
    actors, panels, footnote = ladder_inputs(ep)
    return render_lane_ladder(
        actors,
        panels,
        title=title or f"vote ladder, {ep.episode_id}",
        skip_label="skipped",
        marker_label="spoke before voting",
        wrap=wrap,
        footnote=footnote,
    )
