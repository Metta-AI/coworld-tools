"""Task definitions for the Orpheus agent.

A task is a high-level strategic behavior that the LLM selects. Each
task maps to a per-frame action function that produces button masks
based on the current belief state and perception.

The fast loop calls the active task's act() method every tick. The slow
LLM loop sets which task is active via the controller.

Tasks are intentionally coarse-grained -- they encapsulate multi-frame
behaviors (walk somewhere, execute a menu sequence, etc.) so the LLM
only needs to reason about strategy, not frame-level input.
"""

from __future__ import annotations

import struct
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from perception.types import FramePerception, MinimapDot, View

if TYPE_CHECKING:
    from belief import BeliefState


# ---------------------------------------------------------------------------
# Button masks (from GAME_API.md)
# ---------------------------------------------------------------------------

BTN_UP = 0x01
BTN_DOWN = 0x02
BTN_LEFT = 0x04
BTN_RIGHT = 0x08
BTN_SELECT = 0x10
BTN_A = 0x20
BTN_B = 0x40
BTN_NONE = 0x00


# ---------------------------------------------------------------------------
# Action output
# ---------------------------------------------------------------------------


@dataclass
class FrameAction:
    """Output of a task's act() for one frame.

    Contains the button mask to send and optionally a chat message.
    """

    button_mask: int = BTN_NONE
    chat_message: str | None = None

    def to_button_packet(self) -> bytes:
        """Encode as a 2-byte button packet for the WebSocket."""
        return struct.pack("BB", 0x00, self.button_mask)

    def to_chat_packet(self) -> bytes | None:
        """Encode chat message as a packet, or None if no message."""
        if self.chat_message is None:
            return None
        return b"\x01" + self.chat_message.encode("ascii", errors="ignore")


# ---------------------------------------------------------------------------
# Task type enum (what the LLM chooses between)
# ---------------------------------------------------------------------------


class TaskType(Enum):
    """The set of high-level behaviors the LLM can select."""

    # Overworld behaviors
    IDLE = "idle"
    EXPLORE = "explore"
    MOVE_TO = "move_to"
    PURSUE_PLAYER = "pursue_player"
    OPEN_CHATROOM = "open_chatroom"

    # Chatroom behaviors
    OFFER_ROLE_EXCHANGE = "offer_role_exchange"
    ACCEPT_ROLE_EXCHANGE = "accept_role_exchange"
    CHAT_AND_OBSERVE = "chat_and_observe"
    EXIT_CHATROOM = "exit_chatroom"

    # Communication
    SHOUT = "shout"

    # Meta
    CHECK_INFO = "check_info"


# ---------------------------------------------------------------------------
# Task base class
# ---------------------------------------------------------------------------


class Task(ABC):
    """Base class for all task implementations.

    Each subclass encapsulates a multi-frame behavior. The fast loop
    calls act() every tick; the task maintains its own internal
    sequencing state (e.g., which step of a menu sequence it's on).
    """

    def __init__(self) -> None:
        self.started_at: float = time.monotonic()
        self.frame_count: int = 0

    @property
    @abstractmethod
    def type(self) -> TaskType:
        """Which task type this is."""

    @abstractmethod
    def act(
        self,
        perception: FramePerception,
        belief: BeliefState,
    ) -> FrameAction:
        """Produce a single frame's action given current perception and belief.

        Called once per tick (~24 FPS). Implementations should be fast
        and non-blocking.
        """

    @property
    def elapsed_secs(self) -> float:
        """Seconds since this task was activated."""
        return time.monotonic() - self.started_at

    def pre_act(self) -> None:
        """Called before act() each frame. Tracks frame count."""
        self.frame_count += 1


# ---------------------------------------------------------------------------
# Concrete task implementations (skeletons)
# ---------------------------------------------------------------------------


class IdleTask(Task):
    """Do nothing. Default state before LLM makes a decision."""

    @property
    def type(self) -> TaskType:
        return TaskType.IDLE

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        return FrameAction(button_mask=BTN_NONE)


class ExploreTask(Task):
    """Wander the room to discover other players on the minimap.

    Simple exploration: alternate directions periodically to cover
    ground. More sophisticated pathfinding can be added later.
    """

    def __init__(self) -> None:
        super().__init__()
        self._direction_switch_interval = 36  # frames (~1.5s)

    @property
    def type(self) -> TaskType:
        return TaskType.EXPLORE

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Cycle through directions to cover ground
        directions = [BTN_UP, BTN_RIGHT, BTN_DOWN, BTN_LEFT,
                      BTN_UP | BTN_RIGHT, BTN_DOWN | BTN_LEFT]
        idx = (self.frame_count // self._direction_switch_interval) % len(directions)
        return FrameAction(button_mask=directions[idx])


class MoveToTask(Task):
    """Move toward a target world coordinate.

    Uses position from belief state and simple directional movement.
    No pathfinding around obstacles yet -- that's a future enhancement.
    """

    def __init__(self, target_x: int, target_y: int) -> None:
        super().__init__()
        self.target_x = target_x
        self.target_y = target_y

    @property
    def type(self) -> TaskType:
        return TaskType.MOVE_TO

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        pos = belief.position
        if pos is None:
            # No position estimate -- explore instead
            return FrameAction(button_mask=BTN_DOWN | BTN_RIGHT)

        mask = BTN_NONE
        dx = self.target_x - pos.x
        dy = self.target_y - pos.y

        # Dead zone: close enough
        if abs(dx) < 5 and abs(dy) < 5:
            return FrameAction(button_mask=BTN_NONE)

        if dx > 5:
            mask |= BTN_RIGHT
        elif dx < -5:
            mask |= BTN_LEFT
        if dy > 5:
            mask |= BTN_DOWN
        elif dy < -5:
            mask |= BTN_UP

        return FrameAction(button_mask=mask)


class PursuePlayerTask(Task):
    """Move toward a target player identified by color on the minimap.

    Watches the minimap for the target dot and moves toward it.
    Falls back to exploration if the target isn't visible.
    """

    def __init__(self, target_color: int) -> None:
        super().__init__()
        self.target_color = target_color

    @property
    def type(self) -> TaskType:
        return TaskType.PURSUE_PLAYER

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Find target on minimap
        target_dot: MinimapDot | None = None
        for dot in belief.minimap_dots:
            if dot.color == self.target_color:
                target_dot = dot
                break

        if target_dot is None:
            # Target not visible -- wander
            directions = [BTN_UP, BTN_RIGHT, BTN_DOWN, BTN_LEFT]
            idx = (self.frame_count // 24) % len(directions)
            return FrameAction(button_mask=directions[idx])

        # Move toward target's estimated world position
        pos = belief.position
        if pos is None:
            return FrameAction(button_mask=BTN_NONE)

        mask = BTN_NONE
        dx = target_dot.world_x - pos.x
        dy = target_dot.world_y - pos.y

        if dx > 3:
            mask |= BTN_RIGHT
        elif dx < -3:
            mask |= BTN_LEFT
        if dy > 3:
            mask |= BTN_DOWN
        elif dy < -3:
            mask |= BTN_UP

        return FrameAction(button_mask=mask)


class OpenChatroomTask(Task):
    """Approach a nearby player and press A to create/request chatroom entry.

    Sequence: move toward target, then press A when close enough.
    If already in chatroom view, this task is a no-op.
    """

    def __init__(self, target_color: int | None = None) -> None:
        super().__init__()
        self.target_color = target_color
        self._pressed_a = False

    @property
    def type(self) -> TaskType:
        return TaskType.OPEN_CHATROOM

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Already in chatroom -- done
        if perception.view == View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        # If waiting for entry, just wait
        if perception.view == View.WAITING_ENTRY:
            return FrameAction(button_mask=BTN_NONE)

        # Try to press A (create chatroom / request entry)
        # Need rising edge: alternate between A and NONE
        if self._pressed_a:
            self._pressed_a = False
            return FrameAction(button_mask=BTN_NONE)

        # Only press A every ~12 frames to avoid spamming
        if self.frame_count % 12 == 0:
            self._pressed_a = True
            return FrameAction(button_mask=BTN_A)

        # Otherwise, pursue the target if specified
        if self.target_color is not None:
            target_dot = None
            for dot in belief.minimap_dots:
                if dot.color == self.target_color:
                    target_dot = dot
                    break
            if target_dot and belief.position:
                mask = BTN_NONE
                dx = target_dot.world_x - belief.position.x
                dy = target_dot.world_y - belief.position.y
                if dx > 3:
                    mask |= BTN_RIGHT
                elif dx < -3:
                    mask |= BTN_LEFT
                if dy > 3:
                    mask |= BTN_DOWN
                elif dy < -3:
                    mask |= BTN_UP
                return FrameAction(button_mask=mask)

        return FrameAction(button_mask=BTN_NONE)


class OfferRoleExchangeTask(Task):
    """Execute the R.OFFER menu sequence inside a chatroom.

    Button sequence: B (open menu), Right (ROLE category),
    then A (select R.OFFER -- first item in ROLE category).
    Each step needs a release frame (mask=0) between presses.
    """

    def __init__(self) -> None:
        super().__init__()
        # Menu sequence: each entry is (mask, description)
        self._sequence: list[int] = [
            BTN_B,       # Open action menu
            BTN_NONE,    # Release
            BTN_RIGHT,   # Navigate to ROLE category
            BTN_NONE,    # Release
            BTN_A,       # Select R.OFFER (first item)
            BTN_NONE,    # Release -- done
        ]
        self._step = 0

    @property
    def type(self) -> TaskType:
        return TaskType.OFFER_ROLE_EXCHANGE

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Not in chatroom -- can't execute
        if perception.view != View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        if self._step >= len(self._sequence):
            # Sequence complete -- idle
            return FrameAction(button_mask=BTN_NONE)

        mask = self._sequence[self._step]
        self._step += 1
        return FrameAction(button_mask=mask)


class AcceptRoleExchangeTask(Task):
    """Execute the R.ACCPT menu sequence inside a chatroom.

    Button sequence: B, Right (ROLE), Down, Down (R.ACCPT), A, A (confirm target).
    """

    def __init__(self) -> None:
        super().__init__()
        self._sequence: list[int] = [
            BTN_B,       # Open action menu
            BTN_NONE,
            BTN_RIGHT,   # Navigate to ROLE category
            BTN_NONE,
            BTN_DOWN,    # Down to R.OFFER/R.UNOFFR
            BTN_NONE,
            BTN_DOWN,    # Down to R.ACCPT
            BTN_NONE,
            BTN_A,       # Select R.ACCPT
            BTN_NONE,
            BTN_A,       # Confirm first target in picker
            BTN_NONE,
        ]
        self._step = 0

    @property
    def type(self) -> TaskType:
        return TaskType.ACCEPT_ROLE_EXCHANGE

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        if perception.view != View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        if self._step >= len(self._sequence):
            return FrameAction(button_mask=BTN_NONE)

        mask = self._sequence[self._step]
        self._step += 1
        return FrameAction(button_mask=mask)


class ChatAndObserveTask(Task):
    """Stay in chatroom, generate chat via LLM, wait for responses.

    This task BLOCKS the fast loop while waiting for LLM-generated chat.
    This is intentional -- chatting requires LLM content and the agent
    can't meaningfully act while composing a message.

    Flow:
    1. On activation: block on LLM to generate an opening message based
       on chat history from the belief state. Send it.
    2. Wait for new messages to appear (or chatroom to empty).
    3. When new messages arrive: block on LLM again for a response.
    4. Repeat until the chatroom empties or the slow loop swaps tasks.
    """

    def __init__(self, llm_provider: object | None = None, tracer: object | None = None) -> None:
        super().__init__()
        self._provider = llm_provider  # LLMProvider instance (or None for no-chat mode)
        self._tracer = tracer  # TraceWriter instance (or None)
        self._last_seen_message_count: int = 0
        self._waiting_for_response: bool = False
        self._sent_count: int = 0
        # Frames to wait after sending before checking for new messages
        self._cooldown_frames: int = 0
        self._COOLDOWN = 48  # ~2s at 24 FPS (matches server rate limit)

    @property
    def type(self) -> TaskType:
        return TaskType.CHAT_AND_OBSERVE

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Not in chatroom -- nothing to do
        if perception.view != View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        # No LLM provider -- passive observe only
        if self._provider is None:
            return FrameAction(button_mask=BTN_NONE)

        # Cooldown after sending (wait for server to process + others to respond)
        if self._cooldown_frames > 0:
            self._cooldown_frames -= 1
            return FrameAction(button_mask=BTN_NONE)

        # Check if chatroom is empty (just us)
        if len(belief.chatroom_occupants) == 0:
            return FrameAction(button_mask=BTN_NONE)

        current_message_count = len(belief.recent_chatroom_messages)

        # First frame or new messages arrived -- generate a response
        should_chat = (
            self._sent_count == 0  # Opening message
            or (
                self._waiting_for_response
                and current_message_count > self._last_seen_message_count
            )
        )

        if should_chat:
            message = self._generate_chat(belief)
            if message:
                self._sent_count += 1
                self._last_seen_message_count = current_message_count + 1
                self._waiting_for_response = True
                self._cooldown_frames = self._COOLDOWN
                return FrameAction(button_mask=BTN_NONE, chat_message=message)
            else:
                # LLM returned nothing -- just observe
                self._waiting_for_response = True
                self._last_seen_message_count = current_message_count

        return FrameAction(button_mask=BTN_NONE)

    def _generate_chat(self, belief: BeliefState) -> str | None:
        """Block on LLM to generate a chat message.

        This is a synchronous call that will block the fast loop for
        the duration of the LLM response (~500-1500ms). Intentional:
        the agent can't act meaningfully while composing.
        """
        from llm import LLMProvider  # Import here to avoid circular at module level

        provider: LLMProvider = self._provider  # type: ignore[assignment]

        # Build chat-specific prompt
        system = (
            "You are chatting in a private chatroom in Persephone's Escape. "
            "Generate a short, strategic message (max 36 chars, ASCII only, no lowercase). "
            "Your goal is to gather information, build trust, or coordinate with teammates. "
            "Respond with ONLY the message text, nothing else."
        )

        # Context for the LLM
        lines = []
        lines.append(f"You are: {belief.my_role} ({belief.my_team})")
        lines.append(f"Chatroom occupants (by color): {belief.chatroom_occupants}")

        if belief.recent_chatroom_messages:
            lines.append("Recent messages:")
            for msg in belief.recent_chatroom_messages[-8:]:
                prefix = "SYS" if msg.is_system else f"P{msg.sender_color}"
                lines.append(f"  [{prefix}] {msg.text}")
        else:
            lines.append("No messages yet -- you're starting the conversation.")

        # What we know about occupants
        for color in belief.chatroom_occupants:
            if color in belief.players:
                pk = belief.players[color]
                if pk.role or pk.team:
                    lines.append(f"  Known about color {color}: role={pk.role}, team={pk.team}")

        user = "\n".join(lines)

        import time as _time
        start = _time.monotonic()
        try:
            response = provider.complete(system, user)
            latency_ms = (_time.monotonic() - start) * 1000
            # Sanitize: strip, uppercase, truncate to 36 chars
            message = response.strip().upper()[:36]
            # Remove any non-ASCII or control chars
            message = "".join(c for c in message if 0x20 <= ord(c) <= 0x7E)

            # Trace outbound chat
            if self._tracer and message:
                self._tracer.chat(
                    tick=belief.tick_count,
                    direction="outbound",
                    system_prompt=system,
                    user_prompt=user,
                    response=message,
                    latency_ms=round(latency_ms, 1),
                    occupants=list(belief.chatroom_occupants),
                    message_count_before=len(belief.recent_chatroom_messages),
                )

            return message if message else None
        except Exception:
            return None


class ExitChatroomTask(Task):
    """Exit the current chatroom via Select button.

    Single press of Select exits the chatroom.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pressed = False

    @property
    def type(self) -> TaskType:
        return TaskType.EXIT_CHATROOM

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Already out
        if perception.view != View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        # Press Select once, then release
        if not self._pressed:
            self._pressed = True
            return FrameAction(button_mask=BTN_SELECT)
        return FrameAction(button_mask=BTN_NONE)


class ShoutTask(Task):
    """Send a global chat message (shout) from the overworld.

    Chat packets sent while not in a chatroom are routed to global.
    No need to open the global chat UI.
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message
        self._sent = False

    @property
    def type(self) -> TaskType:
        return TaskType.SHOUT

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        if not self._sent:
            self._sent = True
            return FrameAction(button_mask=BTN_NONE, chat_message=self._message)
        # After sending, idle (LLM will transition to next task)
        return FrameAction(button_mask=BTN_NONE)


class CheckInfoTask(Task):
    """Toggle the info screen to read known player information.

    Press B to open info screen, wait a few frames for perception to
    read it, then press B again to close.
    """

    def __init__(self) -> None:
        super().__init__()
        self._opened = False
        self._close_at_frame: int | None = None

    @property
    def type(self) -> TaskType:
        return TaskType.CHECK_INFO

    def act(self, perception: FramePerception, belief: BeliefState) -> FrameAction:
        # Don't toggle info while in chatroom
        if perception.view == View.WHISPER:
            return FrameAction(button_mask=BTN_NONE)

        # If we see the info screen, schedule close
        if perception.view == View.INFO_SCREEN:
            if self._close_at_frame is None:
                # Let perception read it for ~12 frames (0.5s)
                self._close_at_frame = self.frame_count + 12
            if self.frame_count >= self._close_at_frame:
                return FrameAction(button_mask=BTN_B)
            return FrameAction(button_mask=BTN_NONE)

        # Open info screen
        if not self._opened:
            self._opened = True
            return FrameAction(button_mask=BTN_B)

        return FrameAction(button_mask=BTN_NONE)


# ---------------------------------------------------------------------------
# Task controller
# ---------------------------------------------------------------------------


@dataclass
class TaskParams:
    """Parameters for instantiating a task.

    The LLM specifies which task to activate and its parameters.
    The controller uses this to construct the concrete instance.
    """

    type: TaskType
    target_x: int | None = None
    target_y: int | None = None
    target_color: int | None = None
    message: str | None = None


class TaskController:
    """Manages the active task and handles transitions.

    The fast loop calls tick() every frame. The slow LLM loop calls
    set_task() when it decides to change behavior.
    Thread-safe: set_task() can be called from the LLM thread.
    """

    def __init__(self, llm_provider: object | None = None, tracer: object | None = None) -> None:
        self._active: Task = IdleTask()
        self._lock = threading.Lock()
        self._transition_log: list[tuple[float, TaskType, TaskType]] = []
        self._llm_provider = llm_provider  # Passed to tasks that need LLM (e.g. chat)
        self._tracer = tracer  # TraceWriter instance (or None)
        self._active_started_at: float = time.monotonic()
        self._active_started_tick: int = 0

    @property
    def active(self) -> Task:
        """The currently executing task."""
        with self._lock:
            return self._active

    @property
    def active_type(self) -> TaskType:
        """Type of the currently executing task."""
        with self._lock:
            return self._active.type

    def set_task(self, params: TaskParams, *, trigger: str = "llm_decision") -> None:
        """Transition to a new task.

        Called by the LLM loop when it decides to change strategy.
        Thread-safe.
        """
        new_task = self._build(params)
        now = time.monotonic()
        with self._lock:
            old_type = self._active.type
            old_started = self._active_started_at
            old_tick = self._active_started_tick
            self._active = new_task
            self._active_started_at = now
            # Estimate current tick from frame_count on the new task (0)
            self._transition_log.append(
                (now, old_type, new_task.type)
            )

        # Trace the transition
        if self._tracer:
            duration_ms = (now - old_started) * 1000
            # Use the task's frame_count for duration in ticks (approximate)
            duration_ticks = int(duration_ms / 41.67)  # ~24 FPS
            self._tracer.task_transition(
                tick=old_tick + duration_ticks,
                from_task=old_type.value,
                to_task=new_task.type.value,
                from_duration_ticks=duration_ticks,
                from_duration_ms=duration_ms,
                trigger=trigger,
                params={
                    k: v for k, v in {
                        "target_x": params.target_x,
                        "target_y": params.target_y,
                        "target_color": params.target_color,
                        "message": params.message,
                    }.items() if v is not None
                },
            )

    def tick(
        self,
        perception: FramePerception,
        belief: BeliefState,
    ) -> FrameAction:
        """Execute one frame of the active task.

        Called by the fast loop every tick. Returns the action to send.
        """
        with self._lock:
            task = self._active
        task.pre_act()
        return task.act(perception, belief)

    def get_recent_transitions(self, n: int = 5) -> list[tuple[float, TaskType, TaskType]]:
        """Return the last N task transitions (for LLM context)."""
        with self._lock:
            return list(self._transition_log[-n:])

    def _build(self, params: TaskParams) -> Task:
        """Construct a Task instance from params."""
        match params.type:
            case TaskType.IDLE:
                return IdleTask()
            case TaskType.EXPLORE:
                return ExploreTask()
            case TaskType.MOVE_TO:
                return MoveToTask(
                    target_x=params.target_x or 50,
                    target_y=params.target_y or 50,
                )
            case TaskType.PURSUE_PLAYER:
                return PursuePlayerTask(
                    target_color=params.target_color or 0,
                )
            case TaskType.OPEN_CHATROOM:
                return OpenChatroomTask(
                    target_color=params.target_color,
                )
            case TaskType.OFFER_ROLE_EXCHANGE:
                return OfferRoleExchangeTask()
            case TaskType.ACCEPT_ROLE_EXCHANGE:
                return AcceptRoleExchangeTask()
            case TaskType.CHAT_AND_OBSERVE:
                return ChatAndObserveTask(
                    llm_provider=self._llm_provider,
                    tracer=self._tracer,
                )
            case TaskType.EXIT_CHATROOM:
                return ExitChatroomTask()
            case TaskType.SHOUT:
                return ShoutTask(message=params.message or "")
            case TaskType.CHECK_INFO:
                return CheckInfoTask()
            case _:
                return IdleTask()
