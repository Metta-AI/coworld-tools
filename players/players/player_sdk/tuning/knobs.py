"""Typed kwarg-driven configuration ("knobs") for agent policies.

Many policy runners forward CLI ``kw.<name>=<value>`` arguments to a
policy's ``__init__`` as Python kwargs, but every value arrives as a
string. This module gives policies a small, well-typed pipeline for:

  1. Defining tunable parameters as a frozen dataclass.
  2. Coercing string kwargs to the field's declared type.
  3. Layering kwargs on top of a Python-built base config.
  4. Reporting overrides for telemetry / sweeps.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies Cogs-vs-Clips scripted stack). Original module name
``swgy_knobs.py``; it formalized the coercion logic that several
scripted policies had each re-derived by hand.

Quick reference
---------------

    from dataclasses import dataclass
    from typing import Literal
    from players.player_sdk.tuning import Knobs, build, split_prefixed, by_role

    @dataclass(frozen=True)
    class MyKnobs(Knobs):
        phase_threshold: int = 256
        miner_enabled: bool = True
        falloff: Literal["linear", "inverse_square", "step"] = "linear"
        ttl: int | None = None
        weights: tuple[float, ...] = ()
        hp_buffer_miner:   int = 10
        hp_buffer_aligner: int = 10
        hp_buffer_scout:   int = 5

    class MyPolicy:
        def __init__(self, env_info, **kwargs):
            try:
                # Route helper-module kwargs out via "<name>__" prefix.
                nav_kwargs, kwargs = split_prefixed(kwargs, "nav__")
                self._nav_cfg = build(GridNavConfig, nav_kwargs,
                                      log_prefix="[MyPolicy.nav] ")
                self._cfg = MyKnobs.from_kwargs(kwargs,
                                                log_prefix="[MyPolicy] ")
            except Exception as exc:
                # Some runners suppress ``__init__`` exceptions; print
                # to stderr so the cause is visible before re-raising.
                import sys, traceback
                print(f"[MyPolicy] FATAL init: {exc!r}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                raise

        def hp_buffer_for(self, role: str) -> int:
            return by_role(self._cfg, "hp_buffer", role)

CLI form (cogames shown as an illustration; any runner that forwards
string kwargs works the same way)::

    cogames train -p class=my_policy.MyPolicy,\
        kw.phase_threshold=51,kw.miner_enabled=true,\
        kw.falloff=inverse_square,kw.ttl=200,\
        kw.weights=7,6,5,4,3,\
        kw.hp_buffer_miner=20,\
        kw.nav__teammate_repulsion=3.0,kw.nav__heuristic_mode=manhattan

Subclassing :class:`Knobs` is **optional** — :func:`build` works on any
plain ``@dataclass``. The mixin just bundles the convenient methods
(``from_kwargs``, ``to_dict``, ``diff_from_defaults``, ``with_overrides``).
"""
import sys
import types
from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace
from typing import (
    Any,
    Generic,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

__all__ = [
    "Knobs",
    "RoleKnob",
    "build",
    "by_role",
    "coerce_kwargs",
    "coerce_value",
    "parse_role_knob",
    "split_prefixed",
    "KnobCoercionError",
    "UnknownKnobError",
]

K = TypeVar("K")

_MISSING: Any = object()  # sentinel distinct from dataclasses.MISSING


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnknownKnobError(KeyError):
    """Raised by :func:`build` when ``on_unknown="raise"`` and a kwarg has
    no matching field on the target dataclass."""


class KnobCoercionError(ValueError):
    """Raised when a value cannot be coerced to the field's declared type
    (bad int string, Literal mismatch, etc.)."""


# ---------------------------------------------------------------------------
# Type-introspection helpers
# ---------------------------------------------------------------------------


_UNION_ORIGINS = (Union, getattr(types, "UnionType", Union))


def _is_literal(t: Any) -> bool:
    return get_origin(t) is Literal


def _is_optional(t: Any) -> bool:
    if get_origin(t) in _UNION_ORIGINS:
        return type(None) in get_args(t)
    return False


def _strip_optional(t: Any) -> Any:
    if get_origin(t) not in _UNION_ORIGINS:
        return t
    non_none = [a for a in get_args(t) if a is not type(None)]
    if len(non_none) == 1:
        return non_none[0]
    return t  # Union[A, B, None] — ambiguous; let caller passthrough.


def _tuple_element_type(t: Any) -> Any:
    if get_origin(t) is tuple:
        args = get_args(t)
        if args:
            # Both ``tuple[int, ...]`` (args=(int, Ellipsis)) and
            # ``tuple[int, int, int]`` collapse to the first element type.
            return args[0]
    return None


def _set_element_type(t: Any) -> Any:
    if get_origin(t) in (frozenset, set):
        args = get_args(t)
        if args:
            return args[0]
    return None


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


_BOOL_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})
_BOOL_FALSE = frozenset({"0", "false", "no", "off", "n", "f"})
_NONE_STRINGS = frozenset({"", "none", "null"})


def coerce_value(raw: Any, target_type: Any) -> Any:
    """Coerce *raw* (often a CLI string) into *target_type*.

    Supports ``int``, ``float``, ``bool``, ``str``, ``Literal[...]``,
    ``Optional[T]`` (i.e. ``T | None``), ``tuple[T, ...]``, and
    ``frozenset[T]`` / ``set[T]``. Unknown target types fall through
    unchanged: the dataclass ``__init__`` will raise the real error on
    construction, which keeps misuse visible at the right place rather
    than silently coercing.
    """
    if target_type is Any or target_type is None:
        return raw

    # Optional[T] / T | None — strip and recurse.
    if _is_optional(target_type):
        if raw is None:
            return None
        if isinstance(raw, str) and raw.strip().lower() in _NONE_STRINGS:
            return None
        return coerce_value(raw, _strip_optional(target_type))

    # Literal[...] — exact-match validation.
    if _is_literal(target_type):
        options = get_args(target_type)
        if raw in options:
            return raw
        if isinstance(raw, str):
            for opt in options:
                if isinstance(opt, str) and raw == opt:
                    return opt
        raise KnobCoercionError(
            f"value {raw!r} not in Literal options {list(options)!r}"
        )

    # bool — must come before int (bool is an int subclass).
    if target_type is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int):
            return bool(raw)
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in _BOOL_TRUE:
                return True
            if s in _BOOL_FALSE:
                return False
            raise KnobCoercionError(
                f"cannot parse {raw!r} as bool "
                f"(expected one of {sorted(_BOOL_TRUE | _BOOL_FALSE)})"
            )
        return raw

    if target_type is int:
        if isinstance(raw, bool):
            return int(raw)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError as exc:
                raise KnobCoercionError(
                    f"cannot parse {raw!r} as int"
                ) from exc
        if isinstance(raw, float) and raw.is_integer():
            return int(raw)
        return raw

    if target_type is float:
        if isinstance(raw, bool):
            return float(raw)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError as exc:
                raise KnobCoercionError(
                    f"cannot parse {raw!r} as float"
                ) from exc
        return raw

    if target_type is str:
        return raw  # passthrough; dataclass will complain on real mismatch.

    elem_t = _tuple_element_type(target_type)
    if elem_t is not None:
        if isinstance(raw, tuple):
            return tuple(coerce_value(x, elem_t) for x in raw)
        if isinstance(raw, list):
            return tuple(coerce_value(x, elem_t) for x in raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return tuple()
            return tuple(coerce_value(x.strip(), elem_t) for x in s.split(","))
        return raw

    set_elem_t = _set_element_type(target_type)
    if set_elem_t is not None:
        ctor = (
            frozenset if get_origin(target_type) is frozenset else set
        )
        if isinstance(raw, (frozenset, set, list, tuple)):
            return ctor(coerce_value(x, set_elem_t) for x in raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return ctor()
            return ctor(
                coerce_value(x.strip(), set_elem_t) for x in s.split(",")
            )
        return raw

    return raw  # unknown type — passthrough


def coerce_kwargs(
    kwargs: dict[str, Any],
    knobs_cls: type,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce *kwargs* to the field types declared on *knobs_cls*.

    Returns ``(coerced, ignored)``. ``ignored`` is the list of kwargs
    that did not match any dataclass field. Coercion errors raise
    :class:`KnobCoercionError` immediately — those almost always mean
    the user typed the wrong value type and we want a loud error rather
    than a silent default.
    """
    if not is_dataclass(knobs_cls):
        raise TypeError(f"{knobs_cls!r} is not a dataclass")

    try:
        hints = get_type_hints(knobs_cls)
    except Exception:
        hints = {}

    by_name = {f.name: f for f in fields(knobs_cls)}
    coerced: dict[str, Any] = {}
    ignored: list[str] = []

    for key, raw in kwargs.items():
        f = by_name.get(key)
        if f is None:
            ignored.append(key)
            continue
        target = hints.get(key, f.type)
        try:
            coerced[key] = coerce_value(raw, target)
        except KnobCoercionError as exc:
            raise KnobCoercionError(
                f"knob {key!r} on {knobs_cls.__name__}: {exc}"
            ) from exc

    return coerced, ignored


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build(
    knobs_cls: type[K],
    kwargs: dict[str, Any] | None = None,
    *,
    base: K | None = None,
    on_unknown: str = "warn",
    log_prefix: str = "",
) -> K:
    """Construct (or layer) a knobs dataclass instance from *kwargs*.

    - Empty ``kwargs`` returns ``base`` if given, else ``knobs_cls()``.
    - With no ``base``: returns ``knobs_cls(**coerced)``.
    - With ``base``: returns ``dataclasses.replace(base, **coerced)``;
      kwargs override the base, fields not supplied keep base's values.

    ``on_unknown`` selects the policy for kwargs that don't map to any
    field on ``knobs_cls``:

    - ``"warn"`` (default): one stderr line listing the ignored keys.
      Sweep harnesses often share kwarg sets across slightly-different
      policy classes, so warning instead of crashing is the friendly
      default.
    - ``"raise"``: :class:`UnknownKnobError`. Useful while authoring a
      new policy when you want typos to fail loudly.
    - ``"ignore"``: silent.

    ``log_prefix`` is prepended to warnings (e.g. ``"[MyPolicy] "``) so
    a multi-config policy can tell which sub-config is complaining.
    """
    if on_unknown not in ("warn", "raise", "ignore"):
        raise ValueError(
            f"on_unknown must be 'warn'/'raise'/'ignore', got {on_unknown!r}"
        )

    if not kwargs:
        return base if base is not None else knobs_cls()

    coerced, ignored = coerce_kwargs(kwargs, knobs_cls)

    if ignored:
        if on_unknown == "raise":
            raise UnknownKnobError(
                f"{log_prefix}unknown knobs on "
                f"{knobs_cls.__name__}: {sorted(ignored)}"
            )
        if on_unknown == "warn":
            print(
                f"{log_prefix}WARNING: ignoring unknown knobs on "
                f"{knobs_cls.__name__}: {sorted(ignored)}",
                file=sys.stderr,
            )

    if base is None:
        return knobs_cls(**coerced)
    if not coerced:
        return base
    return replace(base, **coerced)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class Knobs:
    """Optional mixin for frozen-dataclass knob containers.

    Subclassing is opt-in — :func:`build` works on any plain
    ``@dataclass``. The mixin just bundles convenient methods so the
    common case reads naturally::

        @dataclass(frozen=True)
        class MyKnobs(Knobs):
            threshold: int = 10

        cfg = MyKnobs.from_kwargs({"threshold": "20"})
        cfg.to_dict()             # {"threshold": 20}
        cfg.diff_from_defaults()  # {"threshold": 20}
        cfg.with_overrides(threshold=30)
    """

    @classmethod
    def from_kwargs(
        cls,
        kwargs: dict[str, Any] | None = None,
        *,
        base: Any | None = None,
        on_unknown: str = "warn",
        log_prefix: str = "",
    ) -> Any:
        return build(
            cls,
            kwargs,
            base=base,
            on_unknown=on_unknown,
            log_prefix=log_prefix,
        )

    def with_overrides(self, **changes: Any) -> Any:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def diff_from_defaults(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            current = getattr(self, f.name)
            if f.default is not MISSING:
                default = f.default
            elif f.default_factory is not MISSING:  # type: ignore[misc]
                default = f.default_factory()  # type: ignore[misc]
            else:
                # Required field — no default to compare against; always emit.
                out[f.name] = current
                continue
            if current != default:
                out[f.name] = current
        return out


# ---------------------------------------------------------------------------
# Composition / accessor helpers
# ---------------------------------------------------------------------------


def split_prefixed(
    kwargs: dict[str, Any], prefix: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split *kwargs* into ``(matched, rest)`` by *prefix*.

    Keys that start with ``prefix`` have the prefix stripped and land in
    ``matched``. Used to route CLI kwargs to a nested helper-module
    config without name collisions::

        nav_kwargs, kwargs = split_prefixed(kwargs, "nav__")
        # kw.nav__teammate_repulsion=3 -> nav_kwargs["teammate_repulsion"]="3"
        nav_cfg = build(GridNavConfig, nav_kwargs)

    The double-underscore convention is suggested but not enforced;
    pass any prefix string.
    """
    matched: dict[str, Any] = {}
    rest: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k.startswith(prefix):
            matched[k[len(prefix):]] = v
        else:
            rest[k] = v
    return matched, rest


def by_role(
    knobs: Any, prefix: str, role: str, default: Any = _MISSING
) -> Any:
    """Look up ``{prefix}_{role}`` on *knobs*.

    Replaces scattered ``getattr(cfg, f"hp_buffer_{role}")`` calls with
    a single helper that errors loudly on a missing role and lists the
    valid suffixes. Pass ``default=`` to opt out of the error.
    """
    name = f"{prefix}_{role}"
    if hasattr(knobs, name):
        return getattr(knobs, name)
    if default is not _MISSING:
        return default
    valid = sorted(
        f.name[len(prefix) + 1:]
        for f in fields(knobs)
        if f.name.startswith(prefix + "_")
    )
    raise AttributeError(
        f"{type(knobs).__name__} has no field {name!r}; "
        f"known {prefix}_* suffixes: {valid}"
    )


# ---------------------------------------------------------------------------
# Per-role override knob with default-fallback
# ---------------------------------------------------------------------------
#
# Some policies need a shared default with per-role overrides. A typed
# value object is cleaner than sentinel fields plus a custom resolver,
# and it scales cleanly as more role-specific knobs are introduced.

T = TypeVar("T")


@dataclass(frozen=True)
class RoleKnob(Generic[T]):
    """A knob with a default value and per-role overrides.

    Replaces the per-knob sentinel-fallback dance (``aligner_X = -1``,
    ``scrambler_X = -1``, then a resolver that interprets -1 as "use
    the shared X"). Reads cleanly at the call site::

        topup = self._knobs.heart_topup.for_role("scrambler")

    Returns ``default`` when the role has no override.
    """
    default: T
    by_role: dict[str, T] = field(default_factory=dict)

    def for_role(self, role: str | None) -> T:
        if role is None:
            return self.default
        return self.by_role.get(role, self.default)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RoleKnob[T]":
        """Build from a nested-dict form (typical YAML face)::

            heart_topup_target:
              default: 5
              by_role:
                scrambler: 1

        Tolerant: accepts ``{default: 5}`` (no by_role key) and a bare
        scalar wrapped to ``{default: scalar, by_role: {}}``.
        """
        if not isinstance(raw, dict):
            return cls(default=raw)
        default = raw.get("default")
        if default is None and "by_role" not in raw:
            # Legacy: {"aligner": 5} treated as by_role only is
            # ambiguous (no default). Require "default" key for safety.
            raise KnobCoercionError(
                f"RoleKnob.from_dict requires a 'default' key; got {raw!r}"
            )
        by_role = dict(raw.get("by_role", {}))
        return cls(default=default, by_role=by_role)


def parse_role_knob(
    kwargs: dict[str, Any],
    base_name: str,
    default: T,
    type_: Any = None,
    *,
    consume: bool = True,
) -> "RoleKnob[T]":
    """Extract a ``RoleKnob[T]`` from *kwargs*, recognizing three
    surface forms:

    1. **Bare flat key** ``base_name=5`` → ``RoleKnob(default=5)``.
    2. **Suffixed flat keys** ``base_name__aligner=5`` →
       ``RoleKnob(default=<original default>, by_role={"aligner": 5})``.
       (Bare and suffixed compose: both can appear.)
    3. **Nested dict** ``base_name={"default": 5, "by_role": {"aligner": 2}}``
       — typical of YAML configs.

    When ``consume=True`` (default), the matched keys are popped from
    *kwargs* in place — match the convention of ``split_prefixed`` so
    callers can call this before ``build()``.

    ``type_`` is the value type for coercion (e.g. ``int``); if
    ``None``, raw values pass through unchanged. CLI-string values are
    coerced via ``coerce_value``.
    """
    suffix_prefix = f"{base_name}__"
    matched_default: Any = _MISSING
    matched_by_role: dict[str, Any] = {}
    keys_to_pop: list[str] = []

    for key, raw in kwargs.items():
        if key == base_name:
            keys_to_pop.append(key)
            if isinstance(raw, dict) and ("default" in raw or "by_role" in raw):
                rk = RoleKnob.from_dict(raw)
                # Normalize: capture default and any by_role overrides.
                matched_default = (
                    rk.default if type_ is None else coerce_value(rk.default, type_)
                )
                if rk.by_role:
                    for r, v in rk.by_role.items():
                        matched_by_role[r] = (
                            v if type_ is None else coerce_value(v, type_)
                        )
            else:
                matched_default = (
                    raw if type_ is None else coerce_value(raw, type_)
                )
        elif key.startswith(suffix_prefix):
            role = key[len(suffix_prefix):]
            keys_to_pop.append(key)
            matched_by_role[role] = (
                raw if type_ is None else coerce_value(raw, type_)
            )

    if consume:
        for k in keys_to_pop:
            kwargs.pop(k, None)

    final_default = matched_default if matched_default is not _MISSING else default
    return RoleKnob(default=final_default, by_role=matched_by_role)
