"""Opt-in world bookkeeping for limited-information multi-agent play.

Building blocks a team policy composes into a shared blackboard:

- :mod:`.frames` — own-frame ⇄ shared-frame anchoring (:class:`FrameAnchor`
  per-agent lazy, :class:`TeamFrame` team-wide offsets with verification).
- :mod:`.mapping` — :func:`is_stale`, :class:`WorldMap` (monotonic tag-union
  map + walls), :class:`Poi`/:class:`PoiMap` (kind-generic POI registry with
  a kind-transition hook).
- :mod:`.claims` — :class:`ClaimBook`, TTL'd advisory target claims.
- :mod:`.census` — :class:`TeamCensus`, roster + liveness-by-report.
- :mod:`.intents` — :class:`AgentIntent`/:class:`IntentBoard`, goal
  advertisements for team rebalancing.
- :mod:`.targets` — sticky per-agent target with progress-based
  invalidation.
- :mod:`.select` — filter-relaxation candidate selection +
  :func:`make_unclaimed_filter` (comms-free claim inference).
- :mod:`.vitals` — retreat / top-up threshold decisions.
- :mod:`.emergency` — dual-threshold resource-pivot decisions.

Everything is stdlib-only and engine-free: coordinates are ``(row, col)``
tuples, tags are opaque int ids, kinds/roles/goals are caller vocabulary.

This subpackage is not re-exported from ``players.player_sdk`` — import it
explicitly. Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack: ``swgy_memory``, ``mas_memory``,
``dedicated_runtime`` bookkeeping, ``swgy_targets``, ``swgy_select``,
``swgy_vitals``, ``swgy_emergency``).
"""

from .census import TeamCensus
from .claims import ClaimBook
from .emergency import EmergencyConfig, pick_threshold, should_pivot, worst_deficient_resource
from .frames import FrameAnchor, TeamFrame
from .intents import AgentIntent, IntentBoard
from .mapping import Coordinate, Poi, PoiMap, WorldMap, is_stale
from .select import make_unclaimed_filter, select_with_relaxation, tiered_select_with_relaxation
from .targets import TargetConfig, TargetState, check_arrival, clear_target, set_target, update_target_progress
from .vitals import VitalsConfig, hp_deficit, is_topped_up, should_retreat

__all__ = [
    "AgentIntent",
    "ClaimBook",
    "Coordinate",
    "EmergencyConfig",
    "FrameAnchor",
    "IntentBoard",
    "Poi",
    "PoiMap",
    "TargetConfig",
    "TargetState",
    "TeamCensus",
    "TeamFrame",
    "VitalsConfig",
    "WorldMap",
    "check_arrival",
    "clear_target",
    "hp_deficit",
    "is_stale",
    "is_topped_up",
    "make_unclaimed_filter",
    "pick_threshold",
    "select_with_relaxation",
    "set_target",
    "should_pivot",
    "should_retreat",
    "tiered_select_with_relaxation",
    "update_target_progress",
    "worst_deficient_resource",
]
