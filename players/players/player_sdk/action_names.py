"""action_names.py — action-name fallback dispatch.

An env's action vocabulary varies across missions and even across mission
variants (a tutorial mission and a tournament variant of the same base game
can ship a subset or a permutation of action names). Policies should deal
in action *names*, not numeric action ids — numeric ids are
environment-specific and can change with the mission config.

The standard fix everyone independently rediscovers: look up by name, fall
back to noop on miss. :class:`ActionTable` packages that pattern, keeps the
action-name vocabulary once at init time, and exposes O(1) helpers that
always produce a safe action name.

This module is name-only by design (no engine imports — see
``validation/players-tests/test_sdk_core_grid_free.py``). Engine adapters
are one-liners at the call site::

    # MettaGrid / cogames:
    from mettagrid.simulator import Action
    action = Action(name=table.move_name_or_noop(direction))

    # coworld.player.v1 JSON protocol:
    reply = {"type": "action", "action_name": table.name_or_noop(name)}

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
scripted stack; original module name ``swgy_action.py``, whose
``Action``-returning convenience methods were dropped in favor of the
compositions above).
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["ActionTable"]


class ActionTable:
    """Resolve env action names with safe noop fallback.

    Built once per session from the env's ``action_names`` list. The
    set-build cost happens in ``__init__``; per-tick lookups are O(1).

    If the env doesn't ship a ``noop`` action either, ``noop_name`` falls
    back to the first registered action name so the policy can still
    produce a well-formed action even on extremely degenerate
    vocabularies. ``name_for`` raises in that case so callers can detect
    the mismatch explicitly when they care.
    """

    __slots__ = ("_action_names", "_name_set", "_noop_name")

    def __init__(self, action_names: Sequence[str]):
        self._action_names = tuple(action_names)
        self._name_set = set(self._action_names)
        if "noop" in self._name_set:
            self._noop_name = "noop"
        elif action_names:
            # Degenerate fallback: first registered action. Better than
            # failing initialization in runtimes that suppress the
            # underlying exception details.
            self._noop_name = action_names[0]
        else:
            self._noop_name = "noop"

    @property
    def noop_name(self) -> str:
        return self._noop_name

    def has(self, name: str) -> bool:
        return name in self._name_set

    def name_for(self, name: str) -> str:
        """Strict lookup. Raises ``KeyError`` if ``name`` is unknown."""
        if name not in self._name_set:
            raise KeyError(name)
        return name

    def name_or_noop(self, name: str) -> str:
        """Workhorse: action name by name, ``noop_name`` on miss."""
        return name if name in self._name_set else self._noop_name

    def move_name_or_noop(self, direction: str) -> str:
        """Convenience: ``name_or_noop(f"move_{direction}")``."""
        return self.name_or_noop(f"move_{direction}")

    def name_at_index_or_noop(self, action_idx: int) -> str:
        """Map a model-selected index through env action names.

        Numeric ids are not stable across mission configs; this method
        treats the integer only as an index into the env's current
        ``action_names`` list, then returns the corresponding name or the
        noop fallback.
        """
        if 0 <= action_idx < len(self._action_names):
            return self._action_names[action_idx]
        return self._noop_name
