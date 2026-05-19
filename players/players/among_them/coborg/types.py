"""Typed data structures for the coborg Among Them agent.

P0 scaffolds the public types and trivial perception/belief-update functions.
Subsequent phases extend ``AmongThemPercept`` and ``AmongThemBelief`` with
parsed actors, tasks, voting state, social memory, and inferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict


SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
PACKED_FRAME_BYTES = SCREEN_WIDTH * SCREEN_HEIGHT // 2  # 8192


@dataclass(frozen=True)
class AmongThemObservation:
    """Raw observation handed to the runtime by the Coworld bridge.

    P0 only carries the 8192-byte packed frame. Later phases may add structured
    state-vector taps (PLAN D9 / R5) here without changing perception entry.
    """

    packed_frame: bytes
    slot: int = 0


@dataclass(frozen=True)
class AmongThemPercept:
    """Parsed per-tick view. P0 only counts ticks; P1 fills in pixel-derived fields."""

    tick: int
    frame: np.ndarray | None = None


@dataclass
class AmongThemBelief:
    """Persistent world model. P0 carries tick count only; P1 introduces
    self/world/entities/tasks/social/inferences sections per PLAN §4."""

    tick: int = 0


@dataclass
class ActionState:
    """Transport-side mechanics (routes, button pulses, pending chat).

    Empty in P0 — noop emits no pending chat and no movement plan.
    """

    pending_chat: list[str] = field(default_factory=list)


class AmongThemIntent(BaseModel):
    """Symbolic intent emitted by a mode. The action resolver translates this
    into wire-format input/chat packets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["noop", "input", "chat"] = "noop"
    mask: int = 0
    text: str = ""
    reason: str = ""


@dataclass(frozen=True)
class AmongThemCommand:
    """Concrete wire payload. ``packets`` may contain zero, one, or two
    elements per tick: a 2-byte input packet, optionally followed by a chat
    packet. Empty tuple means "no transmission this tick."""

    packets: tuple[bytes, ...] = ()


def unpack_frame(packed_frame: bytes) -> np.ndarray:
    """Unpack a 4-bit nybble-packed 128×128 frame into a uint8 array."""

    if len(packed_frame) != PACKED_FRAME_BYTES:
        raise ValueError(
            f"expected {PACKED_FRAME_BYTES} packed bytes, got {len(packed_frame)}"
        )
    packed = np.frombuffer(packed_frame, dtype=np.uint8)
    pixels = np.empty((PACKED_FRAME_BYTES * 2,), dtype=np.uint8)
    pixels[0::2] = packed & 0x0F
    pixels[1::2] = packed >> 4
    return pixels.reshape((SCREEN_HEIGHT, SCREEN_WIDTH))


def perceive(observation: AmongThemObservation, tick: int) -> AmongThemPercept:
    """P0 perception: unpack the frame, leave parsing to P1."""

    del observation  # P0 does not yet look at pixels
    return AmongThemPercept(tick=tick)


def update_belief(belief: AmongThemBelief, percept: AmongThemPercept) -> None:
    """P0 belief update: track tick count only."""

    belief.tick = percept.tick
