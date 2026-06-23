"""Engine-specific websocket bridge for the ``cogweb.player.v1`` JSON protocol.

This is the shared player protocol for the **cogweb** family of Coworld games
(agricogla, werecog, cogsul, coguire, cogherence, cognames, ...). Every cogweb
game runnable runs a ``/player`` websocket SERVER, one socket per slot; an
external player policy is a websocket CLIENT that drives one slot, connecting to
the URL in ``COWORLD_PLAYER_WS_URL`` (which already carries ``?slot=&token=``).

The wire envelope is **uniform across every cogweb game** — only the opaque
``view`` and ``decision`` payloads are game-specific (verified against the shared
host ``@cogweb/coworld`` ``protocol.ts`` / ``host.ts``, which relay frames without
reading those payloads):

    game   -> player  welcome      { type, protocol:"cogweb.player.v1", slot, config }
    game   -> player  observation  { type, id, seat, turn, view, messages, reason, timeLeftMs }
    player -> game    reply        { type:"reply", id, decision, messages? }
    game   -> player  final        { type:"final", scores:number[] }

A **rejected** reply is re-sent by the host as a fresh ``observation`` with
``reason`` set (there is no separate reject frame); the host retries up to a few
times, then plays a fallback move. The reply MUST echo the observation's ``id``.
``timeLeftMs`` is the policy's *remaining whole-episode* chess-clock budget (``null``
when unbounded); when it hits 0 the host stops asking and plays for the seat.

This bridge owns all of that envelope handling — id correlation, the reason
re-request, the chess-clock budget, cheap-talk routing, and clean exit — so a
cogweb game's player only supplies a ``decide`` callback mapping a redacted
``view`` to a game-specific ``decision``. It deliberately knows NOTHING about any
particular game's view/decision schema (that stays in the game's player package);
both are passed through verbatim.

Layering: this is the **cogweb specialization** of
:mod:`players.player_sdk.message_bridge`, peer to
:mod:`players.player_sdk.coworld_json_bridge` (mettagrid). It depends only on
:func:`run_message_bridge` for transport. Games whose transport is NOT
``cogweb.player.v1`` use their own engine bridge or the generic bridge directly.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from players.player_sdk.message_bridge import (
    ClosePolicy,
    Connect,
    exit_zero_on_unclean_close,
    run_message_bridge,
)
from players.player_sdk.trace_outputs import TraceOutputs

PROTOCOL = "cogweb.player.v1"

#: The canonical env var holding the ``/player`` websocket URL, and a legacy alias.
WS_URL_ENV = "COWORLD_PLAYER_WS_URL"
WS_URL_ENV_LEGACY = "COGAMES_ENGINE_WS_URL"

# A game-specific decision payload (opaque to this bridge; the game validates it).
Decision = Any
# A redacted seat view (opaque to this bridge).
View = Any


@dataclass
class CogwebContext:
    """Per-observation context handed to a game's ``decide`` callback.

    Everything the cogweb envelope carries that a policy might use, without the
    policy having to parse frames itself.
    """

    #: The seat this player drives (0-based). Equals ``slot`` for a remote player.
    seat: int
    #: The current turn number from the observation.
    turn: int
    #: Set when the previous reply was rejected (the host's reason); ``None`` on a
    #: fresh observation. A policy may use it to re-decide more conservatively.
    reason: str | None = None
    #: Remaining whole-episode chess-clock budget in ms, or ``None`` if unbounded.
    time_left_ms: float | None = None
    #: This seat's visible inbox (public chatter + DMs to/from it), oldest first.
    #: Each item is ``{from, to, text, turn}``.
    inbox: list[dict] = field(default_factory=list)
    #: Public (non-secret) episode config from the welcome frame, or ``None``.
    config: Any = None
    #: This player's own slot index from the welcome frame.
    slot: int | None = None


#: A cheap-talk line to post alongside a reply: ``{"to": seat|None, "text": str}``
#: (``to`` ``None``/absent broadcasts publicly). A bare ``str`` is also accepted and
#: treated as a public line.
TalkLine = dict[str, Any] | str

#: ``decide`` returns a decision, or ``(decision, talk_lines)`` to also post talk.
#: Sync or async. Returning ``None`` (or ``(None, ...)``) declines the turn: the
#: bridge sends nothing and the host falls back to a legal move.
DecideResult = Decision | tuple[Decision, Iterable[TalkLine]]
Decide = Callable[[View, CogwebContext], DecideResult | Awaitable[DecideResult]]

# Optional lifecycle hooks.
OnWelcome = Callable[[CogwebContext], None]
OnFinal = Callable[[list[float]], None]


class _CogwebHandler:
    """Decodes one ``cogweb.player.v1`` frame and returns the outbound reply frames.

    Robust by construction: any undecodable or unexpected frame is ignored
    (returns no reply) rather than crashing the bridge — a player process must not
    die mid-episode, or the host scores the seat as failed.
    """

    def __init__(
        self,
        decide: Decide,
        *,
        on_welcome: OnWelcome | None = None,
        on_final: OnFinal | None = None,
    ) -> None:
        self._decide = decide
        self._on_welcome = on_welcome
        self._on_final = on_final
        self._slot: int | None = None
        self._config: Any = None

    async def __call__(self, message: str | bytes) -> list[str]:
        msg = _decode_frame(message)
        if msg is None:
            return []

        mtype = msg.get("type")
        if mtype == "welcome":
            return self._on_welcome_frame(msg)
        if mtype == "final":
            return self._on_final_frame(msg)
        if mtype != "observation":
            return []  # unknown frame type — ignore
        return await self._on_observation_frame(msg)

    def _on_welcome_frame(self, msg: dict) -> list[str]:
        self._slot = msg.get("slot")
        self._config = msg.get("config")
        if self._on_welcome is not None:
            self._on_welcome(
                CogwebContext(
                    seat=self._slot if isinstance(self._slot, int) else -1,
                    turn=0,
                    config=self._config,
                    slot=self._slot,
                )
            )
        return []

    def _on_final_frame(self, msg: dict) -> list[str]:
        if self._on_final is not None:
            scores = msg.get("scores") or []
            self._on_final([float(s) for s in scores])
        return []  # the host closes the socket after final

    async def _on_observation_frame(self, msg: dict) -> list[str]:
        ctx = CogwebContext(
            seat=int(msg.get("seat", self._slot if isinstance(self._slot, int) else -1)),
            turn=int(msg.get("turn", 0)),
            reason=msg.get("reason"),
            time_left_ms=msg.get("timeLeftMs"),
            inbox=list(msg.get("messages") or []),
            config=self._config,
            slot=self._slot,
        )
        result = self._decide(msg.get("view"), ctx)
        if inspect.isawaitable(result):
            result = await result

        decision, talk = _split_decision(result)
        if decision is None:
            # A policy that declines to act this turn (rare). The host falls back to
            # a legal move; we send nothing.
            return []

        reply: dict[str, Any] = {"type": "reply", "id": msg.get("id"), "decision": decision}
        talk_lines = [_normalize_talk(line) for line in talk]
        if talk_lines:
            reply["messages"] = talk_lines
        return [json.dumps(reply)]


def _decode_frame(message: str | bytes) -> dict | None:
    """Decode an inbound frame to a JSON object, or ``None`` if it isn't one."""
    if isinstance(message, (bytes, bytearray)):
        message = bytes(message).decode("utf-8", "replace")
    try:
        msg = json.loads(message)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None  # ignore undecodable frames; never crash the bridge
    return msg if isinstance(msg, dict) else None


def _split_decision(result: DecideResult) -> tuple[Decision, list[TalkLine]]:
    """Allow ``decide`` to return either ``decision`` or ``(decision, talk_lines)``.

    A 2-tuple is treated as ``(decision, talk_lines)``; anything else (including a
    string, which is iterable but not a talk pair) is the decision itself.
    """
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and not isinstance(result, str)
    ):
        decision, talk = result
        return decision, list(talk or [])
    return result, []


def _normalize_talk(line: TalkLine) -> dict[str, Any]:
    """Normalize a talk line to the wire shape ``{"to": seat|None, "text": str}``.

    A bare string is a public broadcast; a dict is passed through (defaulting
    ``to`` to ``None`` so it round-trips the protocol's ``TalkLine`` schema).
    """
    if isinstance(line, str):
        return {"to": None, "text": line}
    out = dict(line)
    out.setdefault("to", None)
    return out


async def run_cogweb_bridge(
    url: str,
    decide: Decide,
    *,
    on_welcome: OnWelcome | None = None,
    on_final: OnFinal | None = None,
    trace_outputs: TraceOutputs | None = None,
    connect: Connect | None = None,
    on_close: ClosePolicy = exit_zero_on_unclean_close,
    teardown: Callable[[], None] | None = None,
    **connect_kwargs: Any,
) -> None:
    """Run a ``cogweb.player.v1`` player loop until the host closes the socket.

    The game supplies only ``decide``; the bridge owns the wire envelope (welcome /
    observation / reply / final, the observation-id echo, the ``reason`` re-request,
    the ``timeLeftMs`` budget, cheap-talk routing, and exit-0-on-close).

    Args:
        url: the websocket URL (typically :func:`env_ws_url`). Use it verbatim — it
            already encodes ``?slot=&token=`` and appending params breaks the
            handshake on some games.
        decide: ``decide(view, ctx) -> decision`` (or ``(decision, talk_lines)``),
            sync or async. ``view`` is the seat's redacted state (opaque to the
            bridge); ``ctx`` is a :class:`CogwebContext`. Return ``None`` to decline
            the turn (the host falls back to a legal move). The bridge echoes the
            observation id for you.
        on_welcome: optional hook called once with the welcome :class:`CogwebContext`.
        on_final: optional hook called with the per-slot ``scores`` at game end.
        trace_outputs: optional :class:`TraceOutputs`; closed (zipped + uploaded) on
            exit. Pass the same instance you ``record`` telemetry into.
        connect: optional websocket connector (for tests); defaults to
            ``websockets.connect``.
        on_close: close policy; defaults to :func:`exit_zero_on_unclean_close`.
        teardown: optional cleanup callback run on exit.
        **connect_kwargs: forwarded to ``websockets.connect`` (e.g. ``ping_interval``,
            ``ping_timeout``, ``max_size``, ``open_timeout``).
    """
    handler = _CogwebHandler(decide, on_welcome=on_welcome, on_final=on_final)
    bridge_kwargs: dict[str, Any] = dict(connect_kwargs)
    if connect is not None:
        bridge_kwargs["connect"] = connect
    await run_message_bridge(
        url,
        handler,
        trace_outputs=trace_outputs,
        on_close=on_close,
        teardown=teardown,
        **bridge_kwargs,
    )


def env_ws_url(env: dict[str, str] | None = None) -> str:
    """Return the ``/player`` websocket URL from the environment, or raise.

    Reads ``COWORLD_PLAYER_WS_URL`` (canonical) or ``COGAMES_ENGINE_WS_URL``
    (legacy alias). Connect to it EXACTLY as given — the slot/token are already
    encoded and appending query params breaks the handshake on some games.
    """
    source = env if env is not None else os.environ
    url = source.get(WS_URL_ENV) or source.get(WS_URL_ENV_LEGACY)
    if not url:
        raise SystemExit(f"cogweb bridge: {WS_URL_ENV} is not set")
    return url
