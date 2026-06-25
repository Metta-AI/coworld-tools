#!/usr/bin/env python3
"""Run offline Eurydice LLM shadow evaluation over saved context packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.eurydice.llm_provider import make_provider  # noqa: E402
from agents.eurydice.llm_shadow import (  # noqa: E402
    evaluate_contexts,
    load_contexts,
    summary_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSON/JSONL context file or directory")
    parser.add_argument(
        "--provider",
        default="heuristic",
        help="Deterministic provider to use: heuristic or hold",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine JSON")
    args = parser.parse_args(argv)

    provider = make_provider(args.provider)
    contexts = load_contexts(args.path)
    summary = evaluate_contexts(contexts, provider)

    if args.json:
        print(summary_json(summary))
    else:
        print(f"contexts_total: {summary.contexts_total}")
        print(f"accepted: {summary.accepted}")
        print(f"rejected: {summary.rejected}")
        print("actions: " + json.dumps(summary.actions, sort_keys=True))
        print(
            "rejection_reasons: "
            + json.dumps(summary.rejection_reasons, sort_keys=True)
        )
    return 1 if summary.contexts_total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
