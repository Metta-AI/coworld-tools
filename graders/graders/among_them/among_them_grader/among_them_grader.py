from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    return path.read_bytes()


def write_uri(uri: str, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            uri,
            data=encoded,
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            response.read()
        return
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def values(results: dict[str, object], key: str) -> list[object]:
    value = results[key] if key in results else []
    if isinstance(value, list):
        return value
    return []


def interestingness(results: dict[str, object]) -> float:
    scores = [float(score) for score in values(results, "scores")]
    wins = [bool(win) for win in values(results, "win")]
    tasks = [int(task) for task in values(results, "tasks")]
    kills = [int(kill) for kill in values(results, "kills")]

    win_balance = 1.0 if any(wins) and not all(wins) else 0.25
    score_spread = (max(scores) - min(scores)) / max(abs(max(scores)), 1.0) if scores else 0.0
    task_signal = min(sum(tasks) / max(len(tasks), 1) / 8.0, 1.0) if tasks else 0.0
    kill_signal = min(sum(kills) / max(len(kills), 1), 1.0) if kills else 0.0
    return round(min(1.0, 0.35 * win_balance + 0.25 * score_spread + 0.25 * task_signal + 0.15 * kill_signal), 4)


def main() -> None:
    results = json.loads(read_uri(os.environ["COGAME_RESULTS_URI"]))
    score = interestingness(results)
    write_uri(os.environ["COGAME_GRADE_OUTPUT_URI"], {"score": score})
    print(f"wrote Among Them grade {score}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
