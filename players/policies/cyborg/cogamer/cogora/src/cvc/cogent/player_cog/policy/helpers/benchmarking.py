"""Benchmark analysis for comparing cyborg policy runs.

Adapted from llm-agent's analyze_results.py. Loads JSONL artifact files
(experience_trace.jsonl, decision_log.jsonl, pilot_generation.jsonl) and
computes per-run and cross-run statistics with outlier filtering.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MetricStats:
    """Statistics for a single metric with outlier filtering."""

    values: list[float] = field(default_factory=list)
    filtered_values: list[float] = field(default_factory=list)
    outliers_removed: int = 0

    @property
    def n(self) -> int:
        return len(self.filtered_values)

    @property
    def mean(self) -> float | None:
        return statistics.mean(self.filtered_values) if self.filtered_values else None

    @property
    def variance(self) -> float | None:
        return statistics.variance(self.filtered_values) if len(self.filtered_values) > 1 else None

    @property
    def std_dev(self) -> float | None:
        return statistics.stdev(self.filtered_values) if len(self.filtered_values) > 1 else None

    @property
    def min_val(self) -> float | None:
        return min(self.filtered_values) if self.filtered_values else None

    @property
    def max_val(self) -> float | None:
        return max(self.filtered_values) if self.filtered_values else None


def filter_outliers(values: list[float], threshold: float = 2.0) -> tuple[list[float], int]:
    """Filter outliers beyond threshold standard deviations from mean.

    Returns (filtered_values, num_outliers_removed).
    """
    if len(values) < 3:
        return values, 0
    mean = statistics.mean(values)
    std = statistics.stdev(values)
    if std == 0:
        return values, 0
    filtered = [v for v in values if abs(v - mean) <= threshold * std]
    return filtered, len(values) - len(filtered)


def compute_metric_stats(values: list[float], outlier_threshold: float = 2.0) -> MetricStats:
    """Compute statistics for a metric with outlier filtering."""
    stats = MetricStats(values=values.copy())
    stats.filtered_values, stats.outliers_removed = filter_outliers(values, outlier_threshold)
    return stats


def format_metric(stats: MetricStats, fmt: str = ".1f") -> str:
    """Format a metric as 'mean +/- std_dev (-N outliers)'."""
    if stats.mean is None:
        return "N/A"
    parts = [f"{stats.mean:{fmt}}"]
    if stats.std_dev is not None:
        parts.append(f"\u00b1{stats.std_dev:{fmt}}")
    if stats.outliers_removed > 0:
        parts.append(f"(-{stats.outliers_removed})")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# JSONL loading
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Progress metric extraction from summary text
# ---------------------------------------------------------------------------

_PROGRESS_KEYS = (
    "steps_since_any_progress",
    "steps_since_heart_progress",
    "steps_since_resource_progress",
    "steps_since_map_control_progress",
    "progress_stalled",
    "heart_total",
    "resource_types_seen",
    "resource_types_missing",
    "team_resource_units",
    "objective_age_steps",
    "friendly_junctions_visible",
    "neutral_junctions_visible",
    "enemy_junctions_visible",
    "enemy_agents_visible",
)

_PROGRESS_PATTERN = re.compile(r"^- (\w+): (.+)$", re.MULTILINE)


def extract_progress_metrics(summary_text: str) -> dict[str, str]:
    """Extract key=value pairs from the PROGRESS section of a trace summary."""
    result = {}
    for match in _PROGRESS_PATTERN.finditer(summary_text):
        key, value = match.group(1), match.group(2).strip()
        if key in _PROGRESS_KEYS:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Stagnation detection
# ---------------------------------------------------------------------------


@dataclass
class StagnationPeriod:
    """A contiguous period where progress_stalled was True."""

    start_step: int
    end_step: int
    objective: str
    peak_steps_since_progress: int = 0

    @property
    def duration(self) -> int:
        return self.end_step - self.start_step + 1


def detect_stagnation_periods(traces: list[dict]) -> list[StagnationPeriod]:
    """Find contiguous stalled periods from experience trace records."""
    periods: list[StagnationPeriod] = []
    current: StagnationPeriod | None = None

    for trace in traces:
        step = trace.get("step", 0)
        summary = trace.get("summary", "")
        objective = trace.get("metadata", {}).get("objective", "")
        progress = extract_progress_metrics(summary)
        stalled = progress.get("progress_stalled") == "True"
        since_progress = int(progress.get("steps_since_any_progress", 0))

        if stalled:
            if current is None or objective != current.objective:
                if current is not None:
                    periods.append(current)
                current = StagnationPeriod(
                    start_step=step,
                    end_step=step,
                    objective=objective,
                    peak_steps_since_progress=since_progress,
                )
            else:
                current.end_step = step
                current.peak_steps_since_progress = max(current.peak_steps_since_progress, since_progress)
        else:
            if current is not None:
                periods.append(current)
                current = None

    if current is not None:
        periods.append(current)

    return periods


@dataclass
class StagnationSummary:
    """Aggregated stagnation stats for a run."""

    total_stalled_steps: int = 0
    stalled_fraction: float = 0.0
    longest_stall_duration: int = 0
    longest_stall_objective: str = ""
    num_stall_periods: int = 0
    peak_steps_since_progress: int = 0
    stalls_by_objective: dict[str, int] = field(default_factory=dict)


def summarize_stagnation(
    traces: list[dict],
    total_steps: int,
) -> StagnationSummary:
    """Build stagnation stats from experience traces."""
    periods = detect_stagnation_periods(traces)
    result = StagnationSummary(num_stall_periods=len(periods))

    for period in periods:
        result.total_stalled_steps += period.duration
        result.peak_steps_since_progress = max(result.peak_steps_since_progress, period.peak_steps_since_progress)
        obj = period.objective or "unknown"
        result.stalls_by_objective[obj] = result.stalls_by_objective.get(obj, 0) + period.duration
        if period.duration > result.longest_stall_duration:
            result.longest_stall_duration = period.duration
            result.longest_stall_objective = period.objective

    if total_steps > 0:
        result.stalled_fraction = result.total_stalled_steps / total_steps

    return result


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------


@dataclass
class RunSummary:
    """Aggregated metrics from one policy run's JSONL artifacts."""

    run_path: Path
    agent_id: int | None = None
    total_steps: int = 0

    # Generation / review counts
    generation_count: int = 0
    review_count: int = 0

    # Token accounting
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0

    # Per-generation token stats
    gen_input_tokens: list[int] = field(default_factory=list)
    gen_output_tokens: list[int] = field(default_factory=list)

    # Review details
    review_triggers: dict[str, int] = field(default_factory=dict)
    review_actions: dict[str, int] = field(default_factory=dict)
    policy_updates: int = 0
    scratchpad_updates: int = 0
    plan_updates: int = 0
    review_errors: int = 0
    review_none_count: int = 0

    # Stop reason breakdown
    stop_reasons: dict[str, int] = field(default_factory=dict)

    # Validation retries
    total_validation_retries: int = 0
    generations_with_retries: int = 0

    # Experience trace derived
    final_hearts: int = 0
    errors: int = 0

    # Role timeline
    role_steps: dict[str, int] = field(default_factory=dict)

    # Objective timeline
    objective_steps: dict[str, int] = field(default_factory=dict)
    objective_transitions: int = 0

    # Goal stability
    distinct_goals: int = 0

    # Target diversity
    distinct_target_entities: int = 0
    distinct_target_regions: int = 0
    steps_with_target_entity: int = 0
    steps_with_target_region: int = 0

    # Resource bias
    resource_bias_steps: dict[str, int] = field(default_factory=dict)

    # Stagnation
    stagnation: StagnationSummary = field(default_factory=StagnationSummary)

    # Heart production (derived from progress counter resets)
    heart_progress_events: int = 0
    peak_heart_total: int = 0

    # Economy progression (from summary progress metrics)
    start_resource_units: int = 0
    peak_resource_units: int = 0
    final_resource_units: int = 0
    resource_types_seen_final: int = 0
    friendly_junctions_final: int = 0
    peak_friendly_junctions: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def avg_input_tokens_per_gen(self) -> float:
        return statistics.mean(self.gen_input_tokens) if self.gen_input_tokens else 0.0

    @property
    def avg_output_tokens_per_gen(self) -> float:
        return statistics.mean(self.gen_output_tokens) if self.gen_output_tokens else 0.0

    @property
    def rewrite_success_rate(self) -> float:
        if self.review_count == 0:
            return 0.0
        return self.policy_updates / self.review_count

    @property
    def validation_retry_rate(self) -> float:
        if self.generation_count == 0:
            return 0.0
        return self.generations_with_retries / self.generation_count


def summarize_run(artifact_dir: Path) -> RunSummary:
    """Build a RunSummary from a single agent's artifact directory.

    Expects files like:
    - pilot_generation.jsonl (PolicyGenerationRecord)
    - decision_log.jsonl (ReviewDecisionRecord)
    - experience_trace.jsonl (ExperienceTraceRecord)
    """
    summary = RunSummary(run_path=artifact_dir)

    # --- pilot_generation.jsonl ---
    for record in load_jsonl(artifact_dir / "pilot_generation.jsonl"):
        summary.generation_count += 1
        metadata = record.get("metadata", {})
        input_tok = int(metadata.get("input_tokens", 0) or 0)
        output_tok = int(metadata.get("output_tokens", 0) or 0)
        summary.total_input_tokens += input_tok
        summary.total_output_tokens += output_tok
        summary.gen_input_tokens.append(input_tok)
        summary.gen_output_tokens.append(output_tok)
        summary.total_latency_ms += float(metadata.get("api_latency_ms", 0.0) or 0.0)
        if not record.get("success", True):
            summary.errors += 1
        stop = metadata.get("stop_reason", "")
        if stop:
            summary.stop_reasons[stop] = summary.stop_reasons.get(stop, 0) + 1
        retries = int(metadata.get("validation_retry_count", 0) or 0)
        summary.total_validation_retries += retries
        if retries > 0:
            summary.generations_with_retries += 1

    # --- decision_log.jsonl ---
    for record in load_jsonl(artifact_dir / "decision_log.jsonl"):
        summary.review_count += 1
        trigger = record.get("trigger_name", "unknown")
        summary.review_triggers[trigger] = summary.review_triggers.get(trigger, 0) + 1
        action = record.get("action", "unknown")
        summary.review_actions[action] = summary.review_actions.get(action, 0) + 1
        if action == "none":
            summary.review_none_count += 1
        if record.get("policy_updated"):
            summary.policy_updates += 1
        if record.get("scratchpad_updated"):
            summary.scratchpad_updates += 1
        if record.get("plan_updated"):
            summary.plan_updates += 1
        metadata = record.get("metadata", {})
        if metadata.get("review_error"):
            summary.review_errors += 1
        summary.total_input_tokens += int(metadata.get("input_tokens", 0) or 0)
        summary.total_output_tokens += int(metadata.get("output_tokens", 0) or 0)
        summary.total_latency_ms += float(metadata.get("api_latency_ms", 0.0) or 0.0)
        stop = metadata.get("stop_reason", "")
        if stop:
            summary.stop_reasons[stop] = summary.stop_reasons.get(stop, 0) + 1

    # --- experience_trace.jsonl ---
    traces = load_jsonl(artifact_dir / "experience_trace.jsonl")
    summary.total_steps = len(traces)

    goals: set[str] = set()
    target_entities: set[str] = set()
    target_regions: set[str] = set()
    prev_objective: str | None = None
    prev_since_heart: int | None = None

    for trace in traces:
        metadata = trace.get("metadata", {})
        summary.agent_id = trace.get("agent_id", summary.agent_id)

        role = metadata.get("role", "")
        if role:
            summary.role_steps[role] = summary.role_steps.get(role, 0) + 1

        objective = metadata.get("objective", "")
        if objective:
            summary.objective_steps[objective] = summary.objective_steps.get(objective, 0) + 1
            if prev_objective is not None and objective != prev_objective:
                summary.objective_transitions += 1
            prev_objective = objective

        goal = metadata.get("goal", "")
        if goal:
            goals.add(goal)

        target_eid = metadata.get("target_entity_id", "")
        if target_eid:
            target_entities.add(target_eid)
            summary.steps_with_target_entity += 1

        target_reg = metadata.get("target_region", "")
        if target_reg:
            target_regions.add(target_reg)
            summary.steps_with_target_region += 1

        bias = metadata.get("resource_bias", "")
        if bias:
            summary.resource_bias_steps[bias] = summary.resource_bias_steps.get(bias, 0) + 1

        # Track production metrics from progress
        progress = extract_progress_metrics(trace.get("summary", ""))

        heart_total = int(progress.get("heart_total", 0))
        if heart_total > summary.peak_heart_total:
            summary.peak_heart_total = heart_total
        since_heart = progress.get("steps_since_heart_progress")
        if since_heart is not None:
            since_heart_int = int(since_heart)
            if prev_since_heart is not None and since_heart_int < prev_since_heart:
                summary.heart_progress_events += 1
            prev_since_heart = since_heart_int

        resource_units = int(progress.get("team_resource_units", 0))
        if resource_units > summary.peak_resource_units:
            summary.peak_resource_units = resource_units

        friendly_junctions = int(progress.get("friendly_junctions_visible", 0))
        if friendly_junctions > summary.peak_friendly_junctions:
            summary.peak_friendly_junctions = friendly_junctions

    summary.distinct_goals = len(goals)
    summary.distinct_target_entities = len(target_entities)
    summary.distinct_target_regions = len(target_regions)

    if traces:
        first_progress = extract_progress_metrics(traces[0].get("summary", ""))
        summary.start_resource_units = int(first_progress.get("team_resource_units", 0))

        last_progress = extract_progress_metrics(traces[-1].get("summary", ""))
        summary.final_hearts = int(last_progress.get("heart_total", 0))
        summary.final_resource_units = int(last_progress.get("team_resource_units", 0))
        summary.resource_types_seen_final = int(last_progress.get("resource_types_seen", 0))
        summary.friendly_junctions_final = int(last_progress.get("friendly_junctions_visible", 0))

    summary.stagnation = summarize_stagnation(traces, summary.total_steps)

    return summary


# ---------------------------------------------------------------------------
# Cross-run comparison
# ---------------------------------------------------------------------------


def compare_runs(
    run_dirs: list[Path],
    outlier_threshold: float = 2.0,
) -> dict[str, MetricStats]:
    """Compare multiple runs and return per-metric statistics.

    Each path should be an agent artifact directory containing JSONL files.
    """
    summaries = [summarize_run(d) for d in run_dirs]

    return {
        "total_tokens": compute_metric_stats([float(s.total_tokens) for s in summaries], outlier_threshold),
        "input_tokens": compute_metric_stats([float(s.total_input_tokens) for s in summaries], outlier_threshold),
        "output_tokens": compute_metric_stats([float(s.total_output_tokens) for s in summaries], outlier_threshold),
        "avg_input_per_gen": compute_metric_stats([s.avg_input_tokens_per_gen for s in summaries], outlier_threshold),
        "avg_output_per_gen": compute_metric_stats([s.avg_output_tokens_per_gen for s in summaries], outlier_threshold),
        "generation_count": compute_metric_stats([float(s.generation_count) for s in summaries], outlier_threshold),
        "review_count": compute_metric_stats([float(s.review_count) for s in summaries], outlier_threshold),
        "rewrite_success_rate": compute_metric_stats([s.rewrite_success_rate for s in summaries], outlier_threshold),
        "validation_retry_rate": compute_metric_stats([s.validation_retry_rate for s in summaries], outlier_threshold),
        "total_steps": compute_metric_stats([float(s.total_steps) for s in summaries], outlier_threshold),
        "latency_ms": compute_metric_stats([s.total_latency_ms for s in summaries], outlier_threshold),
        "final_hearts": compute_metric_stats([float(s.final_hearts) for s in summaries], outlier_threshold),
        "errors": compute_metric_stats([float(s.errors) for s in summaries], outlier_threshold),
        "review_errors": compute_metric_stats([float(s.review_errors) for s in summaries], outlier_threshold),
        "objective_transitions": compute_metric_stats(
            [float(s.objective_transitions) for s in summaries], outlier_threshold
        ),
        "distinct_goals": compute_metric_stats([float(s.distinct_goals) for s in summaries], outlier_threshold),
        "distinct_targets": compute_metric_stats(
            [float(s.distinct_target_entities) for s in summaries], outlier_threshold
        ),
        "stalled_fraction": compute_metric_stats([s.stagnation.stalled_fraction for s in summaries], outlier_threshold),
        "longest_stall": compute_metric_stats(
            [float(s.stagnation.longest_stall_duration) for s in summaries], outlier_threshold
        ),
        "peak_no_progress": compute_metric_stats(
            [float(s.stagnation.peak_steps_since_progress) for s in summaries], outlier_threshold
        ),
        "num_stall_periods": compute_metric_stats(
            [float(s.stagnation.num_stall_periods) for s in summaries], outlier_threshold
        ),
        "final_resource_units": compute_metric_stats(
            [float(s.final_resource_units) for s in summaries], outlier_threshold
        ),
        "resource_growth": compute_metric_stats(
            [float(s.final_resource_units - s.start_resource_units) for s in summaries], outlier_threshold
        ),
        "peak_resource_units": compute_metric_stats(
            [float(s.peak_resource_units) for s in summaries], outlier_threshold
        ),
        "resource_types_seen": compute_metric_stats(
            [float(s.resource_types_seen_final) for s in summaries], outlier_threshold
        ),
        "peak_friendly_junctions": compute_metric_stats(
            [float(s.peak_friendly_junctions) for s in summaries], outlier_threshold
        ),
        "heart_progress_events": compute_metric_stats(
            [float(s.heart_progress_events) for s in summaries], outlier_threshold
        ),
    }
