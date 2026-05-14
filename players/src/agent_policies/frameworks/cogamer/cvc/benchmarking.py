"""Benchmark analysis helpers for Cogamer learnings files."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_OBJECTIVES = ("resource_coverage", "economy_bootstrap", "aligner_pressure", "unknown")


@dataclass
class MetricStats:
    values: list[float] = field(default_factory=list)
    filtered_values: list[float] = field(default_factory=list)
    outliers_removed: int = 0

    @property
    def mean(self) -> float | None:
        return statistics.mean(self.filtered_values) if self.filtered_values else None

    @property
    def std_dev(self) -> float | None:
        return (
            statistics.stdev(self.filtered_values)
            if len(self.filtered_values) > 1
            else None
        )


@dataclass
class StagnationSummary:
    total_stalled_steps: int = 0
    stalled_fraction: float = 0.0
    longest_stall_duration: int = 0
    num_stall_periods: int = 0
    stalls_by_objective: dict[str, int] = field(default_factory=dict)
    longest_stall_by_objective: dict[str, int] = field(default_factory=dict)
    num_periods_by_objective: dict[str, int] = field(default_factory=dict)


@dataclass
class LearningRunSummary:
    path: Path
    game_id: str = ""
    total_steps: int = 0
    agents: int = 0
    snapshot_count: int = 0
    llm_count: int = 0
    llm_errors: int = 0
    total_latency_ms: float = 0.0
    final_hearts: int = 0
    final_resource_units: int = 0
    peak_resource_units: int = 0
    resource_types_seen_final: int = 0
    friendly_junctions_final: int = 0
    peak_friendly_junctions: int = 0
    stagnation: StagnationSummary = field(default_factory=StagnationSummary)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.llm_count if self.llm_count else 0.0

    @property
    def llm_error_rate(self) -> float:
        return self.llm_errors / self.llm_count if self.llm_count else 0.0


def load_learning_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_learning_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def summarize_learning_file(path: Path) -> LearningRunSummary:
    payload = load_learning_file(path)
    snapshots = _records(payload.get("snapshots", []))
    llm_log = _records(payload.get("llm_log", []))
    summary = LearningRunSummary(
        path=path,
        game_id=str(payload.get("game_id", "")),
        snapshot_count=len(snapshots),
        llm_count=len(llm_log),
        llm_errors=sum(1 for record in llm_log if record.get("error")),
        total_latency_ms=sum(
            float(record.get("latency_ms", 0) or 0) for record in llm_log
        ),
    )
    summary.agents = len(
        {
            int(record.get("agent_id", record.get("agent", 0)) or 0)
            for record in snapshots
        }
    )
    summary.total_steps = max(
        (int(record.get("step", 0) or 0) for record in snapshots), default=0
    )

    final_by_agent = _final_snapshots_by_agent(snapshots)
    final_metrics = [_snapshot_metrics(record) for record in final_by_agent.values()]
    peak_metrics = [_snapshot_metrics(record) for record in snapshots]
    summary.final_hearts = sum(
        int(metrics.get("heart_total", 0) or 0) for metrics in final_metrics
    )
    summary.final_resource_units = max(
        (int(m.get("team_resource_units", 0) or 0) for m in final_metrics), default=0
    )
    summary.peak_resource_units = max(
        (int(m.get("team_resource_units", 0) or 0) for m in peak_metrics), default=0
    )
    summary.resource_types_seen_final = max(
        (int(m.get("resource_types_seen", 0) or 0) for m in final_metrics),
        default=0,
    )
    summary.friendly_junctions_final = max(
        (int(m.get("friendly_junctions_visible", 0) or 0) for m in final_metrics),
        default=0,
    )
    summary.peak_friendly_junctions = max(
        (int(m.get("friendly_junctions_visible", 0) or 0) for m in peak_metrics),
        default=0,
    )
    summary.stagnation = summarize_stagnation(
        snapshots, total_steps=summary.total_steps
    )
    return summary


def summarize_stagnation(
    records: list[dict[str, Any]], *, total_steps: int
) -> StagnationSummary:
    result = StagnationSummary()
    for agent_records in _snapshots_by_agent(records).values():
        current_objective = ""
        current_duration = 0
        for index, record in enumerate(agent_records):
            metrics = _snapshot_metrics(record)
            stalled = bool(metrics.get("stalled", False)) or bool(
                metrics.get("oscillating", False)
            )
            duration = _record_duration(agent_records, index)
            objective = _objective(record)
            if stalled:
                result.total_stalled_steps += duration
                result.stalls_by_objective[objective] = (
                    result.stalls_by_objective.get(objective, 0) + duration
                )
                if current_duration == 0 or objective != current_objective:
                    if current_duration > 0:
                        _record_stall_period(
                            result, current_objective, current_duration
                        )
                    current_objective = objective
                    current_duration = duration
                else:
                    current_duration += duration
            elif current_duration > 0:
                _record_stall_period(result, current_objective, current_duration)
                current_duration = 0
        if current_duration > 0:
            _record_stall_period(result, current_objective, current_duration)
    if total_steps > 0:
        result.stalled_fraction = result.total_stalled_steps / total_steps
    return result


def compare_learning_runs(
    run_files: list[Path], outlier_threshold: float = 2.0
) -> dict[str, MetricStats]:
    summaries = [summarize_learning_file(path) for path in run_files]
    metrics = {
        "total_steps": [float(summary.total_steps) for summary in summaries],
        "llm_count": [float(summary.llm_count) for summary in summaries],
        "llm_error_rate": [summary.llm_error_rate for summary in summaries],
        "avg_latency_ms": [summary.avg_latency_ms for summary in summaries],
        "final_hearts": [float(summary.final_hearts) for summary in summaries],
        "final_resource_units": [
            float(summary.final_resource_units) for summary in summaries
        ],
        "peak_resource_units": [
            float(summary.peak_resource_units) for summary in summaries
        ],
        "resource_types_seen": [
            float(summary.resource_types_seen_final) for summary in summaries
        ],
        "friendly_junctions_final": [
            float(summary.friendly_junctions_final) for summary in summaries
        ],
        "peak_friendly_junctions": [
            float(summary.peak_friendly_junctions) for summary in summaries
        ],
        "stalled_fraction": [
            summary.stagnation.stalled_fraction for summary in summaries
        ],
        "longest_stall": [
            float(summary.stagnation.longest_stall_duration) for summary in summaries
        ],
        "num_stall_periods": [
            float(summary.stagnation.num_stall_periods) for summary in summaries
        ],
    }
    for objective in _OBJECTIVES:
        metrics[f"stall_steps_{objective}"] = [
            float(summary.stagnation.stalls_by_objective.get(objective, 0))
            for summary in summaries
        ]
        metrics[f"longest_stall_{objective}"] = [
            float(summary.stagnation.longest_stall_by_objective.get(objective, 0))
            for summary in summaries
        ]
        metrics[f"num_stalls_{objective}"] = [
            float(summary.stagnation.num_periods_by_objective.get(objective, 0))
            for summary in summaries
        ]
    return {
        name: compute_metric_stats(values, outlier_threshold)
        for name, values in metrics.items()
    }


def compute_metric_stats(
    values: list[float], outlier_threshold: float = 2.0
) -> MetricStats:
    filtered_values, outliers_removed = filter_outliers(values, outlier_threshold)
    return MetricStats(
        values=list(values),
        filtered_values=filtered_values,
        outliers_removed=outliers_removed,
    )


def filter_outliers(
    values: list[float], threshold: float = 2.0
) -> tuple[list[float], int]:
    if len(values) < 3:
        return values, 0
    mean = statistics.mean(values)
    std_dev = statistics.stdev(values)
    if std_dev == 0:
        return values, 0
    filtered = [value for value in values if abs(value - mean) <= threshold * std_dev]
    return filtered, len(values) - len(filtered)


def format_metric(stats: MetricStats, fmt: str = ".2f") -> str:
    if stats.mean is None:
        return "N/A"
    text = f"{stats.mean:{fmt}}"
    if stats.std_dev is not None:
        text += f" +/- {stats.std_dev:{fmt}}"
    if stats.outliers_removed:
        text += f" (-{stats.outliers_removed})"
    return text


def _records(value: Any) -> list[dict[str, Any]]:
    return (
        [record for record in value if isinstance(record, dict)]
        if isinstance(value, list)
        else []
    )


def _final_snapshots_by_agent(
    records: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    final: dict[int, dict[str, Any]] = {}
    for record in records:
        agent_id = int(record.get("agent_id", record.get("agent", 0)) or 0)
        if agent_id not in final or int(record.get("step", 0) or 0) >= int(
            final[agent_id].get("step", 0) or 0
        ):
            final[agent_id] = record
    return final


def _snapshots_by_agent(
    records: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        agent_id = int(record.get("agent_id", record.get("agent", 0)) or 0)
        grouped.setdefault(agent_id, []).append(record)
    for agent_records in grouped.values():
        agent_records.sort(key=lambda record: int(record.get("step", 0) or 0))
    return grouped


def _record_duration(records: list[dict[str, Any]], index: int) -> int:
    step = int(records[index].get("step", 0) or 0)
    if index + 1 >= len(records):
        return 1
    next_step = int(records[index + 1].get("step", step + 1) or step + 1)
    return max(1, next_step - step)


def _record_stall_period(
    result: StagnationSummary, objective: str, duration: int
) -> None:
    result.num_stall_periods += 1
    result.num_periods_by_objective[objective] = (
        result.num_periods_by_objective.get(objective, 0) + 1
    )
    result.longest_stall_duration = max(result.longest_stall_duration, duration)
    result.longest_stall_by_objective[objective] = max(
        result.longest_stall_by_objective.get(objective, 0),
        duration,
    )


def _snapshot_metrics(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = record.get("metrics_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    inventory = record.get("inventory", {})
    team_resources = record.get("team_resources", record.get("resources", {}))
    junctions = record.get("junctions", {})
    metrics: dict[str, Any] = {
        "stalled": bool(record.get("stalled", False)),
        "oscillating": bool(record.get("oscillating", False)),
    }
    if isinstance(inventory, dict):
        metrics["heart_total"] = int(inventory.get("heart", 0) or 0)
    if isinstance(team_resources, dict):
        resources = {
            element: int(team_resources.get(element, 0) or 0) for element in _ELEMENTS
        }
        metrics["team_resource_units"] = sum(resources.values())
        metrics["resource_types_seen"] = sum(
            1 for amount in resources.values() if amount > 0
        )
    if isinstance(junctions, dict):
        metrics["friendly_junctions_visible"] = int(junctions.get("friendly", 0) or 0)
        metrics["neutral_junctions_visible"] = int(junctions.get("neutral", 0) or 0)
        metrics["enemy_junctions_visible"] = int(junctions.get("enemy", 0) or 0)
    return metrics


def _objective(record: dict[str, Any]) -> str:
    objective = record.get("objective")
    if isinstance(objective, str) and objective:
        return objective
    snapshot = record.get("metrics_snapshot")
    if isinstance(snapshot, dict):
        snapshot_objective = snapshot.get("objective")
        if isinstance(snapshot_objective, str) and snapshot_objective:
            return snapshot_objective
    return "unknown"
