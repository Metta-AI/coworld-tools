"""Queries over the canonical ``(ts, player, key, value)`` event log.

Every reporter in this repo emits its event log against the same four-column
schema (see ``reporter_sdk/event_log.py``); diagnosers and optimizers consume
it. This module is the query side: an :class:`EventLog` container built from
in-memory rows or the Parquet bytes/file a reporter produced, with the
accessors the chart/stat layers need.

Key names are **conventions, not contract** — the schema fixes columns, not
keys — so every accessor takes the key name as a parameter, defaulting to the
recommended registry (see the package README): ``position`` with an
``{"x", "y"}`` payload, ``reward`` with ``{"delta", "total"}``, ``death``,
and global rows at ``player == -1`` (spans carry ``{"start", "end"}``).

Origin: distilled from Ron Dahlgren's (swgy) crewrift analysis tooling
(``swgy_tools.tasks.eventlog`` / ``spatial.eventlog``), which already parsed
exactly this row shape from a game-specific stream; the game-specific
dataclasses did not port — key-parameterized accessors replaced them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

__all__ = ["EventLog", "EventRow"]


@dataclass(frozen=True)
class EventRow:
    """One decoded event: the four schema columns, value JSON-decoded."""

    ts: int
    player: int
    key: str
    value: Any


class EventLog:
    """An in-memory, ts-ordered view of one episode's event log."""

    def __init__(self, rows: Iterable[EventRow]) -> None:
        self._rows = sorted(rows, key=lambda r: (r.ts, r.player, r.key))

    # --- constructors -------------------------------------------------------

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]]) -> "EventLog":
        """From raw schema rows (``value`` a JSON string, as written)."""
        decoded = []
        for r in rows:
            decoded.append(
                EventRow(
                    ts=int(r["ts"]),
                    player=int(r["player"]),
                    key=str(r["key"]),
                    value=_decode(r["value"]),
                )
            )
        return cls(decoded)

    @classmethod
    def from_parquet(cls, source: bytes | str | Path) -> "EventLog":
        """From canonical event-log Parquet bytes or a file path."""
        import io

        import pyarrow.parquet as pq

        if isinstance(source, bytes):
            table = pq.read_table(io.BytesIO(source))
        else:
            table = pq.read_table(str(source))
        return cls.from_rows(table.to_pylist())

    # --- basics ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[EventRow]:
        return iter(self._rows)

    def to_rows(self) -> list[dict[str, Any]]:
        """Back to raw schema rows (``value`` re-encoded as a JSON string)."""
        return [
            {"ts": r.ts, "player": r.player, "key": r.key, "value": json.dumps(r.value)}
            for r in self._rows
        ]

    @property
    def players(self) -> list[int]:
        """Distinct non-global player slots, ascending."""
        return sorted({r.player for r in self._rows if r.player >= 0})

    @property
    def keys(self) -> list[str]:
        return sorted({r.key for r in self._rows})

    @property
    def max_ts(self) -> int:
        return self._rows[-1].ts if self._rows else 0

    # --- queries ----------------------------------------------------------------

    def filter(self, key: str | None = None, player: int | None = None) -> list[EventRow]:
        return [
            r
            for r in self._rows
            if (key is None or r.key == key) and (player is None or r.player == player)
        ]

    def positions(
        self, player: int | None = None, key: str = "position"
    ) -> list[tuple[int, int, float, float]]:
        """``(ts, player, x, y)`` samples from position-shaped events."""
        out = []
        for r in self.filter(key=key, player=player):
            v = r.value
            if isinstance(v, dict) and "x" in v and "y" in v:
                out.append((r.ts, r.player, float(v["x"]), float(v["y"])))
        return out

    def numeric_series(
        self, key: str, player: int | None = None, field: str | None = None
    ) -> list[tuple[int, float]]:
        """``(ts, value)`` pairs for a numeric event key.

        ``field`` picks a member out of dict payloads (e.g. ``"total"`` from
        a ``reward`` event); scalar payloads are used directly.
        """
        out = []
        for r in self.filter(key=key, player=player):
            v = r.value
            if field is not None:
                if isinstance(v, dict) and isinstance(v.get(field), (int, float)):
                    out.append((r.ts, float(v[field])))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((r.ts, float(v)))
        return out

    def spans(self, key: str) -> list[tuple[int, int]]:
        """``(start, end)`` pairs from global span-shaped events (rows whose
        payload carries ``start``/``end``; falls back to ``(ts, ts)``)."""
        out = []
        for r in self.filter(key=key):
            v = r.value
            if isinstance(v, dict) and "start" in v and "end" in v:
                out.append((int(v["start"]), int(v["end"])))
            else:
                out.append((r.ts, r.ts))
        return out


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value
