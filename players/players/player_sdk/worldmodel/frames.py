"""frames.py — coordinate-frame anchoring for comms-free team coordination.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
``mas_memory.HubAnchor`` and the frame-conversion methods of
``dedicated_runtime.SharedRuntime``).

The problem: in many limited-information grid games each agent's spawn is
its own ``(0, 0)`` and the engine never shares global coordinates. For any
cross-agent memory (shared maps, POIs, claims) the team needs a **shared
frame** every agent can translate into. The trick both original stacks used:
anchor on a *landmark* — a fixed world object every agent eventually sees
(a hub, a base, a beacon). Cells expressed relative to the landmark are a
frame any two anchored agents agree on.

Two flavors:

* :class:`FrameAnchor` — per-agent, lazy, observation-driven. The agent
  records the landmark's position in its own frame on first sighting;
  first sighting wins. Unanchored agents simply don't contribute to or
  query shared state, so a policy degrades gracefully to per-agent behavior
  at startup.
* :class:`TeamFrame` — team-wide offset registry for games where the
  spawn→landmark offsets are known (or guessable) up front. The caller
  injects a bootstrap ``{agent_id: offset}`` map; each agent can later
  *verify* its offset against an actual landmark sighting and
  :meth:`~TeamFrame.reanchor` if the bootstrap guess was wrong. Wrong
  offsets are never silently kept.
"""

from __future__ import annotations

from typing import Callable, Mapping

Coordinate = tuple[int, int]

__all__ = ["Coordinate", "FrameAnchor", "TeamFrame"]


class FrameAnchor:
    """Lazily resolves an agent's own-frame -> shared-frame translation.

    Shared frame = coordinates relative to the anchor landmark (landmark at
    ``(0, 0)``).
    """

    __slots__ = ("_landmark_in_own_frame",)

    def __init__(self) -> None:
        self._landmark_in_own_frame: Coordinate | None = None

    @property
    def is_anchored(self) -> bool:
        return self._landmark_in_own_frame is not None

    @property
    def landmark_own_frame(self) -> Coordinate | None:
        return self._landmark_in_own_frame

    def try_anchor(self, landmark_in_own_frame: Coordinate) -> None:
        """Record the landmark's position in our own frame.

        First sighting wins. If a later sighting disagrees (e.g. multiple
        identical landmarks on the map), we keep the original anchor so
        previously written shared-memory entries stay valid.
        """
        if self._landmark_in_own_frame is None:
            self._landmark_in_own_frame = landmark_in_own_frame

    def to_shared(self, own_frame: Coordinate) -> Coordinate | None:
        if self._landmark_in_own_frame is None:
            return None
        return (
            own_frame[0] - self._landmark_in_own_frame[0],
            own_frame[1] - self._landmark_in_own_frame[1],
        )

    def to_local(self, shared: Coordinate) -> Coordinate | None:
        if self._landmark_in_own_frame is None:
            return None
        return (
            shared[0] + self._landmark_in_own_frame[0],
            shared[1] + self._landmark_in_own_frame[1],
        )


class TeamFrame:
    """Team-wide additive-offset registry: ``local + offset = shared``.

    ``bootstrap`` supplies the initial per-agent offsets (from spawn-layout
    knowledge, mission config, or an educated guess); agents missing from it
    default to ``(0, 0)``. On its first landmark sighting an agent should
    call :meth:`reanchor` with the landmark's spawn-relative local coord —
    if the observed offset disagrees with the bootstrap, the override wins
    and ``on_reanchor`` (if provided) is notified; either way the agent is
    marked verified.
    """

    def __init__(
        self,
        bootstrap: Mapping[int, Coordinate] | None = None,
        on_reanchor: Callable[[int, Coordinate, Coordinate], None] | None = None,
    ) -> None:
        self._bootstrap: dict[int, Coordinate] = dict(bootstrap or {})
        self._override: dict[int, Coordinate] = {}
        self._verified: dict[int, bool] = {}
        self._on_reanchor = on_reanchor

    def offset_for(self, agent_id: int) -> Coordinate:
        """The additive offset for ``agent_id`` (local + offset = shared)."""
        if agent_id in self._override:
            return self._override[agent_id]
        return self._bootstrap.get(agent_id, (0, 0))

    def to_shared(self, agent_id: int, local: Coordinate) -> Coordinate:
        off = self.offset_for(agent_id)
        return (local[0] + off[0], local[1] + off[1])

    def from_shared(self, agent_id: int, shared: Coordinate) -> Coordinate:
        off = self.offset_for(agent_id)
        return (shared[0] - off[0], shared[1] - off[1])

    def landmark_local_for(self, agent_id: int) -> Coordinate:
        """The landmark's coord in agent N's spawn-anchored local frame.

        The landmark is at shared ``(0, 0)``, so its local-frame coord for
        agent N is ``-offset_for(N)``.
        """
        off = self.offset_for(agent_id)
        return (-off[0], -off[1])

    def is_verified(self, agent_id: int) -> bool:
        return self._verified.get(agent_id, False)

    def reanchor(self, agent_id: int, observed_landmark_local: Coordinate) -> None:
        """Verify (and if needed override) one agent's offset from an actual
        landmark sighting.

        ``observed_landmark_local`` is the landmark's *spawn-relative* coord
        in the agent's local frame, i.e. ``observation_offset +
        agent_local_position``. If it disagrees with the current offset, the
        derived offset replaces it — we never silently carry on with a wrong
        frame.
        """
        new_offset = (-observed_landmark_local[0], -observed_landmark_local[1])
        old_offset = self.offset_for(agent_id)
        if new_offset != old_offset:
            self._override[agent_id] = new_offset
            if self._on_reanchor is not None:
                self._on_reanchor(agent_id, old_offset, new_offset)
        self._verified[agent_id] = True
