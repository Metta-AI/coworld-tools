#!/usr/bin/env python3
"""Regenerate the loose smoke fixtures (`smoke/fixtures/`) from the
test fixture helpers.

Run once and commit the outputs; the generated files are
`results.json`, `replay.bitreplay`, and `metadata.json`. Re-run this
script whenever the fixture helpers in `tests/fixtures.py` evolve and
the smoke fixtures need to track them.

The binary replay this produces is synthetic but well-formed: 8 joins
at `time_ms=0`, then a single hash record at `last_tick=1200`. That
exercises the join/leave/last_tick wiring and produces a deterministic
4-entry output zip. A richer real `.bitreplay` capture from a
`nottoodumb`-vs-`nottoodumb` game would expand the activity strip
and stats, but isn't needed for the container-level integration check
the smoke is here to do — the pytest suite covers the rich code paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
REPORTER_DIR = HERE.parent
sys.path.insert(0, str(REPORTER_DIR / "tests"))

import fixtures as fx  # noqa: E402 -- import after sys.path mutation


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    results = fx.make_results_crewmate_win()
    metadata = fx.make_metadata()
    replay = fx.make_typical_replay_bytes(slots=8, last_tick=1200)

    (FIXTURES / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (FIXTURES / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (FIXTURES / "replay.bitreplay").write_bytes(replay)

    print(f"wrote results.json   ({(FIXTURES / 'results.json').stat().st_size} bytes)")
    print(f"wrote metadata.json  ({(FIXTURES / 'metadata.json').stat().st_size} bytes)")
    print(f"wrote replay.bitreplay ({(FIXTURES / 'replay.bitreplay').stat().st_size} bytes)")


if __name__ == "__main__":
    main()
