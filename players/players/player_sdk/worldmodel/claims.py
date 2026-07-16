"""claims.py — TTL'd advisory claims for multi-agent target coordination.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries. This is the
unification of three claim implementations that coexisted in the original
sm-policies stack — ``swgy_memory.ClaimBook`` (the base shape),
``mas_memory.TargetClaims`` (per-call TTL override, ``clear``), and the
``dedicated_runtime.SharedRuntime`` claim methods (motivation only).

Use case: when agents share a memory object (e.g. a policy-level blackboard),
one agent claims a target so teammates pick something else. Claims are
*advisory* — an agent that ignores a claim still executes; the claim just
causes well-behaved teammates to look elsewhere.

Claims auto-expire after ``ttl`` ticks if not renewed. Without TTL, a stuck
or dead agent would lock a resource forever. Renewal is implicit: re-calling
:meth:`ClaimBook.claim` on the same key pushes the expiry forward.

Semantics note (differs from one absorbed source): expiry is computed **at
write time** (``expires_at = step + ttl``), matching ``swgy_memory``/
``mas_memory``. The ``dedicated_runtime`` variant stored the claim step and
compared TTL at read, so changing the TTL knob retroactively re-aged old
claims; that behavior is intentionally not preserved.

Keys are any :class:`~typing.Hashable` — a cell coordinate, a POI id, a
``(cell, role)`` pair, etc.

Coexistence with ``worldmodel.select.make_unclaimed_filter``: that is the
visible-symmetric (no-comms) flavor — both agents reach the same answer
purely from observation, no shared state. ``ClaimBook`` is the published
flavor — agents write claims to a shared book that others read. A single
policy can use both: ``ClaimBook`` for own-team coordination via shared
memory, ``make_unclaimed_filter`` to infer enemy intent from observation.
"""

from __future__ import annotations

from typing import Hashable

__all__ = ["ClaimBook"]


class ClaimBook:
    """TTL'd claims for explicit-comm coordination. See module docstring."""

    __slots__ = ("_claims", "_default_ttl")

    def __init__(self, default_ttl: int = 25) -> None:
        # key -> (agent_id, expires_at_step)
        self._claims: dict[Hashable, tuple[int, int]] = {}
        self._default_ttl = default_ttl

    def claim(
        self, agent_id: int, key: Hashable, step: int, ttl: int | None = None
    ) -> None:
        """Record (or renew) a claim. Expires at ``step + ttl`` (the book's
        ``default_ttl`` when ``ttl`` is None)."""
        ttl = self._default_ttl if ttl is None else ttl
        self._claims[key] = (agent_id, step + ttl)

    def claim_owner(self, key: Hashable, step: int) -> int | None:
        """Return the agent_id that owns ``key``, or None if unclaimed /
        expired. Side-effect: drops expired entries on access."""
        entry = self._claims.get(key)
        if entry is None:
            return None
        owner, expires = entry
        if expires < step:
            del self._claims[key]
            return None
        return owner

    def is_claimed_by_other(self, agent_id: int, key: Hashable, step: int) -> bool:
        owner = self.claim_owner(key, step)
        return owner is not None and owner != agent_id

    def release(self, agent_id: int, key: Hashable) -> bool:
        """Release ``key`` only if ``agent_id`` is its current owner.

        Returns whether a release actually happened. Standard hook for an
        agent that abandoned a target this tick — the key becomes immediately
        available to teammates instead of waiting on TTL.
        """
        entry = self._claims.get(key)
        if entry is None or entry[0] != agent_id:
            return False
        del self._claims[key]
        return True

    def release_all(self, agent_id: int) -> None:
        """Drop every claim held by ``agent_id``. Use on death or role change
        so successors don't inherit stale locks."""
        self._claims = {
            key: entry for key, entry in self._claims.items() if entry[0] != agent_id
        }

    def claims_held_by(self, agent_id: int) -> list[Hashable]:
        return [key for key, entry in self._claims.items() if entry[0] == agent_id]

    def cleanup_expired(self, step: int) -> None:
        """Garbage-collect expired claims. Call periodically; a fully idle
        policy never calls ``claim_owner``, so without this, expired entries
        would leak indefinitely."""
        self._claims = {
            key: entry for key, entry in self._claims.items() if entry[1] >= step
        }

    def clear(self) -> None:
        """Drop every claim (e.g. on episode reset)."""
        self._claims.clear()

    def __len__(self) -> int:
        return len(self._claims)
