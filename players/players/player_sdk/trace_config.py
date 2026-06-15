"""Reusable trace filtering configuration.

This generalizes the filter machinery from ``players/crewrift/crewborg/trace.py``.
Crewborg still owns its event taxonomy and can adopt this base in a later pass.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase

from players.player_sdk.trace import TraceEvent

TraceFilter = Callable[[TraceEvent], bool]


@dataclass(frozen=True, init=False)
class TraceConfig:
    """Environment-derived trace targeting configuration.

    When no targets are selected and the level is not ``debug`` or ``viewer``,
    ``default_filter`` decides what to keep. If no default filter is supplied,
    the neutral default is to allow all events. On an instance, ``groups`` are
    the selected target groups; ``group_patterns`` holds the game's taxonomy.
    """

    env_prefix: str
    group_patterns: Mapping[str, tuple[str, ...]]
    default_filter: TraceFilter | None = None
    low_volume_events: frozenset[str] = frozenset()
    noisy_events: frozenset[str] = frozenset()
    level: str = ""
    groups: frozenset[str] = frozenset()
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        env_prefix: str,
        groups: Mapping[str, tuple[str, ...]],
        default_filter: TraceFilter | None = None,
        low_volume_events: frozenset[str] = frozenset(),
        noisy_events: frozenset[str] = frozenset(),
        level: str = "",
        target_groups: frozenset[str] = frozenset(),
        include_patterns: tuple[str, ...] = (),
        exclude_patterns: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "env_prefix", env_prefix.strip())
        object.__setattr__(self, "group_patterns", _normalize_groups(groups))
        object.__setattr__(self, "default_filter", default_filter)
        object.__setattr__(self, "low_volume_events", _normalize_names(low_volume_events))
        object.__setattr__(self, "noisy_events", _normalize_names(noisy_events))
        object.__setattr__(self, "level", level.strip().lower())
        object.__setattr__(self, "groups", _normalize_names(target_groups))
        object.__setattr__(self, "include_patterns", tuple(pattern.lower() for pattern in include_patterns))
        object.__setattr__(self, "exclude_patterns", tuple(pattern.lower() for pattern in exclude_patterns))

    @classmethod
    def from_env(
        cls,
        *,
        env_prefix: str,
        groups: Mapping[str, tuple[str, ...]],
        default_filter: TraceFilter | None = None,
        low_volume_events: frozenset[str] = frozenset(),
        noisy_events: frozenset[str] = frozenset(),
        env: Mapping[str, str] | None = None,
    ) -> TraceConfig:
        source = os.environ if env is None else env
        return cls(
            env_prefix=env_prefix,
            groups=groups,
            default_filter=default_filter,
            low_volume_events=low_volume_events,
            noisy_events=noisy_events,
            level=source.get(f"{env_prefix}_TRACE", ""),
            target_groups=frozenset(_split_tokens(source.get(f"{env_prefix}_TRACE_GROUPS", ""))),
            include_patterns=_parse_patterns(source.get(f"{env_prefix}_TRACE_INCLUDE", "")),
            exclude_patterns=_parse_patterns(source.get(f"{env_prefix}_TRACE_EXCLUDE", "")),
        )

    @property
    def has_targets(self) -> bool:
        return bool(self.groups or self.include_patterns)

    def allows(self, event: TraceEvent) -> bool:
        name = event.name.lower()
        if self.has_targets:
            allowed = self._matches_group(name) or _matches_any(name, self.include_patterns)
        elif self.level in {"debug", "viewer"}:
            allowed = True
        elif self.default_filter is None:
            allowed = True
        else:
            allowed = self.default_filter(event)
        return allowed and not self.excludes_event(name)

    def targets_event(self, event_name: str) -> bool:
        name = event_name.lower()
        return (self._matches_group(name) or _matches_any(name, self.include_patterns)) and not self.excludes_event(name)

    def excludes_event(self, event_name: str) -> bool:
        return _matches_any(event_name.lower(), self.exclude_patterns)

    def _matches_group(self, event_name: str) -> bool:
        return any(self._group_matches(group, event_name) for group in self.groups)

    def _group_matches(self, group: str, event_name: str) -> bool:
        if group == "lean":
            return event_name in self.low_volume_events or (
                event_name.startswith("domain.") and event_name not in self.noisy_events
            )
        return _matches_any(event_name, self.group_patterns.get(group, ()))


def _normalize_groups(groups: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return {name.lower(): tuple(pattern.lower() for pattern in patterns) for name, patterns in groups.items()}


def _normalize_names(names: frozenset[str]) -> frozenset[str]:
    return frozenset(name.lower() for name in names)


def _matches_any(event_name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(event_name, pattern) for pattern in patterns)


def _parse_patterns(raw: str) -> tuple[str, ...]:
    patterns: list[str] = []
    for token in _split_tokens(raw):
        patterns.append(token)
        if "." not in token:
            patterns.append(f"domain.{token}")
    return tuple(patterns)


def _split_tokens(raw: str) -> tuple[str, ...]:
    return tuple(part for chunk in raw.replace(";", ",").split(",") for part in chunk.lower().split() if part)
