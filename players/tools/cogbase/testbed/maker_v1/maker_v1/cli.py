from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from .bootstrap import BootstrapError, run_visual_bootstrap
from .build_plan import MakerError, generate_plan
from .framework import build_agent_framework_ref
from .policy_builder import PolicyBuildError, build_policy_from_labels
from .smoke import SmokeError, run_smoke_test


LOGGER = logging.getLogger(__name__)


_DEPRECATION_BANNER = (
    "WARNING: maker_v1 is DEPRECATED. New work should go into maker_v2 "
    "(testbed/maker_v2/). See docs/designs/maker_v1_deprecation.md."
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    LOGGER.warning(_DEPRECATION_BANNER)

    guide_dir = args.guide_dir.expanduser()
    if not guide_dir.exists() or not guide_dir.is_dir():
        parser.error(f"guide-dir must be an existing directory: {guide_dir}")

    game_source = args.game_source.expanduser() if args.game_source else None
    if game_source is not None and (not game_source.exists() or not game_source.is_dir()):
        parser.error(f"game-source must be an existing directory: {game_source}")

    agent_framework = None
    if args.agent_framework_dir is not None:
        agent_framework = build_agent_framework_ref(args.agent_framework_dir)
    if agent_framework is not None and not agent_framework.framework_dir.is_dir():
        parser.error(f"agent-framework-dir must be an existing directory: {agent_framework.framework_dir}")

    if args.update_parsers:
        parser.error("--update-parsers is designed but not implemented yet")

    if args.visual_bootstrap and args.frames_dir is None:
        parser.error("--visual-bootstrap currently requires --frames-dir")
    if args.smoke_test and not args.agent_url:
        parser.error("--smoke-test requires --agent-url")
    if args.server_cwd is not None and not args.server_cwd.expanduser().is_dir():
        parser.error(f"--server-cwd must be an existing directory: {args.server_cwd}")

    try:
        result = generate_plan(
            guide_dir,
            output_dir=args.output_dir,
            game_source=game_source,
            agent_framework=agent_framework,
        )
        bootstrap_result = None
        policy_result = None
        smoke_result = None
        if args.visual_bootstrap:
            bootstrap_result = run_visual_bootstrap(
                output_dir=result.output_dir,
                frames_dir=args.frames_dir,
                budget=args.vlm_budget,
                provider=args.vlm_provider,
                decode_observations=args.decode_observations,
            )
        if args.build_policy_from_labels:
            policy_result = build_policy_from_labels(result.output_dir)
        if args.smoke_test:
            smoke_result = run_smoke_test(
                output_dir=result.output_dir,
                agent_url=args.agent_url,
                server_command=args.server_command,
                server_cwd=args.server_cwd,
                health_url=args.health_url,
                startup_timeout=args.startup_timeout,
                run_timeout=args.smoke_timeout,
                agent_max_frames=args.agent_max_frames,
            )
    except MakerError as exc:
        LOGGER.error("%s", exc)
        return 1
    except BootstrapError as exc:
        LOGGER.error("%s", exc)
        return 1
    except PolicyBuildError as exc:
        LOGGER.error("%s", exc)
        return 1
    except SmokeError as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info("Wrote maker_v1 plan: %s", result.plan_file)
    LOGGER.info("Wrote maker_v1 manifest: %s", result.manifest_file)
    LOGGER.info("Observation surface: %s", result.observation_surface.category)
    if result.agent_files:
        LOGGER.info("Wrote maker_v1 agent artifacts under: %s", result.output_dir / "agent")
    if bootstrap_result is not None:
        LOGGER.info(
            "Visual bootstrap wrote %s label%s -> %s",
            bootstrap_result.labels_written,
            "" if bootstrap_result.labels_written == 1 else "s",
            bootstrap_result.report_file,
        )
    if policy_result is not None:
        LOGGER.info(
            "Policy bootstrap read %s label%s and wrote %s rule%s",
            policy_result.labels_read,
            "" if policy_result.labels_read == 1 else "s",
            policy_result.rules_written,
            "" if policy_result.rules_written == 1 else "s",
        )
    if smoke_result is not None:
        LOGGER.info(
            "Smoke test %s -> %s",
            "passed" if smoke_result.passed else "failed",
            smoke_result.report_file,
        )
        return 0 if smoke_result.passed else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate maker_v1 baseline-agent artifacts from a guide_v1 bundle.",
    )
    parser.add_argument(
        "guide_dir",
        type=Path,
        help="Path to a generated guide_v1 guide bundle",
    )
    parser.add_argument(
        "--game-source",
        type=Path,
        help="Optional path to the original game source directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated maker_v1 artifacts. Defaults to ./output/<guide-dir-name>",
    )
    parser.add_argument(
        "--agent-framework-dir",
        type=Path,
        help=(
            "Path to a Cyborg agent policy framework. Defaults to the in-repo "
            "players/player_sdk package."
        ),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Accepted for compatibility; symbolic guide bundles now also receive a starter agent scaffold",
    )
    parser.add_argument(
        "--visual-bootstrap",
        action="store_true",
        help="Run the Phase 4 budgeted visual bootstrap loop over --frames-dir",
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        help="Directory of captured frame/message files to label during --visual-bootstrap",
    )
    parser.add_argument(
        "--decode-observations",
        action="store_true",
        help="Decode captured raw observations through agent/perception/decoder.py before VLM labeling",
    )
    parser.add_argument(
        "--vlm-budget",
        type=_positive_int,
        default=25,
        metavar="N",
        help="Maximum VLM labeling calls for --visual-bootstrap",
    )
    parser.add_argument(
        "--vlm-provider",
        default="mock",
        choices=("mock", "bedrock", "openai", "anthropic"),
        help="VLM provider for --visual-bootstrap. Implemented providers: mock, bedrock.",
    )
    parser.add_argument(
        "--build-policy-from-labels",
        action="store_true",
        help="Generate agent/policy_from_labels.py from existing or newly written VLM labels",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run the generated agent against a local or already-running game server",
    )
    parser.add_argument(
        "--agent-url",
        help="WebSocket URL passed to generated agent/run_agent.py during --smoke-test",
    )
    parser.add_argument(
        "--server-command",
        help="Optional command to start the local game server before --smoke-test",
    )
    parser.add_argument(
        "--server-cwd",
        type=Path,
        help="Working directory for --server-command",
    )
    parser.add_argument(
        "--health-url",
        help="Optional HTTP URL polled until the server is ready before running the agent",
    )
    parser.add_argument(
        "--startup-timeout",
        type=_positive_float,
        default=10.0,
        metavar="SECONDS",
        help="Maximum time to wait for server startup or --health-url",
    )
    parser.add_argument(
        "--smoke-timeout",
        type=_positive_float,
        default=30.0,
        metavar="SECONDS",
        help="Maximum time to let generated agent/run_agent.py run during --smoke-test",
    )
    parser.add_argument(
        "--agent-max-frames",
        type=_positive_int,
        default=25,
        metavar="N",
        help="Max frames for generated visual agents that support --max-frames during --smoke-test",
    )
    parser.add_argument(
        "--update-parsers",
        action="store_true",
        help="Reserved for the future parser-generation phase",
    )
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive number")
    return parsed
