"""Among Them summarizer reporter.

Reports only facts the reporter can read or derive without
inference. Specifically removed (after phase 5):
  - The `likely_dead` inference and its ghost-glyph rendering. Whether
    a slot was killed or alive at episode end is not recoverable from
    the binary replay or the results JSON without a richer game-side
    events file; the reporter no longer guesses.
  - The meetings card and `estimate_meetings`. The same constraint
    applies — meetings called, ballots cast, transcripts spoken all
    live in the game's stdout text, not in the artifacts the reporter
    sees. The per-slot `vote_players` / `vote_skip` / `vote_timeout`
    counts remain in the scoreboard (those *are* facts from the
    results JSON).

Inline CSS only; no `<script>`, no `<link>`. The page renders inside
Observatory's iframe+CSP sandbox without external fetches.

The output zip contains:

    report.zip
    ├── manifest.json       # canonical: {reporter_id, render, event_log}
    ├── summary.html        # render target (flagged by manifest.json `render`)
    ├── stats.json          # auxiliary; full per-slot detail
    └── events.parquet      # event log; shared (ts, player, key, value) schema

See DESIGN.md for the full phase plan and decisions.

The inline primitives in this file (`BundleReader`, `ReporterInputs`,
`read_uri` / `write_uri`, `write_deterministic_zip`, the parquet writer)
are SDK-extraction candidates — once `reporter_sdk` lands, they'll be
lifted out and this file will import them instead.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import time
import urllib.parse
import zipfile
from html import escape as html_escape
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import requests
from pydantic import BaseModel, Field

# The reporter's self-identifying id, stamped into the output zip's
# `manifest.json` `reporter_id` field. Conventionally matches the runnable's
# `id` in `manifest.reporter[]`.
REPORTER_ID = "among-them-summarizer"


# ---------- inline primitives (SDK extraction candidates) ----------


class ReporterInputs(BaseModel):
    episode_bundle_uri: str
    report_uri: str


def load_reporter_inputs() -> ReporterInputs:
    return ReporterInputs(
        episode_bundle_uri=os.environ["COGAME_EPISODE_BUNDLE_URI"],
        report_uri=os.environ["COGAME_REPORT_URI"],
    )


_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
_HTTP_MAX_ATTEMPTS = 5


def _file_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def read_uri(uri: str) -> bytes:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        return _file_path_from_uri(uri).read_bytes()
    if scheme in ("http", "https"):
        return _http_request_with_retry("GET", uri).content
    raise ValueError(f"unsupported URI scheme {scheme!r} for read: {uri}")


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        path = _file_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    if scheme in ("http", "https"):
        _http_request_with_retry(
            "PUT", uri, data=payload, headers={"Content-Type": content_type}
        )
        return
    raise ValueError(f"unsupported URI scheme {scheme!r} for write: {uri}")


def _http_request_with_retry(
    method: str,
    uri: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    delay = 0.5
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        resp = requests.request(method, uri, data=data, headers=headers, timeout=30)
        if resp.status_code < 400:
            return resp
        if (
            resp.status_code not in _HTTP_RETRY_STATUSES
            or attempt == _HTTP_MAX_ATTEMPTS
        ):
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")  # loop above either returns or raises


def read_json(uri: str) -> Any:
    return json.loads(read_uri(uri).decode("utf-8"))


class BundleInnerManifest(BaseModel):
    """The `manifest.json` at the root of every episode bundle zip.

    Schema mirrors metta's `EPISODE_BUNDLE_README.md`: `ereq_id`, `status`,
    `include` (tokens actually delivered after access-control filtering),
    `files` (token -> path-in-zip for single-file tokens; dict for multi-file
    tokens like `game_logs`). `extra="allow"` so forward-extension fields
    (e.g. an `episode_id`/`variant_id` carrier the metta bundler may add)
    don't trip validation.
    """

    ereq_id: str
    status: str = "success"
    include: list[str] = Field(default_factory=list)
    files: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class BundleReader:
    """Opens an episode bundle zip from a URI, parses its inner
    `manifest.json`, and exposes typed accessors for its named tokens.

    Tokens map to entries inside the zip via `manifest.json::files`.
    `read_bytes`/`read_json` require the token; `*_optional` variants
    return `None` when the token isn't in `manifest.include` (so callers
    can transparently handle access-controlled bundles where a token may
    have been filtered out). Among Them reads the `replay` token via
    `read_bytes` because the entry's bytes are the binary `.bitreplay`
    payload, not JSON.
    """

    def __init__(self, bundle_uri: str) -> None:
        self._bytes = read_uri(bundle_uri)
        self._zf = zipfile.ZipFile(io.BytesIO(self._bytes))
        raw = json.loads(self._zf.read("manifest.json"))
        self._manifest = BundleInnerManifest.model_validate(raw)

    def inner_manifest(self) -> BundleInnerManifest:
        return self._manifest

    def _token_path(self, token: str) -> str:
        path = self._manifest.files.get(token)
        if path is None:
            raise KeyError(f"bundle has no entry for token {token!r}")
        if not isinstance(path, str):
            raise TypeError(
                f"token {token!r} maps to a multi-file entry ({type(path).__name__}); "
                "this reader only handles single-file tokens"
            )
        return path

    def read_bytes(self, token: str) -> bytes:
        return self._zf.read(self._token_path(token))

    def read_bytes_optional(self, token: str) -> bytes | None:
        if token not in self._manifest.include:
            return None
        return self.read_bytes(token)

    def read_json(self, token: str) -> Any:
        return json.loads(self.read_bytes(token))

    def read_json_optional(self, token: str) -> Any | None:
        raw = self.read_bytes_optional(token)
        return None if raw is None else json.loads(raw)

    def close(self) -> None:
        self._zf.close()

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# Pinned zip-entry mtime for byte-identical determinism.
_DETERMINISTIC_ZIP_MTIME = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a zip with pinned mtimes for byte-identical reruns.

    Determinism is preferred but not required by the canonical reporter
    contract; this reporter opts in.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=_DETERMINISTIC_ZIP_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buf.getvalue()


def _stable_json(obj: Any) -> str:
    """Sorted-key compact JSON encoding for byte-identical reruns."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# Shared event-log schema. Same shape as paint_arena_summarizer's
# EVENT_LOG_SCHEMA — a deliberate alignment so future cross-reporter
# aggregation can use one columnar source. `player = -1` denotes a
# global / episode-level fact.
EVENT_LOG_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64()),
        pa.field("player", pa.int64()),
        pa.field("key", pa.string()),
        pa.field("value", pa.string()),
    ]
)


def write_events_parquet(rows: list[dict[str, Any]]) -> bytes:
    """Encode event-log rows to Parquet bytes using EVENT_LOG_SCHEMA.

    Determinism: the pyarrow `created_by` footer string includes the
    pyarrow version. The Docker image pins `pyarrow` in
    requirements.txt, so two runs of the *same image* over identical
    inputs produce byte-identical parquet bytes.
    """
    if rows:
        table = pa.table(
            {
                "ts": pa.array([r["ts"] for r in rows], type=pa.int64()),
                "player": pa.array([r["player"] for r in rows], type=pa.int64()),
                "key": pa.array([r["key"] for r in rows], type=pa.string()),
                "value": pa.array([r["value"] for r in rows], type=pa.string()),
            },
            schema=EVENT_LOG_SCHEMA,
        )
    else:
        table = EVENT_LOG_SCHEMA.empty_table()
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="snappy",
        row_group_size=max(len(rows), 1),
    )
    return buf.getvalue()


# ---------- Among Them constants ----------

REPLAY_FPS = 24
GAME_NAME = "among_them"
SUPPORTED_REPLAY_FORMAT_VERSION = 3
REPLAY_MAGIC = b"BITWORLD"

# Record-type bytes from `among_them/sim.nim:14-17`.
_RECORD_TICK_HASH = 0x01
_RECORD_INPUT = 0x02
_RECORD_JOIN = 0x03
_RECORD_LEAVE = 0x04

# Disconnect classification threshold: a leave more than this many ticks
# before the last hash tick is treated as a genuine mid-game disconnect.
# Matches the design's "5 s before end" rule.
_DISCONNECT_GRACE_TICKS = REPLAY_FPS * 5

# Input bitmask layout (mirrors `common/protocol.nim:18-24`).
BUTTONS: tuple[tuple[str, int], ...] = (
    ("up", 0x01),
    ("down", 0x02),
    ("left", 0x04),
    ("right", 0x08),
    ("select", 0x10),
    ("attack", 0x20),
    ("b", 0x40),
)
BUTTON_NAMES: tuple[str, ...] = tuple(name for name, _ in BUTTONS)

# Activity-bucket width in ticks (10 s at 24 fps). At ~10 s per bucket,
# a default 10000-tick episode produces ~40 buckets — enough resolution
# to draw an intensity sparkline without flooding the parquet.
ACTIVITY_BUCKET_TICKS = REPLAY_FPS * 10


def tick_from_ms(ms: int) -> int:
    """Convert a replay millisecond timestamp to a simulation tick.

    Mirrors `among_them/replays.nim:56-58::tickTime` in reverse:
    `tick = ms * ReplayFps // 1000`. Integer floor so the tick of a
    fractional-millisecond timestamp falls on the earlier frame.
    """
    return (ms * REPLAY_FPS) // 1000


# Mirror of `among_them/sim.nim:123-140`. Index = color slot assigned by
# the game; same order the game uses for auto-assignment.
PLAYER_COLOR_NAMES = [
    "red",
    "orange",
    "yellow",
    "light blue",
    "pink",
    "lime",
    "blue",
    "pale blue",
    "gray",
    "white",
    "dark brown",
    "brown",
    "dark teal",
    "green",
    "dark navy",
    "black",
]

# Phase-5 hex codes for the 16 in-game color names. These are CSS
# stand-ins for the game's actual paletted colors (the game uses a
# 16-color indexed framebuffer); they're picked for accessible contrast
# on a white-card background so the scoreboard swatch unambiguously
# identifies the slot's in-game color. Order is intentional: keys
# match PLAYER_COLOR_NAMES one-for-one.
AMONG_THEM_COLORS: dict[str, str] = {
    "red": "#e63946",
    "orange": "#f08a3e",
    "yellow": "#f4c430",
    "light blue": "#7fc7ff",
    "pink": "#f4a8c8",
    "lime": "#a3e635",
    "blue": "#1d4ed8",
    "pale blue": "#c8e0ff",
    "gray": "#8c97a3",
    "white": "#f1f3f5",
    "dark brown": "#5b3a1f",
    "brown": "#9c6b3c",
    "dark teal": "#0f766e",
    "green": "#16a34a",
    "dark navy": "#0b1e3f",
    "black": "#1a1a1a",
}


# ---------- input models ----------


class AmongThemResults(BaseModel):
    """Mirror of the results_schema in `among_them/coworld_manifest.json`.

    Only `scores` is required by the schema; all other arrays are
    optional but expected in any realistic Among Them episode.
    """

    scores: list[float]
    names: list[str | None] | None = None
    win: list[bool] | None = None
    tasks: list[int] | None = None
    kills: list[int] | None = None
    imposter: list[int] | None = None
    crew: list[int] | None = None
    vote_players: list[int] | None = None
    vote_skip: list[int] | None = None
    vote_timeout: list[int] | None = None

    @property
    def slot_count(self) -> int:
        return len(self.scores)


class PlayerMetadata(BaseModel):
    slot: int
    policy_name: str | None = None
    policy_version_id: str | None = None


class EpisodeMetadata(BaseModel):
    """Episode-level metadata used to populate `stats.json` and the HTML
    header. The canonical reporter contract (metta `docs/roles/reporter.md`)
    does not formally carry these fields in the bundle's inner `manifest.json`;
    in practice they reach the reporter via the bundle's optional `metadata`
    token. When that token is absent, every field falls back to a default."""

    episode_id: str | None = None
    variant_id: str = "unknown"
    duration_seconds: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    players: list[PlayerMetadata] = Field(default_factory=list)


class PlayerSlotConfig(BaseModel):
    """Per-slot configuration that may appear in the replay's
    `configJson.slots[i]` (mirrors `sim.nim::PlayerSlotConfig`). All
    fields are optional — the game only writes the ones the operator
    explicitly set.
    """

    name: str | None = None
    color: str | None = None  # color name, e.g. "red", "light blue"
    role: str | None = None

    model_config = {"extra": "ignore"}


class GameConfig(BaseModel):
    """The subset of `among_them/sim.nim::GameConfig` this reporter
    consumes. Other fields in the replay's configJson are ignored.
    Names match the JSON keys the game writes (camelCase in the source);
    the field aliases here map them to Python snake_case.
    """

    min_players: int = Field(8, alias="minPlayers")
    imposter_count: int = Field(2, alias="imposterCount")
    auto_imposter_count: bool = Field(False, alias="autoImposterCount")
    tasks_per_player: int = Field(8, alias="tasksPerPlayer")
    kill_cooldown_ticks: int = Field(900, alias="killCooldownTicks")
    vote_timer_ticks: int = Field(6000, alias="voteTimerTicks")
    max_ticks: int = Field(10000, alias="maxTicks")
    seed: int | None = None
    map_path: str | None = Field(None, alias="mapPath")
    slots: list[PlayerSlotConfig] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "ignore"}


# ---------- output models ----------


class VerdictBlock(BaseModel):
    winner_side: str  # "Imposter" | "Crewmate" | "Draw"
    time_limit_reached: bool
    any_winner: bool


class SlotStats(BaseModel):
    """Per-slot summary.

    `join_order` is the connection-order index this slot was assigned
    to at join time (the `ReplayJoinRecord.player` field — the index
    into `sim.players` at the moment of join). `slot` is the
    tournament/results-JSON slot index. The two differ when the game
    auto-assigns slots or when a player joins out-of-order; downstream
    ingesters that want the connection-order ↔ slot mapping read
    `join_order` here or filter the `join` events in events.parquet.
    `None` when no join record exists for this slot.
    """

    slot: int
    join_order: int | None
    policy_name: str
    in_game_name: str | None
    color_index: int | None
    color_name: str | None
    role: str | None  # "Imposter" | "Crewmate" | None
    won: bool
    score: float
    kills: int
    tasks: int
    tasks_assigned: int
    vote_players: int
    vote_skip: int
    vote_timeout: int
    joined_tick: int
    left_tick: int | None
    input_press_total: int | None = None
    input_press_per_kind: dict[str, int] | None = None


class Disconnect(BaseModel):
    slot: int
    leave_tick: int
    leave_seconds: float | None


class InputPress(BaseModel):
    """One newly-set edge (0→1 transition) of one button by one slot."""

    tick: int
    slot: int
    button: str  # one of BUTTON_NAMES


class ActivityBucket(BaseModel):
    """Per-slot, per-time-bucket aggregate of edge-detected presses.

    Buckets are aligned to multiples of `ACTIVITY_BUCKET_TICKS` from
    tick 0. Empty buckets (no presses) are not represented.
    """

    slot: int
    bucket_start_tick: int
    bucket_ticks: int
    presses_total: int
    presses_by_button: dict[str, int]


class ActivityPerSlot(BaseModel):
    """The activity-strip data for one slot. The list is dense over the
    range [first non-empty bucket, last non-empty bucket]; empty
    interior buckets carry 0 so the HTML can render a continuous bar
    sequence without gaps.
    """

    slot: int
    presses_per_bucket: list[int]


class ActivityBlock(BaseModel):
    bucket_ticks: int
    buckets_per_slot: list[ActivityPerSlot]


class AmongThemStats(BaseModel):
    """Top-level stats blob.

    `slot_to_join_order` is a convenience array indexed by slot, where
    each entry is the connection-order index that joined into that slot
    (or `None` if no join record exists for the slot). The same mapping
    is available row-by-row via `slots[i].join_order`; this top-level
    field is a flat view for downstream ingesters that just want the
    mapping. The full granular event data lives in
    `events.parquet`'s `join` rows.
    """

    episode_id: str | None
    variant_id: str
    duration_seconds: float | None
    total_ticks: int | None
    replay_fps: int
    game_version: str
    config: GameConfig
    verdict: VerdictBlock
    slots: list[SlotStats]
    slot_to_join_order: list[int | None]
    disconnects: list[Disconnect]
    activity: ActivityBlock


class BitReplayHeader(BaseModel):
    game_name: str
    game_version: str
    format_version: int
    timestamp_ms: int
    config: GameConfig

    model_config = {"arbitrary_types_allowed": True}


class ReplayJoin(BaseModel):
    """A `ReplayJoinRecord` (0x03). `slot < 0` means the game
    auto-assigned the slot at runtime; we treat it as "slot unknown
    from the replay alone." `token_present` is the only token-related
    field that ever surfaces in outputs (the token string itself is
    parsed and immediately dropped — see DESIGN.md decision #9).
    """

    time_ms: int
    player: int
    name: str
    slot: int
    token_present: bool


class ReplayLeave(BaseModel):
    """A `ReplayLeaveRecord` (0x04). The `player` field is the index
    into `sim.players` at the time of the leave, which shifts as
    earlier leaves remove entries from that array."""

    time_ms: int
    player: int


class ReplayInput(BaseModel):
    """A `ReplayInputRecord` (0x02). `keys` is the 7-bit button bitmask
    from `common/protocol.nim:18-24`."""

    time_ms: int
    player: int
    keys: int


class ReplayHash(BaseModel):
    """A `ReplayTickHashRecord` (0x01). The reporter uses `tick` only;
    the `hash` is for game-side replay verification."""

    tick: int
    hash: int


class BitReplay(BaseModel):
    header: BitReplayHeader
    joins: list[ReplayJoin]
    leaves: list[ReplayLeave]
    inputs: list[ReplayInput]
    hashes: list[ReplayHash]

    @property
    def last_tick(self) -> int:
        return self.hashes[-1].tick if self.hashes else 0


# ---------- bitreplay header parser ----------


def _read_u8(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 1 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return data[offset], offset + 1


def _read_u16(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def _read_i16(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<h", data, offset)[0], offset + 2


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_u64(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<Q", data, offset)[0], offset + 8


def _read_str(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = _read_u16(data, offset)
    if offset + length > len(data):
        raise ValueError(f"bitreplay string truncated at offset {offset}")
    return data[offset : offset + length].decode("utf-8"), offset + length


def _parse_bitreplay_header(data: bytes) -> tuple[BitReplayHeader, int]:
    """Parse a `.bitreplay` v3 header; return the header and the byte
    offset of the first record."""
    if len(data) < len(REPLAY_MAGIC):
        raise ValueError(f"bitreplay too short for magic ({len(data)} bytes)")
    if data[: len(REPLAY_MAGIC)] != REPLAY_MAGIC:
        raise ValueError(f"unexpected bitreplay magic: {data[:8]!r}")
    offset = len(REPLAY_MAGIC)
    format_version, offset = _read_u16(data, offset)
    if format_version != SUPPORTED_REPLAY_FORMAT_VERSION:
        raise ValueError(
            f"unsupported bitreplay format version {format_version} "
            f"(this reporter supports version {SUPPORTED_REPLAY_FORMAT_VERSION})"
        )
    game_name, offset = _read_str(data, offset)
    if game_name != GAME_NAME:
        raise ValueError(
            f"unexpected game name in bitreplay: {game_name!r} (expected {GAME_NAME!r})"
        )
    game_version, offset = _read_str(data, offset)
    timestamp_ms, offset = _read_u64(data, offset)
    config_json, offset = _read_str(data, offset)
    config = GameConfig.model_validate(json.loads(config_json))
    header = BitReplayHeader(
        game_name=game_name,
        game_version=game_version,
        format_version=format_version,
        timestamp_ms=timestamp_ms,
        config=config,
    )
    return header, offset


def parse_bitreplay_header(data: bytes) -> BitReplayHeader:
    """Parse just the header of a `.bitreplay` v3 file (drops record
    parsing). Retained for callers that only need the game config.

    Layout (`among_them/replays.nim:148-161`):

        magic (8B "BITWORLD") | format_version (u16) |
        game_name (u16+utf8)  | game_version (u16+utf8) |
        timestamp_ms (u64)    | config_json (u16+utf8)

    Refuses anything that isn't `BITWORLD` + format-version 3 + game-name
    `among_them`.
    """
    header, _ = _parse_bitreplay_header(data)
    return header


def parse_bitreplay(data: bytes) -> BitReplay:
    """Parse a full `.bitreplay` v3 file: header + every record type.

    Record dispatch table (`among_them/sim.nim:14-17`):
      0x01 tick-hash   — u32 tick, u64 hash
      0x02 input       — u32 time_ms, u8 player, u8 keys
      0x03 join        — u32 time_ms, u8 player, str name, i16 slot, str token
      0x04 leave       — u32 time_ms, u8 player

    Refuses unknown record bytes with a `ValueError`. Truncated records
    surface the same way the per-field readers already raise (truncation
    at offset N).

    The `token` string in each join is read because the binary format
    requires reading it (the length-prefix must be consumed to advance
    the cursor) but is never stored on the returned object — only the
    derived `token_present: bool` survives.
    """
    header, offset = _parse_bitreplay_header(data)
    joins: list[ReplayJoin] = []
    leaves: list[ReplayLeave] = []
    inputs: list[ReplayInput] = []
    hashes: list[ReplayHash] = []
    while offset < len(data):
        record_type, offset = _read_u8(data, offset)
        if record_type == _RECORD_TICK_HASH:
            tick, offset = _read_u32(data, offset)
            hash_value, offset = _read_u64(data, offset)
            hashes.append(ReplayHash(tick=tick, hash=hash_value))
        elif record_type == _RECORD_INPUT:
            time_ms, offset = _read_u32(data, offset)
            player, offset = _read_u8(data, offset)
            keys, offset = _read_u8(data, offset)
            inputs.append(ReplayInput(time_ms=time_ms, player=player, keys=keys))
        elif record_type == _RECORD_JOIN:
            time_ms, offset = _read_u32(data, offset)
            player, offset = _read_u8(data, offset)
            name, offset = _read_str(data, offset)
            slot, offset = _read_i16(data, offset)
            token, offset = _read_str(data, offset)
            joins.append(
                ReplayJoin(
                    time_ms=time_ms,
                    player=player,
                    name=name,
                    slot=slot,
                    token_present=bool(token),
                )
            )
        elif record_type == _RECORD_LEAVE:
            time_ms, offset = _read_u32(data, offset)
            player, offset = _read_u8(data, offset)
            leaves.append(ReplayLeave(time_ms=time_ms, player=player))
        else:
            raise ValueError(
                f"unknown bitreplay record type 0x{record_type:02x} at offset "
                f"{offset - 1}"
            )
    return BitReplay(
        header=header, joins=joins, leaves=leaves, inputs=inputs, hashes=hashes
    )


# ---------- verdict + meetings + slot stats ----------


def derive_verdict(results: AmongThemResults) -> VerdictBlock:
    """Derive Imposter / Crewmate / Draw from the results-JSON `win`
    + `imposter` + `crew` arrays.

    The sim sets every `win[i]` to `False` when the game ended via
    `timeLimitReached` (see `sim.nim:3217-3228::finishGame`), so a
    "no winners" results blob is the canonical draw signal.
    """
    win = results.win or []
    imposter = results.imposter or []
    crew = results.crew or []
    n = results.slot_count

    imposter_won = any(
        i < len(imposter) and imposter[i] == 1 and i < len(win) and win[i]
        for i in range(n)
    )
    crewmate_won = any(
        i < len(crew) and crew[i] == 1 and i < len(win) and win[i] for i in range(n)
    )
    any_winner = imposter_won or crewmate_won
    if imposter_won and not crewmate_won:
        winner_side = "Imposter"
    elif crewmate_won and not imposter_won:
        winner_side = "Crewmate"
    else:
        winner_side = "Draw"
    return VerdictBlock(
        winner_side=winner_side,
        time_limit_reached=not any_winner,
        any_winner=any_winner,
    )


def _resolve_policy_name(
    slot: int,
    results_names: list[str | None] | None,
    metadata_policy_by_slot: dict[int, str | None],
) -> str:
    """Three-step display-name fallback (DESIGN.md decision #4).

    1. `policy_name` from episode metadata (tournament-meaningful).
    2. `results.names[i]` (the in-game player address — may be a
       string like "red" or a connection address).
    3. `"Slot N"`.
    """
    p = metadata_policy_by_slot.get(slot)
    if p:
        return p
    if results_names and slot < len(results_names) and results_names[slot]:
        return results_names[slot]  # type: ignore[return-value]
    return f"Slot {slot}"


def _slot_role(
    slot: int, imposter: list[int] | None, crew: list[int] | None
) -> str | None:
    if imposter and slot < len(imposter) and imposter[slot] == 1:
        return "Imposter"
    if crew and slot < len(crew) and crew[slot] == 1:
        return "Crewmate"
    return None


def _resolve_color(slot: int, config: GameConfig) -> tuple[int | None, str | None]:
    """Map a slot index to (color_index, color_name).

    Preference: `config.slots[slot].color` when set; otherwise the
    positional fallback `PLAYER_COLOR_NAMES[slot % 16]`. The positional
    fallback only matches the in-game color when no fixed-color slot
    config was set — see DESIGN.md §"Color from join slot config, with
    a fallback palette".
    """
    if slot < 0:
        return None, None
    if slot < len(config.slots):
        configured = config.slots[slot].color
        if configured:
            if configured in PLAYER_COLOR_NAMES:
                return PLAYER_COLOR_NAMES.index(configured), configured
            # Unknown color name in config — surface the name but no index.
            return None, configured
    idx = slot % len(PLAYER_COLOR_NAMES)
    return idx, PLAYER_COLOR_NAMES[idx]


def resolve_slot_events(replay: BitReplay) -> dict[int, dict[str, Any]]:
    """Walk joins and leaves in time order; return per-slot
    `joined_tick` / `left_tick` / `in_game_name`.

    Maintains a tiny simulation of `sim.players` (an ordered list of
    slot numbers) so that the `player` field in a leave record — which
    is the index into `sim.players` at the moment of the leave, not the
    slot — can be mapped back to the right slot. Joins append to the
    current-players list; leaves pop the named index.

    Pragmatic assumption (DESIGN.md decision #3): no mid-game rejoins.
    The reporter never sees that pattern in tournament play, and a
    cleaner simulation here would only matter once the game protocol
    permits it.
    """
    events: list[tuple[int, int, str, ReplayJoin | ReplayLeave]] = []
    for j in replay.joins:
        events.append((j.time_ms, 0, "join", j))
    for lv in replay.leaves:
        events.append((lv.time_ms, 1, "leave", lv))
    events.sort(key=lambda e: (e[0], e[1]))
    current_players: list[int] = []
    info: dict[int, dict[str, Any]] = {}
    for time_ms, _, kind, record in events:
        tick = tick_from_ms(time_ms)
        if kind == "join":
            join = record  # type: ignore[assignment]
            # `join_order` is the connection-order index this slot was
            # assigned to at join time — equal to the current length of
            # `sim.players` (which the writer recorded as
            # `ReplayJoinRecord.player`). Slots that get an explicit
            # `slot >= 0` get that slot id; `slot < 0` falls back to
            # using the join-order index as the slot.
            join_order = len(current_players)
            slot = join.slot if join.slot >= 0 else join_order  # type: ignore[attr-defined]
            current_players.append(slot)
            entry = info.setdefault(slot, {})
            entry["joined_tick"] = tick
            entry["join_order"] = join_order
            entry["in_game_name"] = join.name  # type: ignore[attr-defined]
            entry.setdefault("left_tick", None)
        else:
            leave = record  # type: ignore[assignment]
            if 0 <= leave.player < len(current_players):  # type: ignore[attr-defined]
                slot = current_players.pop(leave.player)  # type: ignore[attr-defined]
                info.setdefault(slot, {})["left_tick"] = tick
    return info


def extract_input_presses(replay: BitReplay) -> list[InputPress]:
    """Walk every input record in time order; emit one `InputPress`
    for each newly-set edge bit (0→1 transition) per slot.

    The binary stream's `input.player` is the index into `sim.players`
    at the moment of the record, which mutates across leaves. The
    walker maintains the live `player_index → slot` mapping alongside
    a per-slot `prev_mask`, mirroring how the game's writer emits
    records (`server.nim` only writes a record when the per-player
    mask changes — so each record is guaranteed to differ from the
    previous mask for that player).

    Time-order tie-break at the same `time_ms`:
      joins (0) < inputs (1) < leaves (2)
    so a player who joins and presses on the same ms produces a
    correctly-ordered (join, press) pair; same for press-then-leave.
    """
    events: list[tuple[int, int, str, Any]] = []
    for j in replay.joins:
        events.append((j.time_ms, 0, "join", j))
    for inp in replay.inputs:
        events.append((inp.time_ms, 1, "input", inp))
    for lv in replay.leaves:
        events.append((lv.time_ms, 2, "leave", lv))
    events.sort(key=lambda e: (e[0], e[1]))

    current_players: list[int] = []
    prev_mask_by_slot: dict[int, int] = {}
    presses: list[InputPress] = []
    for time_ms, _priority, kind, record in events:
        tick = tick_from_ms(time_ms)
        if kind == "join":
            slot = record.slot if record.slot >= 0 else len(current_players)
            current_players.append(slot)
            prev_mask_by_slot.setdefault(slot, 0)
        elif kind == "leave":
            if 0 <= record.player < len(current_players):
                current_players.pop(record.player)
        else:  # input
            if not (0 <= record.player < len(current_players)):
                continue  # defensive: input from an unknown player index
            slot = current_players[record.player]
            prev = prev_mask_by_slot.get(slot, 0)
            cur = record.keys
            edges = cur & ~prev
            for name, bit in BUTTONS:
                if edges & bit:
                    presses.append(InputPress(tick=tick, slot=slot, button=name))
            prev_mask_by_slot[slot] = cur
    return presses


def bucket_presses(
    presses: list[InputPress], *, bucket_ticks: int = ACTIVITY_BUCKET_TICKS
) -> list[ActivityBucket]:
    """Aggregate edge-detected presses into per-(slot, bucket) windows.

    Empty buckets are not emitted; downstream consumers that want a
    dense per-slot intensity strip should fill gaps with zero (see
    `build_activity_block`).
    """
    if bucket_ticks <= 0:
        raise ValueError(f"bucket_ticks must be positive, got {bucket_ticks!r}")
    agg: dict[tuple[int, int], dict[str, int]] = {}
    for p in presses:
        bucket_start = (p.tick // bucket_ticks) * bucket_ticks
        slot_key = (p.slot, bucket_start)
        agg.setdefault(slot_key, {})
        agg[slot_key][p.button] = agg[slot_key].get(p.button, 0) + 1
    out: list[ActivityBucket] = []
    for (slot, bucket_start), counts in sorted(agg.items()):
        out.append(
            ActivityBucket(
                slot=slot,
                bucket_start_tick=bucket_start,
                bucket_ticks=bucket_ticks,
                presses_total=sum(counts.values()),
                presses_by_button=dict(sorted(counts.items())),
            )
        )
    return out


def per_slot_press_summary(
    presses: list[InputPress], slot_count: int
) -> tuple[list[int], list[dict[str, int]]]:
    """Reduce a flat press list to per-slot (total, per-button) summaries.

    Returns `(totals, per_kind)` aligned by slot index 0..slot_count-1.
    Slots with no presses get `total=0` and `per_kind={}`.
    """
    totals = [0] * slot_count
    per_kind: list[dict[str, int]] = [{} for _ in range(slot_count)]
    for p in presses:
        if 0 <= p.slot < slot_count:
            totals[p.slot] += 1
            per_kind[p.slot][p.button] = per_kind[p.slot].get(p.button, 0) + 1
    return totals, [dict(sorted(d.items())) for d in per_kind]


def build_activity_block(
    buckets: list[ActivityBucket],
    *,
    slot_count: int,
    last_tick: int,
    bucket_ticks: int = ACTIVITY_BUCKET_TICKS,
) -> ActivityBlock:
    """Densify the sparse bucket list into one `presses_per_bucket`
    array per slot, with zero-padding so each slot's array has the
    same length (covering ticks 0..last_tick).

    The dense form is what the HTML sparkline expects; the sparse
    bucket events go into the parquet.
    """
    n_buckets = max(1, (last_tick // bucket_ticks) + 1) if last_tick > 0 else 0
    per_slot_counts: list[list[int]] = [[0] * n_buckets for _ in range(slot_count)]
    for b in buckets:
        if 0 <= b.slot < slot_count:
            idx = b.bucket_start_tick // bucket_ticks
            if 0 <= idx < n_buckets:
                per_slot_counts[b.slot][idx] = b.presses_total
    return ActivityBlock(
        bucket_ticks=bucket_ticks,
        buckets_per_slot=[
            ActivityPerSlot(slot=i, presses_per_bucket=per_slot_counts[i])
            for i in range(slot_count)
        ],
    )


def build_slot_stats(
    results: AmongThemResults,
    metadata: EpisodeMetadata,
    config: GameConfig,
    *,
    replay: BitReplay | None = None,
    input_press_totals: list[int] | None = None,
    input_press_per_kind: list[dict[str, int]] | None = None,
) -> list[SlotStats]:
    """Build per-slot stats from the aggregate arrays in results.json,
    optionally enriched with replay-derived per-slot fields
    (`in_game_name`, `joined_tick`, `left_tick`, `color_*`) and
    input-stream summaries (`input_press_total`, `input_press_per_kind`).

    When `input_press_*` lists are omitted, the input fields surface
    as `None` / `None` (phase 2 / phase 3 callers); when they are
    passed (phase 4 callers), the values land in `SlotStats`.
    """
    n = results.slot_count
    policy_by_slot = {p.slot: p.policy_name for p in metadata.players}
    slot_events = resolve_slot_events(replay) if replay is not None else {}
    win = results.win or []
    tasks = results.tasks or []
    kills = results.kills or []
    vp = results.vote_players or []
    vs = results.vote_skip or []
    vt = results.vote_timeout or []
    out: list[SlotStats] = []
    for i in range(n):
        role = _slot_role(i, results.imposter, results.crew)
        won = bool(win[i]) if i < len(win) else False
        color_index, color_name = _resolve_color(i, config)
        slot_event = slot_events.get(i, {})
        out.append(
            SlotStats(
                slot=i,
                join_order=slot_event.get("join_order"),
                policy_name=_resolve_policy_name(i, results.names, policy_by_slot),
                in_game_name=slot_event.get("in_game_name"),
                color_index=color_index,
                color_name=color_name,
                role=role,
                won=won,
                score=float(results.scores[i]) if i < len(results.scores) else 0.0,
                kills=int(kills[i]) if i < len(kills) else 0,
                tasks=int(tasks[i]) if i < len(tasks) else 0,
                tasks_assigned=config.tasks_per_player if role == "Crewmate" else 0,
                vote_players=int(vp[i]) if i < len(vp) else 0,
                vote_skip=int(vs[i]) if i < len(vs) else 0,
                vote_timeout=int(vt[i]) if i < len(vt) else 0,
                joined_tick=slot_event.get("joined_tick", 0),
                left_tick=slot_event.get("left_tick"),
                input_press_total=(
                    input_press_totals[i]
                    if input_press_totals and i < len(input_press_totals)
                    else None
                ),
                input_press_per_kind=(
                    input_press_per_kind[i]
                    if input_press_per_kind and i < len(input_press_per_kind)
                    else None
                ),
            )
        )
    return out


def collect_disconnects(slots: list[SlotStats], last_tick: int) -> list[Disconnect]:
    """A `Disconnect` is a leave that happened more than 5 s before the
    last hash tick (DESIGN.md §"Disconnect / present-ticks"). Leaves
    within that grace period are treated as natural cleanup at episode
    end.
    """
    out: list[Disconnect] = []
    for s in slots:
        if s.left_tick is None:
            continue
        if last_tick - s.left_tick > _DISCONNECT_GRACE_TICKS:
            out.append(
                Disconnect(
                    slot=s.slot,
                    leave_tick=s.left_tick,
                    leave_seconds=s.left_tick / REPLAY_FPS,
                )
            )
    return out


def build_stats(
    results: AmongThemResults,
    metadata: EpisodeMetadata,
    replay: BitReplay,
) -> AmongThemStats:
    last_tick = replay.last_tick
    presses = extract_input_presses(replay)
    buckets = bucket_presses(presses)
    totals, per_kind = per_slot_press_summary(presses, results.slot_count)
    slots = build_slot_stats(
        results,
        metadata,
        replay.header.config,
        replay=replay,
        input_press_totals=totals,
        input_press_per_kind=per_kind,
    )
    activity = build_activity_block(
        buckets, slot_count=results.slot_count, last_tick=last_tick
    )
    return AmongThemStats(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        duration_seconds=metadata.duration_seconds,
        total_ticks=last_tick if last_tick > 0 else None,
        replay_fps=REPLAY_FPS,
        game_version=replay.header.game_version,
        config=replay.header.config,
        verdict=derive_verdict(results),
        slots=slots,
        slot_to_join_order=[s.join_order for s in slots],
        disconnects=collect_disconnects(slots, last_tick),
        activity=activity,
    )


# ---------- parquet event-log assembly ----------


def build_event_rows(
    stats: AmongThemStats, replay: BitReplay | None = None
) -> list[dict[str, Any]]:
    """Assemble event-log rows.

    Phase 4 keys emitted:
      - `game_config` (ts=0, player=-1)
      - `join` (ts=joined_tick, player=slot) — one per ReplayJoinRecord
      - `leave` (ts=left_tick, player=slot) — one per ReplayLeaveRecord
      - `input_press` (ts=tick, player=slot) — one per 0→1 button-edge
      - `activity_bucket` (ts=bucket_start_tick, player=slot) — per
        (slot, time-bucket) aggregate with `presses_total` and
        `presses_by_button`. Empty buckets are not emitted.
      - `player_summary` (ts=last_tick, player=slot)
      - `game_result` (ts=last_tick, player=-1)

    `join` payloads carry `token_present: bool` only — never the token
    string (DESIGN.md decision #9).
    """
    rows: list[dict[str, Any]] = []
    last_tick = stats.total_ticks or 0
    rows.append(
        {
            "ts": 0,
            "player": -1,
            "key": "game_config",
            "value": _stable_json(stats.config.model_dump()),
        }
    )
    if replay is not None:
        # Build a player_index -> slot map by walking joins in order
        # (mirrors resolve_slot_events but tracks the per-join slot so we
        # can emit a join row referencing the correct slot rather than
        # the raw join.player index).
        current_players: list[int] = []
        for join in replay.joins:
            # `player_index` is the connection-order index this join was
            # assigned to at join time — equal to the current length of
            # `sim.players`. Exposing it lets downstream ingesters
            # reconstruct the slot ↔ connection-order mapping from the
            # parquet alone.
            player_index = len(current_players)
            slot = join.slot if join.slot >= 0 else player_index
            current_players.append(slot)
            rows.append(
                {
                    "ts": tick_from_ms(join.time_ms),
                    "player": slot,
                    "key": "join",
                    "value": _stable_json(
                        {
                            "name": join.name,
                            "slot": slot,
                            "player_index": player_index,
                            "token_present": join.token_present,
                        }
                    ),
                }
            )
        # Re-walk for leaves, replaying the same join-driven mutation
        # of current_players so leave.player resolves to the right slot.
        current_players = []
        joins_iter = iter(sorted(replay.joins, key=lambda j: j.time_ms))
        leaves_iter = iter(sorted(replay.leaves, key=lambda lv: lv.time_ms))
        # Merge-walk by timestamp.
        next_join = next(joins_iter, None)
        next_leave = next(leaves_iter, None)
        while next_join is not None or next_leave is not None:
            take_join = next_leave is None or (
                next_join is not None and next_join.time_ms <= next_leave.time_ms
            )
            if take_join:
                slot = next_join.slot if next_join.slot >= 0 else len(current_players)
                current_players.append(slot)
                next_join = next(joins_iter, None)
            else:
                lv = next_leave
                if 0 <= lv.player < len(current_players):
                    slot = current_players.pop(lv.player)
                    rows.append(
                        {
                            "ts": tick_from_ms(lv.time_ms),
                            "player": slot,
                            "key": "leave",
                            "value": _stable_json(
                                {
                                    "ticks_remaining": max(
                                        0, last_tick - tick_from_ms(lv.time_ms)
                                    )
                                }
                            ),
                        }
                    )
                next_leave = next(leaves_iter, None)
        # input_press + activity_bucket rows derived from the replay's
        # input stream. Walked once via extract_input_presses (the
        # canonical edge-detection pass) so the parquet's
        # `input_press` rows and `stats.slots[i].input_press_*`
        # summaries agree by construction.
        presses = extract_input_presses(replay)
        for p in presses:
            rows.append(
                {
                    "ts": p.tick,
                    "player": p.slot,
                    "key": "input_press",
                    "value": _stable_json({"button": p.button}),
                }
            )
        for b in bucket_presses(presses):
            rows.append(
                {
                    "ts": b.bucket_start_tick,
                    "player": b.slot,
                    "key": "activity_bucket",
                    "value": _stable_json(
                        {
                            "bucket_ticks": b.bucket_ticks,
                            "presses_total": b.presses_total,
                            "presses_by_button": b.presses_by_button,
                        }
                    ),
                }
            )
    for s in stats.slots:
        rows.append(
            {
                "ts": last_tick,
                "player": s.slot,
                "key": "player_summary",
                "value": _stable_json(
                    {
                        "role": s.role,
                        "won": s.won,
                        "score": s.score,
                        "kills": s.kills,
                        "tasks": s.tasks,
                        "tasks_assigned": s.tasks_assigned,
                        "vote_players": s.vote_players,
                        "vote_skip": s.vote_skip,
                        "vote_timeout": s.vote_timeout,
                        "policy_name": s.policy_name,
                        "join_order": s.join_order,
                        "joined_tick": s.joined_tick,
                        "left_tick": s.left_tick,
                        "in_game_name": s.in_game_name,
                        "color_name": s.color_name,
                    }
                ),
            }
        )
    rows.append(
        {
            "ts": last_tick,
            "player": -1,
            "key": "game_result",
            "value": _stable_json(
                {
                    "winner_side": stats.verdict.winner_side,
                    "time_limit_reached": stats.verdict.time_limit_reached,
                    "any_winner": stats.verdict.any_winner,
                    "total_ticks": stats.total_ticks,
                    "duration_seconds": stats.duration_seconds,
                }
            ),
        }
    )
    return rows


# ---------- HTML renderer ----------


_HTML_CSS = """
:root { color-scheme: light; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f5f6f8;
  color: #212529;
  margin: 0;
  padding: 24px 16px 48px;
}
.wrap { max-width: 880px; margin: 0 auto; }
header { margin-bottom: 16px; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
.subtitle { color: #6c757d; font-size: 13px; }
.card {
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.verdict {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.verdict .ribbon {
  font-weight: 600; font-size: 13px;
  text-transform: uppercase; letter-spacing: 0.05em;
  padding: 5px 12px; border-radius: 999px;
}
.verdict .ribbon.imposter { background: #f9d6d5; color: #842029; }
.verdict .ribbon.crewmate { background: #cfe7e1; color: #0f5132; }
.verdict .ribbon.draw     { background: #e9ecef; color: #495057; }
.verdict .headline { font-size: 18px; font-weight: 600; }
table.scores { width: 100%; border-collapse: collapse; font-size: 13px; }
table.scores th, table.scores td {
  padding: 8px 6px; text-align: left; border-bottom: 1px solid #f1f3f5;
  font-variant-numeric: tabular-nums;
}
table.scores th {
  font-weight: 600; font-size: 11px; color: #6c757d;
  text-transform: uppercase; letter-spacing: 0.04em;
}
table.scores td.num { text-align: right; }
.role { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; }
.role.imposter { background: #f9d6d5; color: #842029; }
.role.crewmate { background: #cfe7e1; color: #0f5132; }
.role.unknown  { background: #e9ecef; color: #495057; }
.outcome { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; }
.outcome.won  { background: #d1e7dd; color: #0f5132; }
.outcome.lost { background: #f8d7da; color: #842029; }
.swatch {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 2px;
  vertical-align: middle;
  margin-right: 6px;
  border: 1px solid rgba(0, 0, 0, 0.08);
}
.slot-cell { display: inline-flex; align-items: center; }
.activity-col { min-width: 110px; }
.sparkline { display: block; vertical-align: middle; }
.sparkline .bar-present { opacity: 1; }
.sparkline .bar-absent  { opacity: 0.22; }
h2 {
  font-size: 13px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: #495057; margin: 0 0 10px;
}
.config-strip {
  font-size: 12px; color: #495057; display: flex; flex-wrap: wrap; gap: 16px;
}
.config-strip .item strong { color: #212529; }
footer { margin-top: 24px; font-size: 11px; color: #adb5bd; text-align: center; }
""".strip()


def _verdict_html(verdict: VerdictBlock) -> str:
    if verdict.winner_side == "Imposter":
        return (
            '<span class="ribbon imposter">Imposters win</span>'
            '<span class="headline">Imposters survived</span>'
        )
    if verdict.winner_side == "Crewmate":
        return (
            '<span class="ribbon crewmate">Crewmates win</span>'
            '<span class="headline">Crew survived or completed tasks</span>'
        )
    return (
        '<span class="ribbon draw">Draw</span>'
        '<span class="headline">Time limit reached</span>'
    )


def _role_badge_html(role: str | None) -> str:
    if role == "Imposter":
        return '<span class="role imposter">Imposter</span>'
    if role == "Crewmate":
        return '<span class="role crewmate">Crewmate</span>'
    return '<span class="role unknown">?</span>'


def _slot_color_hex(slot: SlotStats) -> str:
    """The CSS hex for this slot. Falls back to a neutral gray when
    the slot has no resolved color (e.g. an unknown color name in
    config.slots[].color, per `_resolve_color`)."""
    if slot.color_name and slot.color_name in AMONG_THEM_COLORS:
        return AMONG_THEM_COLORS[slot.color_name]
    return AMONG_THEM_COLORS["gray"]


def _swatch_html(slot: SlotStats) -> str:
    """A small inline-style swatch keyed to the slot's color. Carries
    `class="swatch"` so phase-5 tests can count one per row."""
    color = _slot_color_hex(slot)
    label = html_escape(slot.color_name or "unknown")
    return (
        f'<span class="swatch" style="background:{color}" '
        f'title="{label}" aria-hidden="true"></span>'
    )


def _outcome_badge_html(s: SlotStats) -> str:
    if s.won:
        return '<span class="outcome won">Won</span>'
    return '<span class="outcome lost">Lost</span>'


def _duration_text(stats: AmongThemStats) -> str:
    if stats.duration_seconds is None:
        return "duration unknown"
    return f"{stats.duration_seconds:.1f} s"


def _config_strip_html(config: GameConfig) -> str:
    kill_cooldown_s = config.kill_cooldown_ticks / REPLAY_FPS
    vote_timer_s = config.vote_timer_ticks / REPLAY_FPS
    items = [
        ("Imposters", str(config.imposter_count)),
        ("Tasks / player", str(config.tasks_per_player)),
        ("Kill cooldown", f"{kill_cooldown_s:.0f} s"),
        ("Vote timer", f"{vote_timer_s:.0f} s"),
        ("Max ticks", str(config.max_ticks)),
        ("Map", html_escape(config.map_path or "unknown")),
    ]
    if config.seed is not None:
        items.append(("Seed", str(config.seed)))
    parts = [
        f'<span class="item"><strong>{html_escape(label)}</strong> {html_escape(value)}</span>'
        for label, value in items
    ]
    return '<div class="config-strip">' + "".join(parts) + "</div>"


def _sparkline_html(
    slot: SlotStats,
    buckets: list[int],
    *,
    bucket_ticks: int,
    max_bucket: int,
) -> str:
    """Per-slot activity sparkline.

    One `<rect>` per bucket, height proportional to that bucket's
    press count normalized to the busiest bucket across all slots
    (so bar heights are comparable row-to-row). Buckets outside the
    slot's `[joined_tick, left_tick]` presence window carry the
    `bar-absent` class (dimmed via CSS) — present-window buckets
    carry `bar-present`. Empty present buckets render as a thin
    baseline tick so the reader sees the row exists.
    """
    n = len(buckets)
    if n == 0:
        return (
            f'<svg class="sparkline" data-slot="{slot.slot}" aria-hidden="true"></svg>'
        )
    bar_w = 6
    bar_gap = 2
    max_bar_h = 22
    pad_y = 2
    svg_w = n * (bar_w + bar_gap) - bar_gap + 4  # +4 for left/right pad
    svg_h = max_bar_h + 2 * pad_y
    bottom = svg_h - pad_y
    left_tick = slot.left_tick if slot.left_tick is not None else None
    joined_tick = slot.joined_tick
    color = _slot_color_hex(slot)
    rects: list[str] = []
    for i, count in enumerate(buckets):
        bucket_start = i * bucket_ticks
        bucket_end = bucket_start + bucket_ticks
        present = bucket_end > joined_tick and (
            left_tick is None or bucket_start < left_tick
        )
        # Minimum 1px so an empty present bucket still draws a baseline.
        if max_bucket > 0 and count > 0:
            h = max(1, round(count / max_bucket * max_bar_h))
        else:
            h = 1
        x = 2 + i * (bar_w + bar_gap)
        y = bottom - h
        klass = "bar-present" if present else "bar-absent"
        rects.append(
            f'<rect class="{klass}" x="{x}" y="{y}" width="{bar_w}" '
            f'height="{h}" rx="1" fill="{color}"/>'
        )
    total = slot.input_press_total or 0
    return (
        f'<svg class="sparkline" data-slot="{slot.slot}" '
        f'viewBox="0 0 {svg_w} {svg_h}" width="{svg_w}" height="{svg_h}" '
        f'role="img" aria-label="{total} presses across {n} buckets">'
        + "".join(rects)
        + "</svg>"
    )


def _scoreboard_html(stats: AmongThemStats) -> str:
    rows: list[str] = []
    # Normalize sparkline bar heights to the busiest bucket *across
    # all slots* so the visual scale is comparable row-to-row.
    buckets_by_slot = {
        b.slot: b.presses_per_bucket for b in stats.activity.buckets_per_slot
    }
    max_bucket = max(
        (max(buckets, default=0) for buckets in buckets_by_slot.values()),
        default=0,
    )
    for s in stats.slots:
        tasks_cell = (
            f"{s.tasks} / {s.tasks_assigned}" if s.tasks_assigned > 0 else f"{s.tasks}"
        )
        sparkline = _sparkline_html(
            s,
            buckets_by_slot.get(s.slot, []),
            bucket_ticks=stats.activity.bucket_ticks,
            max_bucket=max_bucket,
        )
        rows.append(
            "<tr>"
            f'<td><span class="slot-cell">{_swatch_html(s)}Slot {s.slot}</span></td>'
            f"<td>{html_escape(s.policy_name)}</td>"
            f"<td>{_role_badge_html(s.role)}</td>"
            f"<td>{_outcome_badge_html(s)}</td>"
            f'<td class="num">{s.score:.0f}</td>'
            f'<td class="num">{s.kills}</td>'
            f'<td class="num">{html_escape(tasks_cell)}</td>'
            f'<td class="num">{s.vote_players}</td>'
            f'<td class="num">{s.vote_skip}</td>'
            f'<td class="num">{s.vote_timeout}</td>'
            f'<td class="activity-col">{sparkline}</td>'
            "</tr>"
        )
    return (
        '<table class="scores">'
        "<thead><tr>"
        "<th>Slot</th><th>Policy</th><th>Role</th><th>Outcome</th>"
        '<th class="num">Score</th>'
        '<th class="num">Kills</th>'
        '<th class="num">Tasks</th>'
        '<th class="num">Vote on</th>'
        '<th class="num">Skip</th>'
        '<th class="num">Timeout</th>'
        "<th>Activity</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _disconnects_html(disconnects: list[Disconnect], slots: list[SlotStats]) -> str:
    name_by_slot = {s.slot: s.policy_name for s in slots}
    rows: list[str] = []
    for d in disconnects:
        label = html_escape(name_by_slot.get(d.slot, f"Slot {d.slot}"))
        when = f"tick {d.leave_tick}"
        if d.leave_seconds is not None:
            when += f" ({d.leave_seconds:.1f} s)"
        rows.append(
            "<tr>"
            f"<td>Slot {d.slot}</td>"
            f"<td>{label}</td>"
            f"<td>{html_escape(when)}</td>"
            "</tr>"
        )
    return (
        '<table class="scores">'
        "<thead><tr><th>Slot</th><th>Policy</th><th>Left at</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def render_summary_html(stats: AmongThemStats) -> str:
    episode_label = stats.episode_id or "unknown"
    disconnects_section = ""
    if stats.disconnects:
        disconnects_section = (
            '<section class="card">'
            "<h2>Disconnects</h2>"
            f"{_disconnects_html(stats.disconnects, stats.slots)}"
            "</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Among Them &mdash; Episode {html_escape(episode_label)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Among Them &mdash; Episode {html_escape(episode_label)}</h1>
<div class="subtitle">
Variant <strong>{html_escape(stats.variant_id)}</strong> &middot;
{html_escape(_duration_text(stats))} &middot;
{len(stats.slots)} players &middot;
game v{html_escape(stats.game_version)}
</div>
</header>

<section class="card">
<div class="verdict">{_verdict_html(stats.verdict)}</div>
</section>

<section class="card">
<h2>Game config</h2>
{_config_strip_html(stats.config)}
</section>

<section class="card">
<h2>Scoreboard</h2>
{_scoreboard_html(stats)}
</section>

{disconnects_section}

<footer>full stats: <code>stats.json</code> &middot;
event log: <code>events.parquet</code></footer>
</div>
</body>
</html>
"""


# ---------- zip assembly ----------


def build_zip_bytes(
    *,
    results: AmongThemResults,
    metadata: EpisodeMetadata,
    replay_bytes: bytes,
) -> bytes:
    """Build the canonical output zip: a top-level `manifest.json` (flagging
    `summary.html` as `render` and `events.parquet` as `event_log`), the
    HTML render target, the auxiliary `stats.json`, and the event-log
    Parquet."""
    replay = parse_bitreplay(replay_bytes)
    stats = build_stats(results, metadata, replay)
    summary_html = render_summary_html(stats).encode("utf-8")
    stats_json = (json.dumps(stats.model_dump(), indent=2) + "\n").encode("utf-8")
    events_parquet = write_events_parquet(build_event_rows(stats, replay))
    manifest_json = _stable_json(
        {
            "reporter_id": REPORTER_ID,
            "render": "summary.html",
            "event_log": "events.parquet",
        }
    ).encode("utf-8")
    return write_deterministic_zip(
        [
            ("manifest.json", manifest_json),
            ("summary.html", summary_html),
            ("stats.json", stats_json),
            ("events.parquet", events_parquet),
        ]
    )


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        if inner.status != "success":
            raise RuntimeError(
                f"bundle status={inner.status!r}; reporter cannot operate on "
                "a failed episode"
            )
        results = AmongThemResults.model_validate(bundle.read_json("results"))
        # Among Them's "replay" token bytes are the binary `.bitreplay`
        # payload, not JSON (canonical convention is replay.json -- this is
        # an Among-Them-specific deviation; the BundleReader doesn't care
        # about content type, just bytes).
        replay_bytes = bundle.read_bytes("replay")
        metadata_raw: dict[str, Any] = bundle.read_json_optional("metadata") or {}
    metadata_raw.setdefault("episode_id", inner.ereq_id)
    metadata = EpisodeMetadata.model_validate(metadata_raw)
    payload = build_zip_bytes(
        results=results, metadata=metadata, replay_bytes=replay_bytes
    )
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
