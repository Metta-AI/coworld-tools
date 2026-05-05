#!/usr/bin/env python3
"""Extract a single frame from a capture as a test fixture.

Pulls one frame from a .npy capture file and saves it as a fixture pair:
  - {fixtures_dir}/{name}.npy   -- single (128, 128) uint8 frame
  - {fixtures_dir}/{name}.json  -- draft expected output from parse_frame()

The .json file is pre-filled with the current parse_frame() output as a
starting point.  Review and correct it before committing as ground truth.

Examples:
    # Extract tick 55 as a role_reveal fixture
    python scripts/extract_fixture.py \\
        --input /tmp/capture.npy --tick 55 --name role_reveal_shades

    # Extract with a note about what this fixture tests
    python scripts/extract_fixture.py \\
        --input /tmp/capture.npy --tick 503 --name playing_underworld \\
        --note "First frame after role reveal, HUD shows R1 0:15"

    # Override the view label (when detector is wrong)
    python scripts/extract_fixture.py \\
        --input /tmp/capture.npy --tick 10 --name lobby_full \\
        --view lobby
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

# Ensure perception is importable
_SCRIPT_DIR = Path(__file__).resolve().parent
_PERSEPHONE_ROOT = _SCRIPT_DIR.parent
if str(_PERSEPHONE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PERSEPHONE_ROOT))

from perception import parse_frame  # noqa: E402
from perception.types import FramePerception, View  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------

_FIXTURES_DIR = _PERSEPHONE_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Perception result serialization
# ---------------------------------------------------------------------------


def perception_to_assertions(perc: FramePerception) -> dict[str, Any]:
    """Convert a FramePerception to a dict of assertable fields.

    Extracts the non-None fields from the appropriate sub-perception and
    flattens them into dot-notation paths for use in test assertions.

    Returns a dict ready for the "assertions" key in the fixture .json.
    """
    assertions: dict[str, Any] = {}

    if perc.overworld is not None:
        ow = perc.overworld
        if ow.round is not None:
            assertions["overworld.round"] = ow.round
        if ow.timer_secs is not None:
            assertions["overworld.timer_secs"] = ow.timer_secs
        if ow.role_name is not None:
            assertions["overworld.role_name"] = ow.role_name
        if ow.role_team_color is not None:
            assertions["overworld.role_team_color"] = int(ow.role_team_color)
        if ow.room is not None:
            assertions["overworld.room"] = ow.room.value
        if ow.self_position is not None:
            assertions["overworld.self_position"] = {"not_none": True}
        if ow.minimap_dots:
            assertions["overworld.minimap_dot_count"] = {
                "gte": len(ow.minimap_dots),
                "lte": len(ow.minimap_dots),
            }
        if ow.bottom_bar is not None:
            assertions["overworld.bottom_bar"] = {"not_none": True}
        if ow.last_shout is not None:
            assertions["overworld.last_shout"] = {"not_none": True}
        if ow.speech_bubbles:
            assertions["overworld.speech_bubble_count"] = len(ow.speech_bubbles)

    if perc.chatroom is not None:
        cr = perc.chatroom
        if cr.occupant_colors:
            assertions["chatroom.occupant_count"] = len(cr.occupant_colors)
        if cr.bottom_bar is not None:
            assertions["chatroom.bottom_bar"] = {"not_none": True}
        if cr.messages:
            assertions["chatroom.message_count"] = {"gte": len(cr.messages)}
        if cr.has_pending_entry:
            assertions["chatroom.has_pending_entry"] = True
        if cr.pending_role_offer:
            assertions["chatroom.pending_role_offer"] = True
        if cr.pending_color_offer:
            assertions["chatroom.pending_color_offer"] = True
        if cr.menu_category is not None:
            assertions["chatroom.menu_category"] = cr.menu_category
        if cr.target_mode is not None:
            assertions["chatroom.target_mode"] = cr.target_mode

    if perc.global_chat is not None:
        gc = perc.global_chat
        if gc.room_name is not None:
            assertions["global_chat.room_name"] = gc.room_name
        if gc.messages:
            assertions["global_chat.message_count"] = {"gte": len(gc.messages)}
        if gc.usurp_candidate is not None:
            assertions["global_chat.usurp_candidate"] = {"not_none": True}

    if perc.info_screen is not None:
        info = perc.info_screen
        if info.mode is not None:
            assertions["info_screen.mode"] = info.mode.value
        if info.known_players:
            assertions["info_screen.known_player_count"] = len(info.known_players)
        if info.role_name is not None:
            assertions["info_screen.role_name"] = info.role_name
        if info.team_name is not None:
            assertions["info_screen.team_name"] = info.team_name

    if perc.role_reveal is not None:
        rr = perc.role_reveal
        if rr.team is not None:
            assertions["role_reveal.team"] = rr.team
        if rr.team_color is not None:
            assertions["role_reveal.team_color"] = int(rr.team_color)
        if rr.role is not None:
            assertions["role_reveal.role"] = rr.role
        if rr.room is not None:
            assertions["role_reveal.room"] = rr.room
        if rr.player_count is not None:
            assertions["role_reveal.player_count"] = rr.player_count
        if rr.room_size is not None:
            assertions["role_reveal.room_size"] = rr.room_size

    if perc.exchange is not None:
        ex = perc.exchange
        if ex.leaders:
            assertions["exchange.leader_count"] = len(ex.leaders)
        if ex.departing:
            assertions["exchange.departing_count"] = len(ex.departing)
        if ex.arriving:
            assertions["exchange.arriving_count"] = len(ex.arriving)
        if ex.viewer_status is not None:
            assertions["exchange.viewer_status"] = ex.viewer_status

    if perc.result is not None:
        res = perc.result
        assertions["result.is_reveal"] = res.is_reveal
        if res.winner is not None:
            assertions["result.winner"] = res.winner
        if res.winner_color is not None:
            assertions["result.winner_color"] = int(res.winner_color)

    if perc.lobby is not None:
        lb = perc.lobby
        if lb.player_count is not None:
            assertions["lobby.player_count"] = lb.player_count
        if lb.max_players is not None:
            assertions["lobby.max_players"] = lb.max_players
        if lb.countdown_secs is not None:
            assertions["lobby.countdown_secs"] = {"not_none": True}

    return assertions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a single frame from a capture as a test fixture.",
    )
    parser.add_argument(
        "--input", "-i", required=True, type=Path,
        help="Path to the .npy capture file",
    )
    parser.add_argument(
        "--tick", "-t", required=True, type=int,
        help="Tick/frame index to extract (0-based)",
    )
    parser.add_argument(
        "--name", "-n", required=True,
        help="Fixture name (e.g., 'role_reveal_shades')",
    )
    parser.add_argument(
        "--view", default=None,
        help="Override the detected view label (e.g., 'lobby' when detector is wrong)",
    )
    parser.add_argument(
        "--note", default=None,
        help="Human-readable note about what this fixture tests",
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=_FIXTURES_DIR,
        help=f"Fixture output directory (default: {_FIXTURES_DIR})",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Record the seed used for this capture (for provenance)",
    )

    args = parser.parse_args()

    # Load capture
    if not args.input.is_file():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    frames = np.load(args.input)
    if args.tick < 0 or args.tick >= len(frames):
        print(
            f"Error: tick {args.tick} out of range (0-{len(frames)-1})",
            file=sys.stderr,
        )
        return 1

    frame = frames[args.tick]

    # Run parse_frame
    perc = parse_frame(frame)
    detected_view = perc.view.value
    actual_view = args.view if args.view else detected_view

    # Build assertions from parse output
    assertions = perception_to_assertions(perc)

    # Build fixture JSON
    fixture_json = {
        "view": actual_view,
        "source": {
            "tick": args.tick,
            "date": str(date.today()),
        },
        "assertions": assertions,
    }
    if args.seed is not None:
        fixture_json["source"]["seed"] = args.seed
    if args.note:
        fixture_json["note"] = args.note
    if actual_view != detected_view:
        fixture_json["_detected_view"] = detected_view
        fixture_json["_detection_override"] = True

    # Write files
    args.fixtures_dir.mkdir(parents=True, exist_ok=True)

    npy_path = args.fixtures_dir / f"{args.name}.npy"
    json_path = args.fixtures_dir / f"{args.name}.json"

    np.save(npy_path, frame)

    with open(json_path, "w") as f:
        json.dump(fixture_json, f, indent=2)
        f.write("\n")

    # Report
    print(f"Extracted fixture '{args.name}' from tick {args.tick}")
    print(f"  Detected view: {detected_view}")
    if actual_view != detected_view:
        print(f"  Override view:  {actual_view}")
    print(f"  Assertions:    {len(assertions)} field(s)")
    print(f"  Frame:         {npy_path}")
    print(f"  Expected:      {json_path}")
    if assertions:
        print()
        print("  Draft assertions (review before committing):")
        for path, spec in assertions.items():
            print(f"    {path}: {spec}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
