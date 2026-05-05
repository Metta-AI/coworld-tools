"""Belief state for the Orpheus agent.

Accumulates knowledge across frames. The fast loop updates this every
tick; the slow LLM loop reads a snapshot to decide on superaction
transitions.

The belief state is the agent's accumulated model of the world -- what
it knows, what it suspects, and what it's unsure about. It's updated
incrementally by each frame's perception output and provides the context
the LLM needs to make strategic decisions.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from perception.types import (
    ChatMessage,
    FramePerception,
    KnownPlayer,
    MinimapDot,
    Position,
    Room,
    View,
)


class GamePhase(Enum):
    """High-level game phase (distinct from per-frame View)."""

    LOBBY = "lobby"
    ROLE_REVEAL = "role_reveal"
    PLAYING = "playing"
    HOSTAGE_SELECT = "hostage_select"
    HOSTAGE_EXCHANGE = "hostage_exchange"
    GAME_OVER = "game_over"
    UNKNOWN = "unknown"


@dataclass
class PlayerKnowledge:
    """What the agent knows about a specific player (by color index)."""

    color: int
    role: str | None = None
    team: str | None = None  # "shades" or "nymphs"
    last_seen_position: Position | None = None
    last_seen_tick: int = 0
    in_my_room: bool = False
    # Whether we've had a chatroom interaction with this player.
    chatted_with: bool = False
    # Whether this player has offered us a role exchange.
    offered_role_exchange: bool = False
    # Whether we've offered them a role exchange.
    we_offered_role_exchange: bool = False


@dataclass
class BeliefState:
    """The agent's accumulated world model.

    Thread-safe: the fast loop writes via update(), the slow loop reads
    via snapshot(). A lock protects shared mutable state.
    """

    # --- Identity (set once at role reveal) ---
    my_role: str | None = None
    my_team: str | None = None  # "shades" or "nymphs"
    my_room: Room | None = None
    my_color: int | None = None  # Palette index assigned to us

    # --- Spatial ---
    position: Position | None = None
    room_size: int = 100  # Updated from role reveal

    # --- Temporal ---
    current_round: int | None = None
    timer_secs: int | None = None
    tick_count: int = 0

    # --- Game state ---
    phase: GamePhase = GamePhase.UNKNOWN
    current_view: View = View.UNKNOWN

    # --- Players ---
    players: dict[int, PlayerKnowledge] = field(default_factory=dict)
    minimap_dots: list[MinimapDot] = field(default_factory=list)

    # --- Communication ---
    recent_chatroom_messages: list[ChatMessage] = field(default_factory=list)
    recent_global_messages: list[ChatMessage] = field(default_factory=list)
    last_shout: str | None = None
    last_shout_color: int | None = None

    # --- Chatroom context ---
    in_chatroom: bool = False
    chatroom_occupants: list[int] = field(default_factory=list)
    pending_role_offer: bool = False
    pending_color_offer: bool = False

    # --- Result ---
    game_winner: str | None = None

    # --- Metadata ---
    last_update_time: float = 0.0

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, perception: FramePerception) -> None:
        """Integrate a new frame's perception into the belief state.

        Called once per tick by the fast loop. Should be cheap -- no
        allocations on the hot path beyond updating existing fields.
        """
        with self._lock:
            self._update_internal(perception)

    def _update_internal(self, p: FramePerception) -> None:
        """Internal update logic (caller holds lock)."""
        self.tick_count += 1
        self.current_view = p.view
        self.last_update_time = time.monotonic()

        # Phase tracking
        self._update_phase(p)

        # View-specific updates
        if p.view == View.ROLE_REVEAL and p.role_reveal:
            self._update_from_role_reveal(p)

        elif p.view in (View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT, View.WAITING_ENTRY):
            self._update_from_overworld(p)

        elif p.view == View.WHISPER and p.chatroom:
            self._update_from_chatroom(p)

        elif p.view == View.GLOBAL_CHAT and p.global_chat:
            self._update_from_global_chat(p)

        elif p.view == View.INFO_SCREEN and p.info_screen:
            self._update_from_info_screen(p)

        elif p.view == View.HOSTAGE_EXCHANGE and p.exchange:
            self._update_from_exchange(p)

        elif p.view in (View.REVEAL, View.GAME_OVER) and p.result:
            self._update_from_result(p)

    def _update_phase(self, p: FramePerception) -> None:
        """Map current view to high-level game phase."""
        view_to_phase = {
            View.LOBBY: GamePhase.LOBBY,
            View.ROLE_REVEAL: GamePhase.ROLE_REVEAL,
            View.PLAYING: GamePhase.PLAYING,
            View.WAITING_ENTRY: GamePhase.PLAYING,
            View.WHISPER: GamePhase.PLAYING,
            View.GLOBAL_CHAT: GamePhase.PLAYING,
            View.INFO_SCREEN: GamePhase.PLAYING,
            View.HOSTAGE_SELECT: GamePhase.HOSTAGE_SELECT,
            View.LEADER_SUMMIT: GamePhase.HOSTAGE_SELECT,
            View.HOSTAGE_EXCHANGE: GamePhase.HOSTAGE_EXCHANGE,
            View.REVEAL: GamePhase.GAME_OVER,
            View.GAME_OVER: GamePhase.GAME_OVER,
        }
        self.phase = view_to_phase.get(p.view, GamePhase.UNKNOWN)

    def _update_from_role_reveal(self, p: FramePerception) -> None:
        """Extract identity info from role reveal screen."""
        rr = p.role_reveal
        if rr.role:
            self.my_role = rr.role
        if rr.team:
            self.my_team = rr.team.lower()
        if rr.room:
            if "underworld" in rr.room.lower():
                self.my_room = Room.UNDERWORLD
            else:
                self.my_room = Room.MORTAL_REALM
        if rr.room_size:
            self.room_size = rr.room_size

    def _update_from_overworld(self, p: FramePerception) -> None:
        """Update spatial and temporal info from overworld views."""
        ow = p.overworld
        if not ow:
            return

        # Temporal
        if ow.round is not None:
            self.current_round = ow.round
        if ow.timer_secs is not None:
            self.timer_secs = ow.timer_secs

        # Role from HUD (more reliable than role reveal OCR)
        if ow.role_name:
            self.my_role = ow.role_name
        if ow.role_team_color is not None:
            self.my_team = "shades" if ow.role_team_color == 3 else "nymphs"

        # Spatial
        if ow.self_position:
            self.position = ow.self_position
            self.my_room = ow.self_position.room
        if ow.room:
            self.my_room = ow.room

        # Minimap
        self.minimap_dots = list(ow.minimap_dots)
        for dot in ow.minimap_dots:
            if dot.is_self:
                continue
            player = self.players.setdefault(
                dot.color, PlayerKnowledge(color=dot.color)
            )
            player.last_seen_tick = self.tick_count
            player.in_my_room = True

        # Shout
        if ow.last_shout:
            self.last_shout = ow.last_shout
            self.last_shout_color = ow.last_shout_color

        # Track chatroom state from view
        self.in_chatroom = False
        self.chatroom_occupants = []

    def _update_from_chatroom(self, p: FramePerception) -> None:
        """Update communication state from chatroom view."""
        cr = p.chatroom
        self.in_chatroom = True
        self.chatroom_occupants = list(cr.occupant_colors)
        self.pending_role_offer = cr.pending_role_offer
        self.pending_color_offer = cr.pending_color_offer

        # Track who we've chatted with
        for color in cr.occupant_colors:
            player = self.players.setdefault(color, PlayerKnowledge(color=color))
            player.chatted_with = True

        # Store recent messages (keep last N)
        if cr.messages:
            self.recent_chatroom_messages = list(cr.messages[-10:])

    def _update_from_global_chat(self, p: FramePerception) -> None:
        """Update from global chat view."""
        gc = p.global_chat
        if gc.messages:
            self.recent_global_messages = list(gc.messages[-10:])
        self.in_chatroom = False

    def _update_from_info_screen(self, p: FramePerception) -> None:
        """Update player knowledge from info screen."""
        info = p.info_screen
        for kp in info.known_players:
            player = self.players.setdefault(kp.color, PlayerKnowledge(color=kp.color))
            if kp.role_name:
                player.role = kp.role_name
            if kp.team_color is not None:
                player.team = "shades" if kp.team_color == 3 else "nymphs"
            if kp.is_self:
                self.my_color = kp.color

    def _update_from_exchange(self, p: FramePerception) -> None:
        """Update from hostage exchange screen."""
        # Track role indicators revealed during exchange
        ex = p.exchange
        for ep in ex.leaders + ex.departing + ex.arriving:
            if ep.role_indicator:
                player = self.players.setdefault(
                    ep.color, PlayerKnowledge(color=ep.color)
                )
                player.role = ep.role_indicator.role
                player.team = ep.role_indicator.team

    def _update_from_result(self, p: FramePerception) -> None:
        """Record game result."""
        if p.result and p.result.winner:
            self.game_winner = p.result.winner

    def snapshot(self) -> BeliefSnapshot:
        """Create a read-only snapshot for the LLM loop.

        Returns a frozen copy of the relevant belief state fields that
        the LLM needs for decision-making. Cheap to create -- just
        copies references to immutable/small objects.
        """
        with self._lock:
            return BeliefSnapshot(
                my_role=self.my_role,
                my_team=self.my_team,
                my_room=self.my_room,
                my_color=self.my_color,
                position=self.position,
                room_size=self.room_size,
                current_round=self.current_round,
                timer_secs=self.timer_secs,
                tick_count=self.tick_count,
                phase=self.phase,
                current_view=self.current_view,
                players=dict(self.players),
                minimap_dots=list(self.minimap_dots),
                in_chatroom=self.in_chatroom,
                chatroom_occupants=list(self.chatroom_occupants),
                pending_role_offer=self.pending_role_offer,
                pending_color_offer=self.pending_color_offer,
                recent_chatroom_messages=list(self.recent_chatroom_messages),
                recent_global_messages=list(self.recent_global_messages),
                last_shout=self.last_shout,
                last_shout_color=self.last_shout_color,
                game_winner=self.game_winner,
            )


@dataclass(frozen=True)
class BeliefSnapshot:
    """Immutable snapshot of belief state for LLM consumption.

    This is what gets serialized into the LLM prompt. Keep it focused
    on decision-relevant information.
    """

    my_role: str | None
    my_team: str | None
    my_room: Room | None
    my_color: int | None
    position: Position | None
    room_size: int
    current_round: int | None
    timer_secs: int | None
    tick_count: int
    phase: GamePhase
    current_view: View
    players: dict[int, PlayerKnowledge]
    minimap_dots: list[MinimapDot]
    in_chatroom: bool
    chatroom_occupants: list[int]
    pending_role_offer: bool
    pending_color_offer: bool
    recent_chatroom_messages: list[ChatMessage]
    recent_global_messages: list[ChatMessage]
    last_shout: str | None
    last_shout_color: int | None
    game_winner: str | None

    def to_prompt_context(self) -> str:
        """Serialize the snapshot into a text block for the LLM prompt.

        Provides a structured summary of the current game state that
        the LLM can reason about.
        """
        lines: list[str] = []

        # Identity
        lines.append(f"Role: {self.my_role or 'unknown'}")
        lines.append(f"Team: {self.my_team or 'unknown'}")
        lines.append(f"Room: {self.my_room.value if self.my_room else 'unknown'}")
        lines.append(f"Color index: {self.my_color}")

        # Temporal
        lines.append(f"Round: {self.current_round or '?'}")
        lines.append(f"Timer: {self.timer_secs}s" if self.timer_secs else "Timer: ?")
        lines.append(f"Phase: {self.phase.value}")
        lines.append(f"View: {self.current_view.value}")

        # Spatial
        if self.position:
            lines.append(
                f"Position: ({self.position.x}, {self.position.y}) "
                f"in {self.position.room.value}"
            )

        # Chatroom
        if self.in_chatroom:
            lines.append(f"In chatroom with: {self.chatroom_occupants}")
            if self.pending_role_offer:
                lines.append("  -> Pending role exchange offer!")
            if self.pending_color_offer:
                lines.append("  -> Pending color exchange offer!")

        # Known players
        if self.players:
            lines.append("Known players:")
            for color, pk in sorted(self.players.items()):
                parts = [f"  color={color}"]
                if pk.role:
                    parts.append(f"role={pk.role}")
                if pk.team:
                    parts.append(f"team={pk.team}")
                if pk.in_my_room:
                    parts.append("(in room)")
                if pk.offered_role_exchange:
                    parts.append("(offered R.EXCHANGE)")
                lines.append(" ".join(parts))

        # Nearby players (minimap)
        if self.minimap_dots:
            non_self = [d for d in self.minimap_dots if not d.is_self]
            if non_self:
                lines.append(
                    f"Nearby players on minimap: {len(non_self)} "
                    f"(colors: {[d.color for d in non_self]})"
                )

        # Recent comms
        if self.recent_chatroom_messages:
            lines.append("Recent chatroom messages:")
            for msg in self.recent_chatroom_messages[-5:]:
                prefix = "SYS" if msg.is_system else f"P{msg.sender_color}"
                lines.append(f"  [{prefix}] {msg.text}")

        if self.last_shout:
            lines.append(f"Last shout (color {self.last_shout_color}): {self.last_shout}")

        return "\n".join(lines)
