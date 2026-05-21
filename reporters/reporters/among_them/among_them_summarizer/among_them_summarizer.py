"""Among Them summarizer reporter.

Phase 2 (aggregates path): builds a usable per-episode summary from
`COGAME_RESULTS_URI` + `COGAME_EPISODE_METADATA_URI` + the
`.bitreplay` header (game config). Per-record replay parsing and
input-stream analytics land in phases 3-4.

The output zip contains:

    report.zip
    ├── summary.html        # rendered inline (listed in render.txt)
    ├── stats.json          # download-only; full per-slot detail
    ├── events.parquet      # download-only; shared (ts, player, key, value) schema
    └── render.txt          # single line: "summary.html\\n"

See DESIGN.md for the full phase plan and decisions.

The inline primitives in this file (`ReporterInputs`, `read_uri` /
`write_uri`, `write_deterministic_zip`, the parquet writer) are
SDK-extraction candidates — once the second reporter exists in stable
form, the upcoming `reporter_sdk` extraction pass will lift them.
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

# ---------- inline primitives (SDK extraction candidates) ----------


class ReporterInputs(BaseModel):
    results_uri: str
    replay_uri: str
    episode_metadata_uri: str
    report_output_uri: str
    reporter_id: str


def load_reporter_inputs() -> ReporterInputs:
    return ReporterInputs(
        results_uri=os.environ["COGAME_RESULTS_URI"],
        replay_uri=os.environ["COGAME_REPLAY_URI"],
        episode_metadata_uri=os.environ["COGAME_EPISODE_METADATA_URI"],
        report_output_uri=os.environ["COGAME_REPORT_OUTPUT_URI"],
        reporter_id=os.environ["COGAME_REPORTER_ID"],
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


# Pinned zip-entry mtime for byte-identical determinism (D12).
_DETERMINISTIC_ZIP_MTIME = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a zip with pinned mtimes for byte-identical reruns (D12)."""
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
        pa.field("player", pa.int16()),
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
                "player": pa.array([r["player"] for r in rows], type=pa.int16()),
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
    episode_id: str | None = None
    variant_id: str
    duration_seconds: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    players: list[PlayerMetadata] = Field(default_factory=list)


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

    model_config = {"populate_by_name": True, "extra": "ignore"}


# ---------- output models ----------


class VerdictBlock(BaseModel):
    winner_side: str  # "Imposter" | "Crewmate" | "Draw"
    time_limit_reached: bool
    any_winner: bool


class SlotStats(BaseModel):
    slot: int
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
    likely_dead: bool
    input_press_total: int | None = None
    input_press_per_kind: dict[str, int] | None = None


class MeetingsBlock(BaseModel):
    estimated_count: int
    total_vote_players: int
    total_vote_skip: int
    total_vote_timeout: int


class Disconnect(BaseModel):
    slot: int
    leave_tick: int
    leave_seconds: float | None


class AmongThemStats(BaseModel):
    episode_id: str | None
    variant_id: str
    duration_seconds: float | None
    total_ticks: int | None
    replay_fps: int
    game_version: str
    config: GameConfig
    verdict: VerdictBlock
    slots: list[SlotStats]
    meetings: MeetingsBlock
    disconnects: list[Disconnect]


class BitReplayHeader(BaseModel):
    game_name: str
    game_version: str
    format_version: int
    timestamp_ms: int
    config: GameConfig

    model_config = {"arbitrary_types_allowed": True}


# ---------- bitreplay header parser ----------


def _read_u16(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def _read_u64(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        raise ValueError(f"bitreplay truncated at offset {offset}")
    return struct.unpack_from("<Q", data, offset)[0], offset + 8


def _read_str(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = _read_u16(data, offset)
    if offset + length > len(data):
        raise ValueError(f"bitreplay string truncated at offset {offset}")
    return data[offset : offset + length].decode("utf-8"), offset + length


def parse_bitreplay_header(data: bytes) -> BitReplayHeader:
    """Parse a `.bitreplay` v3 header.

    Layout (`among_them/replays.nim:148-161`):

        magic (8B "BITWORLD") | format_version (u16) |
        game_name (u16+utf8)  | game_version (u16+utf8) |
        timestamp_ms (u64)    | config_json (u16+utf8)

    Refuses anything that isn't `BITWORLD` + format-version 3 + game-name
    `among_them`. Returns the parsed header and game config; record
    parsing (joins/leaves/inputs/hashes) lands in phase 3.
    """
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
    return BitReplayHeader(
        game_name=game_name,
        game_version=game_version,
        format_version=format_version,
        timestamp_ms=timestamp_ms,
        config=config,
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


def estimate_meetings(results: AmongThemResults) -> MeetingsBlock:
    """Lower-bound estimate of meetings held during the episode.

    Every alive slot votes (or times out) exactly once per meeting
    (`sim.nim:2862-2897::tallyVotes`). So `vote_players + vote_skip +
    vote_timeout` per slot is the number of meetings that slot
    participated in, and the max across slots is the tightest lower
    bound on the total. See DESIGN.md §"Meetings count (best-effort)".
    """
    vp = results.vote_players or []
    vs = results.vote_skip or []
    vt = results.vote_timeout or []
    n = results.slot_count
    per_slot = [
        (vp[i] if i < len(vp) else 0)
        + (vs[i] if i < len(vs) else 0)
        + (vt[i] if i < len(vt) else 0)
        for i in range(n)
    ]
    return MeetingsBlock(
        estimated_count=max(per_slot) if per_slot else 0,
        total_vote_players=sum(vp),
        total_vote_skip=sum(vs),
        total_vote_timeout=sum(vt),
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


def _likely_dead(role: str | None, won: bool, winner_side: str) -> bool:
    """Inference: did this player die before the game ended?

    Only flags the unambiguous case: the player's team won the game
    overall, but they personally didn't win. The only way that
    happens in Among Them is if they were killed (crew) or ejected
    (which by sim convention sets their win flag to False since the
    game continued without them — for imposters, see Friction §4 of
    DESIGN.md). Other cases (lost in a losing team, won) stay False.
    """
    if won or role is None:
        return False
    return winner_side == role


def build_slot_stats(
    results: AmongThemResults,
    metadata: EpisodeMetadata,
    config: GameConfig,
) -> list[SlotStats]:
    """Build per-slot stats from the aggregate arrays in results.json.

    Phase 2: `in_game_name`, `color_index`, `color_name`, `joined_tick`,
    `left_tick`, `input_press_*` are filled in by phase 3+. They appear
    as None / placeholder values here.
    """
    n = results.slot_count
    verdict = derive_verdict(results)
    policy_by_slot = {p.slot: p.policy_name for p in metadata.players}
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
        out.append(
            SlotStats(
                slot=i,
                policy_name=_resolve_policy_name(i, results.names, policy_by_slot),
                in_game_name=None,
                color_index=None,
                color_name=None,
                role=role,
                won=won,
                score=float(results.scores[i]) if i < len(results.scores) else 0.0,
                kills=int(kills[i]) if i < len(kills) else 0,
                tasks=int(tasks[i]) if i < len(tasks) else 0,
                tasks_assigned=config.tasks_per_player if role == "Crewmate" else 0,
                vote_players=int(vp[i]) if i < len(vp) else 0,
                vote_skip=int(vs[i]) if i < len(vs) else 0,
                vote_timeout=int(vt[i]) if i < len(vt) else 0,
                joined_tick=0,
                left_tick=None,
                likely_dead=_likely_dead(role, won, verdict.winner_side),
                input_press_total=None,
                input_press_per_kind=None,
            )
        )
    return out


def build_stats(
    results: AmongThemResults,
    metadata: EpisodeMetadata,
    header: BitReplayHeader,
) -> AmongThemStats:
    return AmongThemStats(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        duration_seconds=metadata.duration_seconds,
        total_ticks=None,  # phase 3 reads this from the last hash record
        replay_fps=REPLAY_FPS,
        game_version=header.game_version,
        config=header.config,
        verdict=derive_verdict(results),
        slots=build_slot_stats(results, metadata, header.config),
        meetings=estimate_meetings(results),
        disconnects=[],  # phase 3 fills this in from leave records
    )


# ---------- parquet event-log assembly ----------


def build_event_rows(stats: AmongThemStats) -> list[dict[str, Any]]:
    """Phase 2 events: game_config, one player_summary per slot,
    game_result. Phase 3 adds join/leave; phase 4 adds input_press
    and activity_bucket.
    """
    rows: list[dict[str, Any]] = []
    rows.append(
        {
            "ts": 0,
            "player": -1,
            "key": "game_config",
            "value": _stable_json(stats.config.model_dump()),
        }
    )
    for s in stats.slots:
        rows.append(
            {
                "ts": 0,
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
                        "likely_dead": s.likely_dead,
                        "policy_name": s.policy_name,
                    }
                ),
            }
        )
    rows.append(
        {
            "ts": 0,
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
.outcome.dead { background: #fff3cd; color: #664d03; }
h2 {
  font-size: 13px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: #495057; margin: 0 0 10px;
}
.config-strip {
  font-size: 12px; color: #495057; display: flex; flex-wrap: wrap; gap: 16px;
}
.config-strip .item strong { color: #212529; }
.meetings { display: flex; gap: 24px; font-size: 13px; }
.meetings .stat { display: flex; flex-direction: column; }
.meetings .stat .label { color: #6c757d; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.meetings .stat .value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.meetings .note { color: #6c757d; font-size: 12px; margin-top: 8px; }
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


def _outcome_badge_html(s: SlotStats) -> str:
    if s.won:
        return '<span class="outcome won">Won</span>'
    if s.likely_dead:
        return '<span class="outcome dead" title="inferred from team outcome">Lost (likely killed)</span>'
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


def _scoreboard_html(stats: AmongThemStats) -> str:
    rows: list[str] = []
    for s in stats.slots:
        tasks_cell = (
            f"{s.tasks} / {s.tasks_assigned}" if s.tasks_assigned > 0 else f"{s.tasks}"
        )
        rows.append(
            "<tr>"
            f"<td>Slot {s.slot}</td>"
            f"<td>{html_escape(s.policy_name)}</td>"
            f"<td>{_role_badge_html(s.role)}</td>"
            f"<td>{_outcome_badge_html(s)}</td>"
            f'<td class="num">{s.score:.0f}</td>'
            f'<td class="num">{s.kills}</td>'
            f'<td class="num">{html_escape(tasks_cell)}</td>'
            f'<td class="num">{s.vote_players}</td>'
            f'<td class="num">{s.vote_skip}</td>'
            f'<td class="num">{s.vote_timeout}</td>'
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
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _meetings_html(meetings: MeetingsBlock) -> str:
    return (
        '<div class="meetings">'
        f'<div class="stat"><span class="label">Meetings (est.)</span>'
        f'<span class="value">{meetings.estimated_count}</span></div>'
        f'<div class="stat"><span class="label">Votes on players</span>'
        f'<span class="value">{meetings.total_vote_players}</span></div>'
        f'<div class="stat"><span class="label">Skip votes</span>'
        f'<span class="value">{meetings.total_vote_skip}</span></div>'
        f'<div class="stat"><span class="label">Timeouts</span>'
        f'<span class="value">{meetings.total_vote_timeout}</span></div>'
        "</div>"
        '<div class="note">Meeting count is a lower bound from per-slot vote totals; '
        "per-meeting transcripts and ballots require richer game-side events "
        "(see DESIGN.md §Frictions).</div>"
    )


def render_summary_html(stats: AmongThemStats) -> str:
    episode_label = stats.episode_id or "unknown"
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

<section class="card">
<h2>Meetings</h2>
{_meetings_html(stats.meetings)}
</section>

<footer>full stats: <code>stats.json</code> &middot;
event log: <code>events.parquet</code> &middot;
reporter v0.2 (phase 2)</footer>
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
    """Build the phase-2 output zip:

        summary.html  (rendered)
        stats.json    (download-only)
        events.parquet (download-only)
        render.txt    (lists summary.html)

    Phase 2 ignores all records in the replay beyond the header
    (config-bearing). Phase 3 extends this to consume joins / leaves /
    inputs / hashes.
    """
    header = parse_bitreplay_header(replay_bytes)
    stats = build_stats(results, metadata, header)
    summary_html = render_summary_html(stats).encode("utf-8")
    stats_json = (json.dumps(stats.model_dump(), indent=2) + "\n").encode("utf-8")
    events_parquet = write_events_parquet(build_event_rows(stats))
    render_txt = b"summary.html\n"
    return write_deterministic_zip(
        [
            ("summary.html", summary_html),
            ("stats.json", stats_json),
            ("events.parquet", events_parquet),
            ("render.txt", render_txt),
        ]
    )


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    results = AmongThemResults.model_validate(read_json(inputs.results_uri))
    metadata = EpisodeMetadata.model_validate(read_json(inputs.episode_metadata_uri))
    replay_bytes = read_uri(inputs.replay_uri)
    payload = build_zip_bytes(
        results=results, metadata=metadata, replay_bytes=replay_bytes
    )
    write_uri(inputs.report_output_uri, payload, content_type="application/zip")
    print(
        f"[{inputs.reporter_id}] wrote zip to {inputs.report_output_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
