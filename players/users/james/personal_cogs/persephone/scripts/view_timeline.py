#!/usr/bin/env python3
"""View timeline: summarize view transitions from a capture metadata file.

Reads the .jsonl sidecar produced by capture.py and prints a compact
timeline showing when view transitions happen.

Examples:
    python scripts/view_timeline.py /tmp/capture.jsonl

    # With frame counts
    python scripts/view_timeline.py /tmp/capture.jsonl --counts

Output:
    ticks   0-118  (119 frames)  unknown
    ticks 119-353  (235 frames)  role_reveal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_timeline(jsonl_path: Path) -> list[dict]:
    """Read all records from a .jsonl metadata file."""
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def summarize_transitions(records: list[dict]) -> list[dict]:
    """Group consecutive frames with the same view into spans.

    Returns a list of dicts with keys: view, start_tick, end_tick, count,
    start_wall_s, end_wall_s.
    """
    if not records:
        return []

    spans = []
    current_view = records[0]["view"]
    start_tick = records[0]["tick"]
    start_wall = records[0].get("wall_s", 0)

    for rec in records[1:]:
        if rec["view"] != current_view:
            spans.append({
                "view": current_view,
                "start_tick": start_tick,
                "end_tick": rec["tick"] - 1,
                "count": rec["tick"] - start_tick,
                "start_wall_s": start_wall,
                "end_wall_s": records[rec["tick"] - 1].get("wall_s", 0)
                if rec["tick"] - 1 < len(records) else 0,
            })
            current_view = rec["view"]
            start_tick = rec["tick"]
            start_wall = rec.get("wall_s", 0)

    # Final span
    last = records[-1]
    spans.append({
        "view": current_view,
        "start_tick": start_tick,
        "end_tick": last["tick"],
        "count": last["tick"] - start_tick + 1,
        "start_wall_s": start_wall,
        "end_wall_s": last.get("wall_s", 0),
    })

    return spans


def print_timeline(spans: list[dict], show_counts: bool = False) -> None:
    """Print the timeline in a compact format."""
    if not spans:
        print("(empty)")
        return

    # Find max tick width for alignment
    max_tick = max(s["end_tick"] for s in spans)
    tick_width = len(str(max_tick))

    for span in spans:
        start = str(span["start_tick"]).rjust(tick_width)
        end = str(span["end_tick"]).rjust(tick_width)
        count = span["count"]
        wall_start = span["start_wall_s"]
        wall_end = span["end_wall_s"]

        line = f"ticks {start}-{end}  ({count:>4d} frames, {wall_start:.1f}-{wall_end:.1f}s)  {span['view']}"
        print(line)

    # Summary
    print()
    total_frames = sum(s["count"] for s in spans)
    total_time = spans[-1]["end_wall_s"]
    unique_views = len(set(s["view"] for s in spans))
    print(f"Total: {total_frames} frames, {total_time:.1f}s, {unique_views} unique view(s)")

    if show_counts:
        print()
        print("View counts:")
        from collections import Counter
        counts = Counter()
        for s in spans:
            counts[s["view"]] += s["count"]
        for view, count in counts.most_common():
            print(f"  {view:20s} {count:>5d} frames")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize view transitions from a capture metadata file.",
    )
    parser.add_argument(
        "jsonl_path", type=Path,
        help="Path to the .jsonl metadata file from capture.py",
    )
    parser.add_argument(
        "--counts", action="store_true",
        help="Show per-view frame counts at the end",
    )
    args = parser.parse_args()

    if not args.jsonl_path.is_file():
        print(f"Error: file not found: {args.jsonl_path}", file=sys.stderr)
        return 1

    records = read_timeline(args.jsonl_path)
    if not records:
        print("No records found.", file=sys.stderr)
        return 1

    spans = summarize_transitions(records)
    print_timeline(spans, show_counts=args.counts)

    return 0


if __name__ == "__main__":
    sys.exit(main())
