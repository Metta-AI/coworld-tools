#!/usr/bin/env python3
"""eyes_v1: deprecated visual/UI report generator for game source code.

Takes a directory path or URL pointing to a game's source code and runs a
templated analysis prompt through opencode, codex, and claude CLI tools in
headless mode. Outputs are compiled into individual .md report files.

Usage:
    python generate_report.py <path_or_url> [--output-dir <dir>]

Examples:
    python generate_report.py ~/coding/metta
    python generate_report.py https://github.com/Metta-AI/metta
    python generate_report.py ./my-game --output-dir ./output/my-game
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
import time
from pathlib import Path


DEPRECATION_NOTICE = (
    "eyes_v1 is deprecated as a primary Cogbase pipeline stage. "
    "Use testbed/guide_v1 first for canonical game understanding; run eyes_v1 "
    "only for legacy regeneration or targeted visual-artifact experiments."
)


PROMPT_TEMPLATE = textwrap.dedent("""\
    You are an expert game UI/UX analyst and graphics cataloger. Your task is to
    perform a complete and comprehensive audit of the visuals, graphics, sprites,
    UI views, and UI elements of the game whose source code is located at:

        {source_location}

    Examine every relevant source file: rendering code, UI definitions, asset
    manifests, sprite sheets, scene definitions, view controllers, HTML/CSS
    templates, config files referencing visuals, and anything else that defines
    what a player *sees*.

    Produce a detailed Markdown report with the following structure:

    # Visual & UI Report: [Game Name]

    ## Overview
    A brief summary of the game's visual/graphical architecture (rendering
    engine, UI framework, asset pipeline, resolution, coordinate system, etc.)

    ## UI Views

    For EVERY distinct view/screen/scene in the game (e.g. main menu, lobby,
    settings, in-game HUD, chat overlay, inventory, game-over screen, loading
    screen, etc.), create a section:

    ### [View Name]

    **Description:** What this view is, when the player sees it, how they
    navigate to/from it.

    **Summary Table:**

    | Element | Type | Visual Description | Source Location |
    |---------|------|-------------------|-----------------|
    | ... | ... | ... | ... |

    The table must include EVERY graphical element that could appear in this
    view: buttons, labels, text fields, icons, sprites, animated elements,
    background layers, particle effects, overlays, progress bars, avatars,
    health bars, score displays, chat bubbles, tooltips, etc.

    **Element Details:**

    For each element in the table, provide a detailed paragraph covering:
    - Exact visual appearance (colors, dimensions, font, shape, animation)
    - States/variants (hover, active, disabled, selected, error)
    - Position/layout within the view
    - Source file(s) and line numbers where it is defined
    - Any relevant asset file paths (images, sprite sheets, fonts)

    ## Asset Inventory
    A summary of all graphical assets (images, sprite sheets, fonts, shaders,
    animations) with file paths and where they are used.

    ## Visual Constants & Theming
    Colors, fonts, spacing values, breakpoints, and any theming/skin system.

    ---

    Be exhaustive. Do not skip elements because they seem minor. Include every
    single visual element you can identify from the source code. If something is
    ambiguous, note the ambiguity rather than omitting it.
""")


def build_prompt(source_location: str) -> str:
    """Fill the analysis prompt template with the given source location."""
    return PROMPT_TEMPLATE.format(source_location=source_location)


RUNNER_TIMEOUT = 1800  # 30 minutes per runner (default)


def run_opencode(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run the prompt through opencode's headless CLI.

    opencode run accepts the prompt as positional args. We pass it as a single
    argument since it can be long.
    """
    result = subprocess.run(
        ["opencode", "run", prompt],
        capture_output=True,
        text=True,
        cwd=working_dir,
        timeout=timeout,
    )
    return result.stdout or result.stderr


def run_codex(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run the prompt through codex's non-interactive exec mode.

    Passes prompt via stdin (using '-') to avoid argument length limits.
    Uses read-only sandbox and writes last message to a temp file for
    reliable output capture (codex can be noisy on stdout).
    """
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "codex", "exec",
                "-s", "read-only",
                "-o", tmp_path,
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=timeout,
        )
        # Prefer the output file (contains just the final response)
        output_path = Path(tmp_path)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path.read_text(encoding="utf-8")
        return result.stdout or result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_claude(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run the prompt through claude's print (non-interactive) mode.

    Passes prompt as a positional argument with --print for non-interactive
    output. Adds --add-dir for local directories so claude can read the source.
    """
    cmd = ["claude", "--print", prompt]
    if working_dir:
        cmd.extend(["--add-dir", working_dir])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=working_dir,
        timeout=timeout,
    )
    return result.stdout or result.stderr


RUNNERS = {
    "opencode": run_opencode,
    "codex": run_codex,
    "claude": run_claude,
}


def resolve_source_location(path_or_url: str) -> tuple[str, str | None]:
    """Resolve input to a (location_string, working_dir_or_none) tuple.

    For local paths, returns the absolute path as both the location string
    and the working directory. For URLs, returns the URL with no working dir.
    """
    if path_or_url.startswith(("http://", "https://", "git@")):
        return path_or_url, None
    resolved = Path(path_or_url).expanduser().resolve()
    if not resolved.exists():
        print(f"Error: path does not exist: {resolved}", file=sys.stderr)
        sys.exit(1)
    return str(resolved), str(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deprecated visual/UI report generator. Use guide_v1 first for "
            "canonical game documentation."
        ),
    )
    parser.add_argument(
        "source",
        help="Directory path or URL to the game's source code.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to write generated report artifacts into (default: ./output).",
    )
    parser.add_argument(
        "--runners",
        nargs="+",
        choices=list(RUNNERS.keys()),
        default=list(RUNNERS.keys()),
        help="Which CLI runners to use (default: all three).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=RUNNER_TIMEOUT,
        help=f"Timeout in seconds per runner (default: {RUNNER_TIMEOUT}).",
    )
    args = parser.parse_args()

    print(f"DEPRECATED: {DEPRECATION_NOTICE}", file=sys.stderr)

    source_location, working_dir = resolve_source_location(args.source)
    prompt = build_prompt(source_location)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runner_timeout = args.timeout

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    print(f"Source: {source_location}")
    print(f"Output: {output_dir}")
    print(f"Runners: {', '.join(args.runners)}")
    print()

    for runner_name in args.runners:
        print(f"[{runner_name}] Running analysis...", flush=True)
        runner_fn = RUNNERS[runner_name]
        try:
            output = runner_fn(prompt, working_dir, runner_timeout)
        except subprocess.TimeoutExpired:
            output = f"# Error\n\nRunner `{runner_name}` timed out after {runner_timeout} seconds."
            print(f"[{runner_name}] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            output = f"# Error\n\n`{runner_name}` CLI not found on PATH."
            print(f"[{runner_name}] CLI NOT FOUND", file=sys.stderr)

        filename = f"visual_report_{runner_name}_{timestamp}.md"
        out_path = output_dir / filename
        out_path.write_text(output, encoding="utf-8")
        print(f"[{runner_name}] Done -> {out_path}")

    print("\nAll reports generated.")


if __name__ == "__main__":
    main()
