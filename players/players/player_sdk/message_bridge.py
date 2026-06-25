"""Protocol-agnostic websocket bridge for message-driven Coworld players.

The bridge owns the common websocket shape shared by non-mettagrid players:
connect to the engine, async-iterate inbound text or binary frames, let a
game-specific handler produce zero or more outbound frames, send them in order,
and always tear down owned resources.

The default close policy intentionally treats a server-side close as game-over,
including abrupt websocket closes reported as code 1006 with no close handshake.
Coworld's runner expects player containers to exit 0 after normal episode end;
letting that close exception escape would fail the episode even though the game
has simply ended.

This module is the deferred migration target for the existing mettagrid JSON
bridge and Crewrift/Sprite-v1 style bridges, but it does not import or depend on
any grid-specific code.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

import websockets
from websockets.exceptions import ConnectionClosed

from players.player_sdk.trace_outputs import TraceOutputs

Frame = str | bytes
HandlerResult = Iterable[Frame] | Awaitable[Iterable[Frame]]
Connect = Callable[..., Any]
ClosePolicy = Callable[[BaseException | None], None]


class MessageHandler(Protocol):
    """Handle one inbound websocket frame and return outbound frames to send."""

    def __call__(self, message: Frame) -> HandlerResult: ...


def exit_zero_on_unclean_close(exc: BaseException | None) -> None:
    """Treat websocket close as normal game-over so the runner sees exit 0.

    Crewrift and other Coworld servers signal episode end by closing the player
    socket. Some servers close cleanly, which the websockets async iterator may
    expose as ordinary iteration end. Crewrift has also closed abruptly with no
    close handshake, surfaced as ``ConnectionClosedError`` with code 1006. Both
    cases are normal game-over for a player container: Coworld's runner requires
    every player process to exit 0, and propagating the close would fail the
    whole episode rather than just ending the player.
    """

    if exc is None or isinstance(exc, ConnectionClosed):
        print("game over: server closed the connection", file=sys.stderr, flush=True)
        return
    raise exc


async def run_message_bridge(
    url: str,
    handler: MessageHandler,
    *,
    trace_outputs: TraceOutputs | None = None,
    connect: Connect = websockets.connect,
    on_close: ClosePolicy = exit_zero_on_unclean_close,
    teardown: Callable[[], None] | None = None,
    **connect_kwargs: Any,
) -> None:
    """Run a websocket message loop until the server closes or an error occurs."""

    primary_exc: BaseException | None = None
    try:
        async with connect(url, **connect_kwargs) as websocket:
            try:
                async for message in websocket:
                    replies = handler(message)
                    if inspect.isawaitable(replies):
                        replies = await replies
                    for frame in replies:
                        await websocket.send(frame)
            except ConnectionClosed as exc:
                on_close(exc)
            else:
                on_close(None)
    except BaseException as exc:
        primary_exc = exc
        raise
    finally:
        cleanup_errors = _close_owned_resources(
            trace_outputs=trace_outputs,
            teardown=teardown,
        )
        if cleanup_errors and primary_exc is None:
            _raise_cleanup_error(cleanup_errors)
        if cleanup_errors and primary_exc is not None:
            for error in cleanup_errors:
                primary_exc.add_note(
                    f"message bridge cleanup failed: {type(error).__name__}: {error}"
                )


def _close_owned_resources(
    *,
    trace_outputs: TraceOutputs | None,
    teardown: Callable[[], None] | None,
) -> list[BaseException]:
    errors: list[BaseException] = []
    if trace_outputs is not None:
        try:
            trace_outputs.close()
        except BaseException as exc:  # noqa: BLE001 - still run the other cleanup hook.
            errors.append(exc)
    if teardown is not None:
        try:
            teardown()
        except BaseException as exc:  # noqa: BLE001 - report after all cleanup runs.
            errors.append(exc)
    return errors


def _raise_cleanup_error(errors: list[BaseException]) -> None:
    error = errors[0]
    for extra in errors[1:]:
        error.add_note(f"additional cleanup failure: {type(extra).__name__}: {extra}")
    raise error
