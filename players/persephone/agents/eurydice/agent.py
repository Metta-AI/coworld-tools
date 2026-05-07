"""Eurydice agent — import validation for all Orpheus framework components.

This module imports every public component of the Orpheus framework to verify
that the dependency graph resolves cleanly. Once confirmed, this file becomes
the foundation for Eurydice's own policy logic.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

from orpheus.pipeline import Pipeline
from orpheus.outer_loop import OuterLoop

# ---------------------------------------------------------------------------
# Perception
# ---------------------------------------------------------------------------

from orpheus.perception import parse_frame
from orpheus.perception.types import FramePerception, View
from orpheus.perception._common import PROTOCOL_BYTES
from orpheus.perception._unpack import unpack_frame

# ---------------------------------------------------------------------------
# Belief state & update
# ---------------------------------------------------------------------------

from orpheus.belief_state import BeliefState, PlayerInfo, ChatMessageRecord, MinimapSighting
from orpheus import belief_update
from orpheus.action_memory import ActionMemory

# ---------------------------------------------------------------------------
# Buffers (inner <-> outer loop communication)
# ---------------------------------------------------------------------------

from orpheus.buffers import BeliefBuffer
from orpheus.mode_buffer import ModeBuffer

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.idle import IdleMode, IdleTask

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

from orpheus.task import Task, ActCommand
from orpheus.tasks import (
    MoveToTask,
    FollowTask,
    WanderTask,
    OpenGlobalChatTask,
    OpenInfoScreenTask,
    CloseViewTask,
    CreateWhisperTask,
    RequestEntryTask,
    CancelEntryTask,
    ExitWhisperTask,
    GrantEntryTask,
    OfferColorExchangeTask,
    AcceptColorExchangeTask,
    WithdrawColorOfferTask,
    OfferRoleExchangeTask,
    AcceptRoleExchangeTask,
    WithdrawRoleOfferTask,
    RevealRoleTask,
    PassLeadershipTask,
    TakeLeadershipTask,
    VoteUsurpTask,
    SelectHostagesTask,
    SendMessageTask,
)

# ---------------------------------------------------------------------------
# Spatial reasoning
# ---------------------------------------------------------------------------

from orpheus.occupancy_grid import OccupancyGrid, CellState
from orpheus.pathfinding import a_star

# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

from orpheus.hooks import HookPoint, HookRegistry

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from orpheus.logging import Logger, LogLevel

# ---------------------------------------------------------------------------
# Types & constants
# ---------------------------------------------------------------------------

from orpheus.types import (
    Room,
    PlayerShape,
    KnowledgeSource,
    ActionMask,
    PLAYER_COLORS,
    BUTTON_UP,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_SELECT,
    BUTTON_A,
    BUTTON_B,
    RESET_MASK,
)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Verify all imports resolve and key classes are instantiable."""
    # Modes / registry
    registry = ModeRegistry()
    registry.register("idle", IdleMode)

    # Belief state
    bs = BeliefState()
    assert bs.tick == 0

    # Buffers
    _bb = BeliefBuffer()
    _mb = ModeBuffer()

    # Directive
    d = ModeDirective("idle", ModeParams())
    assert d.mode == "idle"

    # Tasks
    idle_task = IdleTask()
    assert idle_task.valid_views == set(View)

    # ActCommand
    cmd = ActCommand(buttons=BUTTON_UP | BUTTON_A)
    assert cmd.buttons == 0x21

    # Logger
    _logger = Logger(level="off")

    # Hooks
    _hr = HookRegistry()

    # Occupancy grid
    _grid = OccupancyGrid(room_size=(256, 256))

    print("eurydice: all Orpheus imports OK")


if __name__ == "__main__":
    _smoke_test()
