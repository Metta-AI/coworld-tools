# player_sdk.tuning — typed knob configs + GA genome vectors

Opt-in, stdlib-only tuning utilities for policies. Not re-exported from
`players.player_sdk` — import explicitly.

## The two halves

**`knobs`** — runners forward CLI `kw.<name>=<value>` arguments to a policy's
`__init__` as *string* kwargs. `knobs` coerces them onto a frozen dataclass:

```python
from dataclasses import dataclass
from players.player_sdk.tuning import Knobs, build, split_prefixed

@dataclass(frozen=True)
class MyKnobs(Knobs):
    threshold: int = 10
    falloff: str = "linear"

nav_kwargs, kwargs = split_prefixed(kwargs, "nav__")   # route nested configs
cfg = MyKnobs.from_kwargs(kwargs)                      # "42" -> 42, "true" -> True…
cfg.diff_from_defaults()                               # overrides, for telemetry
```

Supports `int`, `float`, `bool`, `str`, `Literal[...]`, `T | None`,
`tuple[T, ...]`, `frozenset[T]`/`set[T]`. Unknown kwargs warn by default
(`on_unknown="raise"` / `"ignore"` to change). `RoleKnob`/`parse_role_knob`
add a shared-default-with-per-role-overrides pattern; `by_role` reads
`{prefix}_{role}` fields with a loud error listing valid suffixes.

**`genome`** — a `GenomeSpec` of `Gene(name, low, high, default)` entries maps
named parameters to/from a flat float vector in declaration order (the sole
genome contract). A GA/sweep harness consumes only the vector view:

```python
from players.player_sdk.tuning import Gene, GenomeSpec

spec = GenomeSpec([Gene("arrival_radius", 4, 32, 12), Gene("avoid_penalty", 0, 200, 50)])
vec = spec.sample(rng)          # seedable uniform draw
spec.clamp(vec)                 # per-gene bounds
params = spec.from_vector(vec)  # {"arrival_radius": 17.3, ...}
```

**`compose`** — glue: `genome_from_dataclass(cls, bounds)` builds a spec from a
config dataclass's numeric fields (bounds supplied by you — config modules like
`nav_mesh/params.py` document suggested ranges as `# GA bounds [lo, hi]`
comments), and `apply_genome(cfg, spec, vec)` overlays a vector onto a config
(`int` fields rounded, `bool` fields thresholded at 0.5).

## Origin

Extracted from Ron Dahlgren's (swgy) agent libraries: `swgy_knobs.py`
(sm-policies Cogs-vs-Clips scripted stack) and `swgy_tune.knob`
(swgy-crewrift). `Knob`/`KnobSpec` were renamed `Gene`/`GenomeSpec` here to
avoid colliding with the `Knobs` mixin. Behavior is otherwise a faithful port;
the original embedded smoke tests live on as
`validation/players-tests/test_tuning_*.py`.
