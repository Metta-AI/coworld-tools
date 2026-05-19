"""Compare BitWorld AmongThem reference runs with AmongCogs audits."""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

from pydantic import BaseModel, Field

BITWORLD_TASK_HOLD_RE = re.compile(r"\bat task .*, holding action\b")
BITWORLD_MAP_LOCK_RE = re.compile(r"\bmap lock\b")
BITWORLD_CONNECTED_RE = re.compile(r"\bConnected to\b")
BITWORLD_BUTTON_RE = re.compile(r"\bButton\b|gather at Button")
BITWORLD_INTERSTITIAL_RE = re.compile(r"\binterstitial\b|Crewmates win|Imposters win|Game over")

REQUIRED_AMONGCOGS_COVERAGE = (
    "tasks_completed_rate",
    "kills_rate",
    "reports_rate",
    "ejections_rate",
    "meeting_calls_rate",
    "meeting_skips_rate",
    "emergency_meeting_calls_rate",
    "sabotages_rate",
    "repairs_rate",
    "vents_used_rate",
    "admin_checks_rate",
    "camera_checks_rate",
    "comms_checks_rate",
    "lights_sabotages_rate",
    "oxygen_sabotages_rate",
    "reactor_sabotages_rate",
    "meeting_talk_actions_rate",
    "ballot_talk_actions_rate",
    "winner_declared_rate",
)


class BitWorldReferenceMetrics(BaseModel):
    log_dir: str
    bot_logs: int
    connected_bots: int
    task_holds: int
    map_locks: int
    button_goals: int
    interstitials: int
    replay_bytes: int = 0
    replay_joins: int = 0
    replay_leaves: int = 0
    replay_inputs: int = 0
    replay_nonzero_inputs: int = 0
    replay_tick_hashes: int = 0
    replay_last_tick: int = 0
    config_min_players: int | None = None
    config_imposter_count: int | None = None
    config_tasks_per_player: int | None = None
    config_vote_timer_ticks: int | None = None
    config_max_ticks: int | None = None


class AmongCogsAuditMetrics(BaseModel):
    episodes: int
    completion_rate: float
    coverage: dict[str, float]
    winners: dict[str, int]
    actions: dict[str, float] = Field(default_factory=dict)
    steps_mean: float | None = None
    sps_mean: float | None = None


class ParityCheck(BaseModel):
    name: str
    passed: bool
    observed: float | int | str
    threshold: float | int | str


class ParityReport(BaseModel):
    bitworld: BitWorldReferenceMetrics
    amongcogs: AmongCogsAuditMetrics
    checks: list[ParityCheck] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def summarize_bitworld_run(log_dir: Path, replay_path: Path | None = None) -> BitWorldReferenceMetrics:
    bot_logs = sorted(log_dir.glob("bot*.log"))
    text = "\n".join(path.read_text() for path in bot_logs)
    replay_bytes = replay_path.stat().st_size if replay_path is not None and replay_path.exists() else 0
    replay = _summarize_bitworld_replay(replay_path) if replay_path is not None and replay_path.exists() else {}
    return BitWorldReferenceMetrics(
        log_dir=str(log_dir),
        bot_logs=len(bot_logs),
        connected_bots=max(len(set(_connected_bot_names(bot_logs))), int(replay.get("joins", 0))),
        task_holds=len(BITWORLD_TASK_HOLD_RE.findall(text)),
        map_locks=len(BITWORLD_MAP_LOCK_RE.findall(text)),
        button_goals=len(BITWORLD_BUTTON_RE.findall(text)),
        interstitials=len(BITWORLD_INTERSTITIAL_RE.findall(text)),
        replay_bytes=replay_bytes,
        replay_joins=int(replay.get("joins", 0)),
        replay_leaves=int(replay.get("leaves", 0)),
        replay_inputs=int(replay.get("inputs", 0)),
        replay_nonzero_inputs=int(replay.get("nonzero_inputs", 0)),
        replay_tick_hashes=int(replay.get("tick_hashes", 0)),
        replay_last_tick=int(replay.get("last_tick", 0)),
        config_min_players=_optional_int(replay.get("minPlayers")),
        config_imposter_count=_optional_int(replay.get("imposterCount")),
        config_tasks_per_player=_optional_int(replay.get("tasksPerPlayer")),
        config_vote_timer_ticks=_optional_int(replay.get("voteTimerTicks")),
        config_max_ticks=_optional_int(replay.get("maxTicks")),
    )


def summarize_amongcogs_audit(audit: dict[str, object]) -> AmongCogsAuditMetrics:
    coverage = audit["coverage"]
    winners = audit["winners"]
    steps = audit.get("steps", {})
    sps = audit.get("sps", {})
    assert isinstance(coverage, dict)
    assert isinstance(winners, dict)
    assert isinstance(steps, dict)
    assert isinstance(sps, dict)
    return AmongCogsAuditMetrics(
        episodes=int(audit["episodes"]),
        completion_rate=float(audit["completion_rate"]),
        coverage={str(key): float(value) for key, value in coverage.items()},
        winners={str(key): int(value) for key, value in winners.items()},
        actions={str(key): float(value) for key, value in _dict_or_empty(audit.get("actions")).items()},
        steps_mean=float(steps["mean"]) if "mean" in steps else None,
        sps_mean=float(sps["mean"]) if "mean" in sps else None,
    )


def build_parity_report(
    bitworld: BitWorldReferenceMetrics,
    amongcogs: AmongCogsAuditMetrics,
    *,
    min_connected_bots: int = 5,
) -> ParityReport:
    checks = [
        _min_check("bitworld.connected_bots", bitworld.connected_bots, min_connected_bots),
        _min_check("bitworld.replay_bytes", bitworld.replay_bytes, 1),
        _min_check("bitworld.replay_tick_hashes", bitworld.replay_tick_hashes, 1),
        _min_check("bitworld.replay_inputs", bitworld.replay_inputs, 1),
        _min_check("bitworld.replay_nonzero_inputs", bitworld.replay_nonzero_inputs, 1),
        _eq_check("bitworld.config.minPlayers", bitworld.config_min_players, 5),
        _eq_check("bitworld.config.imposterCount", bitworld.config_imposter_count, 1),
        _eq_check("bitworld.config.tasksPerPlayer", bitworld.config_tasks_per_player, 4),
        _eq_check("bitworld.config.voteTimerTicks", bitworld.config_vote_timer_ticks, 1440),
        _eq_check("bitworld.config.maxTicks", bitworld.config_max_ticks, 0),
        _min_check("amongcogs.completion_rate", amongcogs.completion_rate, 1.0),
    ]
    for key in REQUIRED_AMONGCOGS_COVERAGE:
        checks.append(_min_check(f"amongcogs.coverage.{key}", amongcogs.coverage[key], 1.0 if key == "winner_declared_rate" else 0.0001))
    checks.append(_min_check("amongcogs.winners.crew", amongcogs.winners.get("crew", 0), 1))
    checks.append(_min_check("amongcogs.winners.impostor", amongcogs.winners.get("impostor", 0), 1))
    return ParityReport(bitworld=bitworld, amongcogs=amongcogs, checks=checks)


def format_summary(report: ParityReport) -> str:
    failed = [check for check in report.checks if not check.passed]
    lines = [
        f"amongcogs.parity passed={report.passed} checks={len(report.checks)} failed={len(failed)}",
        (
            "bitworld "
            f"bots={report.bitworld.connected_bots}/{report.bitworld.bot_logs} "
            f"task_holds={report.bitworld.task_holds} "
            f"map_locks={report.bitworld.map_locks} "
            f"replay_bytes={report.bitworld.replay_bytes} "
            f"ticks={report.bitworld.replay_tick_hashes} "
            f"inputs={report.bitworld.replay_inputs}"
        ),
        (
            "amongcogs "
            f"episodes={report.amongcogs.episodes} "
            f"completion={report.amongcogs.completion_rate:.3f} "
            f"winners={report.amongcogs.winners} "
            f"meeting_talk={int(report.amongcogs.actions.get('meeting_talk_actions', 0))} "
            f"ballot_talk={int(report.amongcogs.actions.get('ballot_talk_actions', 0))}"
        ),
    ]
    for check in failed:
        lines.append(f"failed {check.name}: observed={check.observed} threshold={check.threshold}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare BitWorld AmongThem logs with an AmongCogs audit JSON.")
    parser.add_argument("--bitworld-log-dir", type=Path, required=True)
    parser.add_argument("--bitworld-replay", type=Path)
    parser.add_argument("--amongcogs-audit-json", type=Path, required=True)
    parser.add_argument("--output", choices=("summary", "json", "both"), default="summary")
    args = parser.parse_args()

    bitworld = summarize_bitworld_run(args.bitworld_log_dir, args.bitworld_replay)
    amongcogs = summarize_amongcogs_audit(json.loads(args.amongcogs_audit_json.read_text()))
    report = build_parity_report(bitworld, amongcogs)
    if args.output in {"summary", "both"}:
        print(format_summary(report))
    if args.output in {"json", "both"}:
        print(report.model_dump_json(indent=2))
    if not report.passed:
        raise SystemExit(1)


def _connected_bot_names(bot_logs: list[Path]) -> list[str]:
    names: list[str] = []
    for path in bot_logs:
        text = path.read_text()
        if BITWORLD_CONNECTED_RE.search(text):
            names.append(path.stem)
    return names


def _min_check(name: str, observed: float | int, threshold: float | int) -> ParityCheck:
    return ParityCheck(name=name, passed=observed >= threshold, observed=observed, threshold=threshold)


def _eq_check(name: str, observed: float | int | str | None, expected: float | int | str) -> ParityCheck:
    return ParityCheck(name=name, passed=observed == expected, observed=str(observed), threshold=str(expected))


def _dict_or_empty(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _summarize_bitworld_replay(replay_path: Path) -> dict[str, object]:
    data = replay_path.read_bytes()
    offset = 0
    magic = data[:8]
    offset += 8
    if magic != b"BITWORLD":
        raise ValueError(f"{replay_path} is not a BITWORLD replay")
    version = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    if version != 2:
        raise ValueError(f"{replay_path} has unsupported replay version {version}")
    game_name, offset = _read_replay_string(data, offset)
    game_version, offset = _read_replay_string(data, offset)
    if game_name != "among_them" or game_version != "1":
        raise ValueError(f"{replay_path} is {game_name} v{game_version}, expected among_them v1")
    offset += 8
    config_text, offset = _read_replay_string(data, offset)
    config = json.loads(config_text)
    result = {
        "joins": 0,
        "leaves": 0,
        "inputs": 0,
        "nonzero_inputs": 0,
        "tick_hashes": 0,
        "last_tick": 0,
        **config,
    }
    while offset < len(data):
        record_type = data[offset]
        offset += 1
        if record_type == 1:
            tick = struct.unpack_from("<I", data, offset)[0]
            offset += 12
            result["tick_hashes"] = int(result["tick_hashes"]) + 1
            result["last_tick"] = tick
        elif record_type == 2:
            offset += 4
            offset += 1
            keys = data[offset]
            offset += 1
            result["inputs"] = int(result["inputs"]) + 1
            result["nonzero_inputs"] = int(result["nonzero_inputs"]) + int(keys != 0)
        elif record_type == 3:
            offset += 4
            offset += 1
            _, offset = _read_replay_string(data, offset)
            result["joins"] = int(result["joins"]) + 1
        elif record_type == 4:
            offset += 5
            result["leaves"] = int(result["leaves"]) + 1
        else:
            raise ValueError(f"{replay_path} has unknown replay record {record_type} at byte {offset - 1}")
    return result


def _read_replay_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    value = data[offset : offset + length].decode("utf-8")
    return value, offset + length


if __name__ == "__main__":
    main()
