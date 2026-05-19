from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from .documents import all_documents, validate_doc_slugs
from .framework import build_agent_framework_ref
from .pipeline import normalize_runner_names, run_pipeline


LOGGER = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    source = args.source.expanduser()
    if not source.exists() or not source.is_dir():
        parser.error(f"source must be an existing directory: {source}")

    agent_framework = build_agent_framework_ref(args.agent_framework_dir)
    if args.agent_framework_dir is not None and not agent_framework.framework_dir.is_dir():
        parser.error(f"agent-framework-dir must be an existing directory: {agent_framework.framework_dir}")

    if args.only:
        unknown = validate_doc_slugs(args.only)
        if unknown:
            available = ", ".join(document.slug for document in all_documents())
            parser.error(f"unknown document slug(s): {', '.join(unknown)}. Available: {available}")

    try:
        runner_names = normalize_runner_names(args.runners)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        result = run_pipeline(
            source,
            output_dir=args.output_dir,
            only=args.only,
            through_stage=args.through_stage,
            claude_model=args.claude_model,
            codex_model=args.codex_model,
            agent_framework=agent_framework,
            runners=runner_names,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            max_parallel=args.max_parallel,
        )
    except Exception as exc:
        LOGGER.error("Pipeline failed: %s", exc)
        return 1

    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate guide_v1 game reference documents.",
    )
    parser.add_argument("source", type=Path, help="Path to the game source directory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Directory where generated documents are written",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="DOC",
        help="Generate only specific lowercase-hyphenated document slugs",
    )
    parser.add_argument(
        "--through-stage",
        type=_stage_number,
        metavar="N",
        help="Generate stages 1 through N only",
    )
    parser.add_argument("--claude-model", help="Override Claude model")
    parser.add_argument("--codex-model", help="Override Codex model")
    parser.add_argument(
        "--runner",
        "--coding-agent",
        dest="runners",
        action="append",
        metavar="RUNNER",
        help=(
            "Coding agent CLI to use for drafts. Repeat or comma-separate values. "
            "Available: claude/clod and codex/codec. Defaults to both."
        ),
    )
    parser.add_argument(
        "--agent-framework-dir",
        type=Path,
        help=(
            "Path to a Cyborg agent policy framework. Defaults to the in-repo "
            "src/players_lib/coborg package."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Print generation plan and exit")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not regenerate documents that already exist in the output directory",
    )
    parser.add_argument(
        "--max-parallel",
        type=_positive_int,
        default=4,
        metavar="N",
        help="Maximum concurrent document generations per stage",
    )
    return parser


def _stage_number(value: str) -> int:
    try:
        stage = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("stage must be an integer from 1 to 7") from exc
    if stage < 1 or stage > 7:
        raise argparse.ArgumentTypeError("stage must be an integer from 1 to 7")
    return stage


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed
