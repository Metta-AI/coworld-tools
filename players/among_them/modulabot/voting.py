"""Voting-screen perception (parse half).

Port of ``among_them/players/modulabot/voting.nim`` lines 1-481.
Decides *what the screen looks like*; the cursor-drive + listen-timer
+ A-press policy half lives in :mod:`modulabot.policies.voting`.

The entry point is :func:`parse_voting_screen`. It walks candidate
player counts top-down and, for each, tries
:func:`parse_voting_candidate` — a strict parser that only accepts a
count when every slot resolves to a player or body sprite at its
expected position, with its colour index matching its slot index.
That's how we know "yes, this frame is the voting screen" rather
than a lookalike interstitial.

Cache discipline: callers should run :func:`parse_voting_screen`
once per frame during a meeting. Every call overwrites
``bot.voting.slots``, ``chat_text``, ``chat_lines``, and the other
parse-cache fields; the decision policy reads from the cache,
it doesn't write to it.

Call order on a voting frame::

    from modulabot import voting
    if voting.parse_voting_screen(bot, sprites, font, frame, tick):
        # bot.voting.* is now populated; run the decision policy.
        ...

When the parser returns ``False`` (not a voting screen), it leaves
``bot.voting.active = False`` and zeros the parse cache so stale
slots / chat lines can't leak into the next meeting.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Iterable, Iterator

import numpy as np

from . import ascii as ascii_mod
from .actors import (
    BODY_MAX_MISSES,
    BODY_MIN_STABLE_PIXELS,
    BODY_MIN_TINT_PIXELS,
)
from .data import (
    PLAYER_COLOR_NAMES,
    PLAYER_COLORS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    PixelFont,
    Sprites,
)
from .sprite_match import (
    actor_color_index,
    crewmate_color_index,
    matches_actor_sprite,
    matches_crewmate,
    player_color_index,
)
from .state import Bot, VoteChatLine, VoteSlot

# ---------------------------------------------------------------------------
# Constants (from voting.nim + sim.nim)
# ---------------------------------------------------------------------------

#: Sentinel for "we haven't resolved this yet" — mirrors ``VoteUnknown``
#: in the Nim types so the two ports interpret parse-cache fields the
#: same way.
VOTE_UNKNOWN = -1

#: Sentinel for "skip" as a vote target — mirrors ``VoteSkip`` in
#: Nim. Distinct from slot indices (0..N-1) and from VOTE_UNKNOWN.
VOTE_SKIP = -2

#: Maximum players per lobby. BitWorld caps it at 16; the Nim
#: parser iterates down from this value to find the first player
#: count that validates.
MAX_PLAYERS = 16

VOTE_CELL_W = 16
VOTE_CELL_H = 17
VOTE_START_Y = 2
VOTE_SKIP_W = 28

#: Palette index of the "dark" outline the local-player marker
#: uses when the self colour is palette black (index 0). Mirrors
#: the ``VoteBlackMarker`` constant in Nim.
VOTE_BLACK_MARKER = 12

#: Sim-side chat panel geometry. Sourced directly from
#: ``among_them/sim.nim`` (``VoteChatIconX``, ``VoteChatTextX``,
#: ``VoteChatCharsPerLine``) so the parser stays aligned with whatever
#: the sim draws. These are tiny constants, not worth importing as
#: state; re-check against sim.nim if the chat panel layout changes.
VOTE_CHAT_ICON_X = 1
#: ``VoteChatIconX + SpriteSize + 1``, where ``SpriteSize`` is 12.
VOTE_CHAT_TEXT_X = VOTE_CHAT_ICON_X + 12 + 1
#: Max glyphs read per chat line. Variable-width glyphs advance by
#: their own width so :func:`~modulabot.ascii.read_run` terminates
#: when the remaining panel width is exhausted regardless.
VOTE_CHARS_PER_LINE = 32
#: Max vertical distance (pixels) from a chat text-line y to a
#: speaker pip's sprite-top y before we declare the pip unrelated.
VOTE_CHAT_SPEAKER_SEARCH = 24

#: Cursor outline colour (PICO-8 white in the bitworld palette).
_CURSOR_COLOR = 2
#: Space / interstitial background. Chat OCR uses black background by
#: default in :mod:`modulabot.ascii`; explicit for readability.
_TEXT_BACKGROUND = 0

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def clear_voting_state(bot: Bot) -> None:
    """Reset the voting sub-record to its sentinel-initialised form.

    Called at the end of a voting interstitial (next meeting rebuilds
    fresh) and whenever :func:`parse_voting_screen` decides the
    current frame isn't actually the voting screen.
    """
    v = bot.voting
    v.active = False
    v.player_count = 0
    v.cursor = VOTE_UNKNOWN
    v.self_slot = VOTE_UNKNOWN
    v.target_slot = VOTE_UNKNOWN
    v.start_tick = -1
    v.chat_sus_color = VOTE_UNKNOWN
    v.chat_text = ""
    v.chat_lines = []
    v.slots = [VoteSlot(color_index=VOTE_UNKNOWN, alive=False) for _ in range(MAX_PLAYERS)]
    v.choices = [VOTE_UNKNOWN] * MAX_PLAYERS


# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoteGridLayout:
    """Fixed voting grid geometry for one player count.

    Computed once per parse attempt by :func:`vote_grid_layout`;
    passed to the slot / cursor / skip helpers so they all agree
    about where the cells are.
    """

    cols: int
    rows: int
    start_x: int
    skip_x: int
    skip_y: int


def vote_grid_layout(count: int) -> VoteGridLayout:
    """Return the grid geometry for ``count`` players (1..MAX_PLAYERS).

    Cell grid is column-major up to 8 wide; anything above 8 wraps
    to a second row. Matches ``voteGridLayout`` in ``voting.nim``.
    """
    cols = min(count, 8)
    rows = (count + cols - 1) // cols
    total_w = cols * VOTE_CELL_W
    start_x = (SCREEN_WIDTH - total_w) // 2
    skip_x = (SCREEN_WIDTH - VOTE_SKIP_W) // 2
    skip_y = VOTE_START_Y + rows * VOTE_CELL_H + 1
    return VoteGridLayout(cols=cols, rows=rows, start_x=start_x, skip_x=skip_x, skip_y=skip_y)


def vote_cell_origin(count: int, index: int) -> tuple[int, int]:
    """Screen-space top-left of the player cell at ``index``."""
    layout = vote_grid_layout(count)
    return (
        layout.start_x + (index % layout.cols) * VOTE_CELL_W,
        VOTE_START_Y + (index // layout.cols) * VOTE_CELL_H,
    )


# ---------------------------------------------------------------------------
# Slot / cursor parsing
# ---------------------------------------------------------------------------


def vote_skip_text_matches(
    frame: np.ndarray, font: PixelFont, skip_x: int, skip_y: int
) -> bool:
    """True when the SKIP label is visible within a small tolerance
    of its expected position.

    The voting screen sometimes shifts the SKIP label by 1-2 px
    between client frames; the Nim parser searches a ±2×±1 window
    to absorb that without re-running the full
    :func:`~modulabot.ascii.find_text` sweep. We copy that heuristic
    exactly.
    """
    if font.height <= 0:
        return False
    phrase_w = ascii_mod.text_width(font, "SKIP")
    for y in range(max(0, skip_y - 1), min(SCREEN_HEIGHT - font.height, skip_y + 1) + 1):
        x_lo = max(0, skip_x - 2)
        x_hi = min(SCREEN_WIDTH - phrase_w, skip_x + 2)
        for x in range(x_lo, x_hi + 1):
            if ascii_mod.text_matches(frame, font, "SKIP", x, y):
                return True
    return False


def parse_vote_slot(
    frame: np.ndarray, sprites: Sprites, count: int, index: int
) -> VoteSlot:
    """Parse one voting grid slot — colour and alive/dead.

    Tries the player sprite first; if that doesn't match, falls
    back to the body sprite (dead-player image). Returns
    :data:`VOTE_UNKNOWN` colour when neither matches — callers treat
    that as "not the voting screen at this count" and reject the
    candidate.
    """
    cx, cy = vote_cell_origin(count, index)
    sprite_x = cx + (VOTE_CELL_W - sprites.player.width) // 2
    sprite_y = cy + 1
    if matches_crewmate(frame, sprites.player, sprite_x, sprite_y, False):
        return VoteSlot(
            color_index=crewmate_color_index(
                frame, sprites.player, sprite_x, sprite_y, False
            ),
            alive=True,
        )
    if matches_actor_sprite(
        frame,
        sprites.body,
        sprite_x,
        sprite_y,
        False,
        max_misses=BODY_MAX_MISSES,
        min_stable_pixels=BODY_MIN_STABLE_PIXELS,
        min_tint_pixels=BODY_MIN_TINT_PIXELS,
    ):
        return VoteSlot(
            color_index=actor_color_index(
                frame, sprites.body, sprite_x, sprite_y, False
            ),
            alive=False,
        )
    return VoteSlot(color_index=VOTE_UNKNOWN, alive=False)


def vote_cell_selected(frame: np.ndarray, count: int, index: int) -> bool:
    """True when the cursor outline (palette index 2) brackets cell ``index``.

    Checks the full top edge (row above cell) and full bottom edge
    (row after cell) for cursor-colour pixels. We require both rows
    to be full cursor lines — the Nim parser does the same, which
    stops stray single-pixel artifacts from false-positiving.
    """
    cx, cy = vote_cell_origin(count, index)
    top_y = cy - 1
    bot_y = cy + VOTE_CELL_H - 2
    if top_y < 0 or bot_y >= SCREEN_HEIGHT:
        return False
    top = frame[top_y, cx : cx + VOTE_CELL_W]
    bot = frame[bot_y, cx : cx + VOTE_CELL_W]
    hits = int(np.count_nonzero(top == _CURSOR_COLOR)) + int(
        np.count_nonzero(bot == _CURSOR_COLOR)
    )
    return hits >= VOTE_CELL_W


def vote_skip_selected(frame: np.ndarray, skip_x: int, skip_y: int) -> bool:
    """True when the cursor outlines the SKIP option."""
    top_y = skip_y - 1
    bot_y = skip_y + 6
    if top_y < 0 or bot_y >= SCREEN_HEIGHT:
        return False
    top = frame[top_y, skip_x : skip_x + VOTE_SKIP_W]
    bot = frame[bot_y, skip_x : skip_x + VOTE_SKIP_W]
    hits = int(np.count_nonzero(top == _CURSOR_COLOR)) + int(
        np.count_nonzero(bot == _CURSOR_COLOR)
    )
    return hits >= VOTE_SKIP_W


def vote_self_marker_present(
    frame: np.ndarray, count: int, index: int, color_index: int
) -> bool:
    """True when the local-player marker sits above slot ``index``.

    The marker is a 2-pixel stamp above the cell at ``(cx+cellW//2-1, cy-2)``
    painted in the player's colour — or, for palette index 0 (black),
    a special cursor-colour pixel with a shadow so it's visible
    against the black background. Mirrors the ``voteSelfMarkerPresent``
    logic in Nim.
    """
    if color_index < 0 or color_index >= len(PLAYER_COLORS):
        return False
    cx, cy = vote_cell_origin(count, index)
    marker_x = cx + VOTE_CELL_W // 2 - 1
    marker_y = cy - 2
    if marker_y < 0 or marker_x < 0 or marker_x + 1 >= SCREEN_WIDTH:
        return False
    a = int(frame[marker_y, marker_x])
    b = int(frame[marker_y, marker_x + 1])
    color = int(PLAYER_COLORS[color_index])
    if color == _TEXT_BACKGROUND:
        # Black player: marker uses cursor-colour + VOTE_BLACK_MARKER shadow.
        return a == _CURSOR_COLOR and b == VOTE_BLACK_MARKER
    return a == color and b == color


# ---------------------------------------------------------------------------
# Vote-dot row parsing (other players' votes)
# ---------------------------------------------------------------------------


def vote_dot_color_index(frame: np.ndarray, x: int, y: int) -> int:
    """Return the PLAYER_COLORS index of the dot at ``(x, y)``, or
    :data:`VOTE_UNKNOWN` if the pixel is background or off-screen.

    Black-player dots are specially-encoded as cursor-colour next to
    a :data:`VOTE_BLACK_MARKER` shadow pixel — the same scheme
    :func:`vote_self_marker_present` uses, because black-on-black
    otherwise isn't visible.
    """
    if x < 0 or y < 0 or x >= SCREEN_WIDTH or y >= SCREEN_HEIGHT:
        return VOTE_UNKNOWN
    color = int(frame[y, x])
    if color == _CURSOR_COLOR and x > 0 and int(frame[y, x - 1]) == VOTE_BLACK_MARKER:
        return player_color_index(_TEXT_BACKGROUND)
    if color == _TEXT_BACKGROUND:
        return VOTE_UNKNOWN
    return player_color_index(color)


def parse_vote_dots_for_target(
    frame: np.ndarray, bot: Bot, target: int, dot_x: int, dot_y: int
) -> None:
    """Populate ``bot.voting.choices`` with voters who picked ``target``.

    Scans a compact 8-wide dot grid at the given top-left. For each
    visible colour dot, records that that player voted for
    ``target`` (a slot index, :data:`VOTE_SKIP`, or
    :data:`VOTE_UNKNOWN`). Ports ``parseVoteDotsForTarget`` in Nim
    — the Python port takes the frame explicitly so the internal
    parser doesn't have to reach into a Nim-style ``bot.io.unpacked``
    attribute.
    """
    v = bot.voting
    for row in range(MAX_PLAYERS):
        color_index = vote_dot_color_index(
            frame,
            dot_x + (row % 8) * 2,
            dot_y + (row // 8),
        )
        if 0 <= color_index < len(v.choices):
            v.choices[color_index] = target


# ---------------------------------------------------------------------------
# Chat text OCR
# ---------------------------------------------------------------------------


_LETTERS = set(string.ascii_letters)


def useful_chat_line(line: str) -> bool:
    """True when a parsed OCR line has real content.

    Definition matches ``usefulChatLine`` in Nim: at least 2 letters
    and at most half the characters are ``?`` (unknown-glyph
    placeholders). Keeps meaningless OCR garbage out of the chat
    cache without dropping partial reads of real chat.
    """
    letters = 0
    unknown = 0
    for ch in line:
        if ch in _LETTERS:
            letters += 1
        elif ch == "?":
            unknown += 1
    return letters >= 2 and unknown * 2 <= max(1, len(line))


def visible_chat_lines(
    frame: np.ndarray, font: PixelFont, count: int
) -> Iterator[tuple[int, str]]:
    """Yield ``(y, text)`` for each rendered chat line in row order.

    Sequential duplicates are collapsed and useless lines (failing
    :func:`useful_chat_line`) are skipped. Scan starts at
    ``chat_y + 1`` to match the sim's one-pixel top offset — see the
    matching note in ``voting.nim``'s iterator implementation.

    Python-specific fast path: rows whose chat column strip is
    entirely background are skipped without invoking
    :func:`~modulabot.ascii.read_run`. In the Nim version the
    ``framePixelOn`` early-exit inside ``glyphScore`` absorbs this
    cost, but Python's vectorised score pays full freight per
    ``best_glyph`` call (95 glyphs × O(glyph_pixels)). An 80-row
    empty chat region drops from ~700 ms to well under a millisecond
    with this gate.
    """
    layout = vote_grid_layout(count)
    chat_y = layout.skip_y + 10
    previous = ""
    # Precompute per-row "any text present" mask once; the cost is one
    # (chat_y+1 .. SCREEN_HEIGHT) strip compare.
    chat_strip = frame[chat_y + 1 : SCREEN_HEIGHT - 6, VOTE_CHAT_TEXT_X:]
    row_has_text = chat_strip.any(axis=1)
    for offset, any_text in enumerate(row_has_text.tolist()):
        if not any_text:
            continue
        y = chat_y + 1 + offset
        line = ascii_mod.read_run(
            frame, font, VOTE_CHAT_TEXT_X, y, VOTE_CHARS_PER_LINE
        )
        if not useful_chat_line(line):
            continue
        if line == previous:
            continue
        yield y, line
        previous = line


def vote_chat_speaker_at(
    frame: np.ndarray, sprites: Sprites, y: int
) -> int:
    """Return the PLAYER_COLORS index of the speaker-icon pip whose
    sprite top is at row ``y``, or :data:`VOTE_UNKNOWN` if no player
    sprite matches at the pip's fixed X column."""
    if y < 0 or y > SCREEN_HEIGHT - sprites.player.height:
        return VOTE_UNKNOWN
    if not matches_crewmate(frame, sprites.player, VOTE_CHAT_ICON_X, y, False):
        return VOTE_UNKNOWN
    idx = crewmate_color_index(
        frame, sprites.player, VOTE_CHAT_ICON_X, y, False
    )
    return idx if idx >= 0 else VOTE_UNKNOWN


def read_vote_chat_speakers(
    frame: np.ndarray, sprites: Sprites, count: int
) -> list[tuple[int, int]]:
    """Return a list of ``(sprite_top_y, color_index)`` for every
    visible speaker pip.

    Collapses consecutive Y rows inside a single sprite (``height /
    2`` pixels) so each pip contributes one entry. Order matches
    top-to-bottom render order, matching :func:`visible_chat_lines`
    so the pairing logic in :func:`vote_chat_speaker_for_line` works
    frame by frame.
    """
    layout = vote_grid_layout(count)
    chat_y = layout.skip_y + 10
    y_max = SCREEN_HEIGHT - sprites.player.height
    result: list[tuple[int, int]] = []
    if y_max < chat_y + 1:
        return result
    for y in range(chat_y + 1, y_max + 1):
        color_index = vote_chat_speaker_at(frame, sprites, y)
        if color_index == VOTE_UNKNOWN:
            continue
        if result and abs(result[-1][0] - y) < sprites.player.height // 2:
            continue
        result.append((y, color_index))
    return result


def vote_chat_speaker_for_line(
    speakers: Iterable[tuple[int, int]], text_y: int
) -> int:
    """Return the speaker PLAYER_COLORS index for a chat text line.

    Strategy matches the Nim ``voteChatSpeakerForLine`` exactly:
    prefer the pip at or above the text line (largest
    ``pip_y <= text_y``); fall back to the nearest pip below within
    :data:`VOTE_CHAT_SPEAKER_SEARCH` rows. The prefer-above bias
    handles the common single-line case and every
    middle-of-multi-line-message case; the below-fallback handles
    the first line of a wrapped message whose pip is centred below
    it.
    """
    best_above_y = -1 << 30
    best_above = VOTE_UNKNOWN
    best_below_y = 1 << 30
    best_below = VOTE_UNKNOWN
    for pip_y, color in speakers:
        if pip_y <= text_y:
            if pip_y > best_above_y:
                best_above_y = pip_y
                best_above = color
        else:
            if pip_y < best_below_y:
                best_below_y = pip_y
                best_below = color
    if best_above != VOTE_UNKNOWN and text_y - best_above_y <= VOTE_CHAT_SPEAKER_SEARCH:
        return best_above
    if best_below != VOTE_UNKNOWN and best_below_y - text_y <= VOTE_CHAT_SPEAKER_SEARCH:
        return best_below
    return VOTE_UNKNOWN


def normalize_chat_text(text: str) -> str:
    """Lowercase + collapse non-alphanumerics into single spaces.

    Used by :func:`chat_sus_color_index` to make the "sus <colour>"
    search robust to punctuation and whitespace drift. Matches the
    Nim ``normalizeChatText`` byte-for-byte so the sus heuristic
    emits the same colour on both ports given the same OCR output.
    """
    out: list[str] = []
    had_space = True
    for ch in text:
        if "A" <= ch <= "Z":
            ch = chr(ord(ch) - ord("A") + ord("a"))
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
            had_space = False
        elif not had_space:
            out.append(" ")
            had_space = True
    return "".join(out).strip()


def _span_gap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Inclusive-on-start/exclusive-on-end gap between two spans.
    Zero when they overlap. Matches ``spanGap`` in Nim."""
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def chat_sus_color_index(text: str) -> int:
    """Return the player-colour index called "sus" most prominently
    in ``text``, or :data:`VOTE_UNKNOWN` if no sus-call parses.

    For each ``(colour, "sus")`` pair the parser picks the pairing
    with the latest "sus" position, then the smallest gap to the
    colour mention, then the longer colour name (so "light blue"
    wins over "blue" in "light blue sus"). Matches the Nim
    tie-break order precisely — this is important because the
    imposter-bandwagon branch of the decision policy reads it
    directly.
    """
    padded = " " + normalize_chat_text(text) + " "
    sus_needle = " sus "
    best_sus = -1
    best_gap = 1 << 30
    best_len = -1
    winner = VOTE_UNKNOWN
    for color_index, name in enumerate(PLAYER_COLOR_NAMES):
        color_needle = " " + normalize_chat_text(name) + " "
        if not color_needle.strip():
            continue
        color_pos = padded.find(color_needle)
        while color_pos >= 0:
            color_start = color_pos + 1
            color_end = color_pos + len(color_needle) - 1
            color_len = color_end - color_start
            sus_pos = padded.find(sus_needle)
            while sus_pos >= 0:
                sus_start = sus_pos + 1
                sus_end = sus_pos + len(sus_needle) - 1
                gap = _span_gap(color_start, color_end, sus_start, sus_end)
                if gap <= VOTE_CHARS_PER_LINE * 2 and (
                    sus_start > best_sus
                    or (sus_start == best_sus and gap < best_gap)
                    or (sus_start == best_sus and gap == best_gap and color_len > best_len)
                ):
                    best_sus = sus_start
                    best_gap = gap
                    best_len = color_len
                    winner = color_index
                sus_pos = padded.find(sus_needle, sus_pos + 1)
            color_pos = padded.find(color_needle, color_pos + 1)
    return winner


def read_vote_chat_text(
    frame: np.ndarray, font: PixelFont, count: int
) -> str:
    """Concatenated OCR of the voting chat region, space-separated.

    Used by :func:`chat_sus_color_index` and stashed on
    ``bot.voting.chat_text`` for the trace writer.
    """
    parts: list[str] = []
    for _, line in visible_chat_lines(frame, font, count):
        parts.append(line)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------


def parse_voting_candidate(
    bot: Bot,
    sprites: Sprites,
    font: PixelFont,
    frame: np.ndarray,
    count: int,
    start_tick: int,
) -> bool:
    """Try to parse the voting screen for a specific player count.

    Returns ``True`` and populates ``bot.voting.*`` when every slot
    resolves to a player / body sprite whose colour index matches
    its slot index — the strict invariant that makes "this isn't
    the voting screen" the only failure mode.

    Doesn't mutate ``bot.voting`` on failure, so callers can retry
    other player counts without worrying about partial writes.
    """
    layout = vote_grid_layout(count)
    if not vote_skip_text_matches(frame, font, layout.skip_x, layout.skip_y):
        return False

    # Strict slot check: every slot's parsed colour index must match
    # its slot index. If anything mismatches, abort without touching
    # state.
    parsed: list[VoteSlot] = []
    for i in range(count):
        slot = parse_vote_slot(frame, sprites, count, i)
        if slot.color_index == VOTE_UNKNOWN or slot.color_index != i:
            return False
        parsed.append(slot)

    clear_voting_state(bot)
    v = bot.voting
    v.active = True
    v.player_count = count
    v.start_tick = start_tick

    for i in range(count):
        v.slots[i] = parsed[i]
        if parsed[i].alive and vote_cell_selected(frame, count, i):
            v.cursor = i
        if vote_self_marker_present(frame, count, i, parsed[i].color_index):
            v.self_slot = i
            bot.identity.self_color = parsed[i].color_index
        cx, cy = vote_cell_origin(count, i)
        parse_vote_dots_for_target(
            frame,
            bot,
            i,
            cx + 1,
            cy + sprites.player.height + 2,
        )

    if vote_skip_selected(frame, layout.skip_x, layout.skip_y):
        v.cursor = count
    parse_vote_dots_for_target(
        frame,
        bot,
        VOTE_SKIP,
        layout.skip_x + VOTE_SKIP_W + 2,
        layout.skip_y,
    )

    # Chat OCR + speaker attribution.
    speakers = read_vote_chat_speakers(frame, sprites, count)
    v.chat_lines = []
    parts: list[str] = []
    for y, text in visible_chat_lines(frame, font, count):
        speaker = vote_chat_speaker_for_line(speakers, y)
        v.chat_lines.append(VoteChatLine(speaker_color=speaker, y=y, text=text))
        parts.append(text)
    v.chat_text = " ".join(parts)
    v.chat_sus_color = chat_sus_color_index(v.chat_text)
    return True


def parse_voting_screen(
    bot: Bot,
    sprites: Sprites,
    font: PixelFont,
    frame: np.ndarray,
    tick: int,
) -> bool:
    """Parse the voting interstitial if it is currently visible.

    Iterates candidate player counts from :data:`MAX_PLAYERS` down to
    1, returning True as soon as one validates. If no count validates,
    resets the voting sub-record (clearing stale state) and returns
    False.

    ``tick`` is recorded as ``start_tick`` on the first frame of a
    new meeting; subsequent frames during the same meeting preserve
    the earlier tick so the listen timer in the decision policy
    counts from meeting start, not the current frame.
    """
    v = bot.voting
    start_tick = v.start_tick if v.active and v.start_tick >= 0 else tick
    for count in range(MAX_PLAYERS, 0, -1):
        if parse_voting_candidate(bot, sprites, font, frame, count, start_tick):
            return True
    clear_voting_state(bot)
    return False


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------


def vote_slot_for_color(bot: Bot, color_index: int) -> int:
    """Return the slot index holding ``color_index``, or
    :data:`VOTE_UNKNOWN`."""
    v = bot.voting
    for i in range(v.player_count):
        if v.slots[i].color_index == color_index:
            return i
    return VOTE_UNKNOWN


def vote_target_name(bot: Bot, target: int) -> str:
    """Human-readable name for a vote target. ``"skip"`` for
    :data:`VOTE_SKIP`, the colour name for a slot index, otherwise
    ``"unknown"``."""
    if target == VOTE_SKIP:
        return "skip"
    v = bot.voting
    if 0 <= target < v.player_count:
        ci = v.slots[target].color_index
        if 0 <= ci < len(PLAYER_COLOR_NAMES):
            return PLAYER_COLOR_NAMES[ci]
    return "unknown"


def self_vote_choice(bot: Bot) -> int:
    """Return the parsed vote choice for the local player.

    :data:`VOTE_UNKNOWN` if we haven't resolved our own colour yet
    or if no dot has been observed next to our name. Consulted by
    the decision policy to short-circuit after we've already voted
    (the voting UI can't un-vote so retrying is never useful).
    """
    v = bot.voting
    self_color = bot.identity.self_color
    if 0 <= self_color < len(v.choices):
        return v.choices[self_color]
    if 0 <= v.self_slot < v.player_count:
        ci = v.slots[v.self_slot].color_index
        if 0 <= ci < len(v.choices):
            return v.choices[ci]
    return VOTE_UNKNOWN


# ---------------------------------------------------------------------------
# Cursor stepping (used by the decision policy)
# ---------------------------------------------------------------------------


def next_vote_selectable(bot: Bot, cursor: int, direction: int) -> int:
    """Advance the voting cursor by one step in ``direction`` (±1),
    skipping dead slots.

    The cursor wraps through ``[0, player_count]`` inclusive, where
    ``player_count`` is the SKIP option. Dead slots (``slots[i].alive
    == False``) are skipped so stepping never lands on a body cell.
    Returns :data:`VOTE_UNKNOWN` when no selectable position exists.
    """
    v = bot.voting
    total = v.player_count + 1  # +1 for the SKIP slot
    if total <= 0:
        return VOTE_UNKNOWN
    cur = cursor
    for _ in range(total):
        cur = (cur + direction + total) % total
        if cur == v.player_count:
            return cur
        if 0 <= cur < v.player_count and v.slots[cur].alive:
            return cur
    return VOTE_UNKNOWN


def vote_steps_to(bot: Bot, target: int, direction: int) -> int:
    """Steps the cursor would take to reach ``target`` in
    ``direction``, or :data:`sys.maxsize` on failure.

    Counts SKIP + dead-slot hops correctly via
    :func:`next_vote_selectable`. Returns a huge sentinel instead of
    raising so the cursor-direction picker can always compare left
    vs. right counts with ``min``.
    """
    v = bot.voting
    if v.cursor == VOTE_UNKNOWN:
        return 1 << 30
    cur = v.cursor
    for step in range(v.player_count + 2):
        if cur == target:
            return step
        cur = next_vote_selectable(bot, cur, direction)
        if cur == VOTE_UNKNOWN:
            return 1 << 30
    return 1 << 30


def vote_move_direction(bot: Bot, target: int) -> int:
    """Return ``-1`` to step left or ``+1`` to step right toward
    ``target``.

    Picks whichever direction produces fewer steps; ties go right
    (matches Nim). Callers should translate the return value into
    :data:`~modulabot.actions.LEFT` / :data:`~modulabot.actions.RIGHT`.
    """
    left_steps = vote_steps_to(bot, target, -1)
    right_steps = vote_steps_to(bot, target, 1)
    return -1 if left_steps < right_steps else 1


__all__ = [
    "VOTE_UNKNOWN",
    "VOTE_SKIP",
    "MAX_PLAYERS",
    "VOTE_CELL_W",
    "VOTE_CELL_H",
    "VOTE_START_Y",
    "VOTE_SKIP_W",
    "VOTE_BLACK_MARKER",
    "VOTE_CHAT_ICON_X",
    "VOTE_CHAT_TEXT_X",
    "VOTE_CHARS_PER_LINE",
    "VOTE_CHAT_SPEAKER_SEARCH",
    "VoteGridLayout",
    "clear_voting_state",
    "vote_grid_layout",
    "vote_cell_origin",
    "vote_skip_text_matches",
    "parse_vote_slot",
    "vote_cell_selected",
    "vote_skip_selected",
    "vote_self_marker_present",
    "vote_dot_color_index",
    "parse_vote_dots_for_target",
    "useful_chat_line",
    "visible_chat_lines",
    "vote_chat_speaker_at",
    "read_vote_chat_speakers",
    "vote_chat_speaker_for_line",
    "normalize_chat_text",
    "chat_sus_color_index",
    "read_vote_chat_text",
    "parse_voting_candidate",
    "parse_voting_screen",
    "vote_slot_for_color",
    "vote_target_name",
    "self_vote_choice",
    "next_vote_selectable",
    "vote_steps_to",
    "vote_move_direction",
]
