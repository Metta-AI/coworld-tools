# player_sdk.worldmodel — bookkeeping for limited-information play

Stdlib-only, engine-free building blocks for the hard part of partial
observability: **remembering the world, agreeing on a frame, and not
stepping on your teammates.** Opt-in: not re-exported from
`players.player_sdk` — import explicitly.

## The composition story

A team policy typically holds ONE shared blackboard object containing:

```python
from players.player_sdk import worldmodel as wm

class Blackboard:
    def __init__(self, roster: dict[int, str]):
        self.frame = wm.TeamFrame(bootstrap=...)   # or per-agent wm.FrameAnchor
        self.map = wm.WorldMap()                   # monotonic tag-union map
        self.pois = wm.PoiMap(on_kind_change=...)  # remembered objectives
        self.claims = wm.ClaimBook(default_ttl=25) # advisory target locks
        self.census = wm.TeamCensus(roster)        # who's alive, by role
        self.intents = wm.IntentBoard()            # who's doing what
```

Each agent, each tick: converts local↔shared via the frame
(`frame.to_shared(agent_id, cell)`), records observations into
`map`/`pois`, reports `census.report_alive(...)`, publishes an intent, and
picks targets with `select.select_with_relaxation(...)` filtered by
`claims.is_claimed_by_other(...)`.

## Modules

| Module | Provides | Origin |
|--------|----------|--------|
| `frames` | `FrameAnchor` (per-agent, lazy, first-sighting-wins landmark anchoring), `TeamFrame` (team-wide offsets: injectable bootstrap, `reanchor` verification, `on_reanchor` hook) | `mas_memory.HubAnchor`, `dedicated_runtime.SharedRuntime` frame methods |
| `mapping` | `is_stale` (free-function staleness), `WorldMap` (monotonic tag union + walls), `Poi[K]`/`PoiMap[K]` (kind-generic POI registry; kind transitions surface via `on_kind_change` hook) | `swgy_memory`, `mas_memory.SharedWorldMap`, `dedicated_runtime` POI map |
| `claims` | `ClaimBook` — TTL'd advisory claims, hashable keys, per-call TTL, expiry-at-write | unification of `swgy_memory.ClaimBook`, `mas_memory.TargetClaims`, `dedicated_runtime` claims |
| `census` | `TeamCensus` — roster + liveness from per-tick HP reports, freshness window, startup grace | `dedicated_runtime.TeamLedger` (liveness subset) |
| `intents` | `AgentIntent`/`IntentBoard` — goal advertisements, stale-pruned on read | `mas_memory` |
| `targets` | sticky target with progress-based invalidation (`set_target`/`update_target_progress`/`check_arrival`), caller-injected distance fn | `swgy_targets` |
| `select` | `select_with_relaxation`, `tiered_select_with_relaxation`, `make_unclaimed_filter` | `swgy_select` |
| `vitals` | `should_retreat`/`is_topped_up`/`hp_deficit` threshold math | `swgy_vitals` |
| `emergency` | `pick_threshold`/`worst_deficient_resource`/`should_pivot` dual-threshold pivots | `swgy_emergency` |

## The two claim flavors

- **Published** (`claims.ClaimBook`): agents write claims into shared
  memory; teammates read the book. Use for own-team coordination when you
  have a shared blackboard.
- **Visible-symmetric** (`select.make_unclaimed_filter`): both agents reach
  the same answer purely from observation — no shared state. Use to infer
  *enemy* intent, or when you don't want shared-memory plumbing.

A single policy can (and the origin stacks did) use both.

## Staleness discipline

Every remembered fact carries a `last_seen_step`; readers gate with
`is_stale(last_seen, now, ttl)` (or `Poi.is_stale`, where `ttl <= 0`
disables aging). This is what prevents ghost-POI chasing: the map never
forgets, but consumers refuse to act on facts older than their tolerance.

## What deliberately did NOT port

The origin `dedicated_runtime.SharedRuntime` also carried game economy
(hub stocks, gear costs, cargo caps, element vocabularies) and a
`PoiKind` enum with Cogs-vs-Clips categories. Those are game logic:
kinds here are a type parameter, kind-transition reactions are the
`on_kind_change` hook, and economy stays in the policy. Its
`EpisodeStats` counters are superseded by the SDK's telemetry sinks
(`players.player_sdk.telemetry`).

## Origin

Extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
Cogs-vs-Clips scripted stack). Mechanical ports where possible; the
merge decisions above are documented per-module. Original smoke tests
live on in `validation/players-tests/test_worldmodel_*.py`.
