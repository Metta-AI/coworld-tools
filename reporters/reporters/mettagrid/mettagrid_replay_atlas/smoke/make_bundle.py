"""Write a synthetic multi-tick episode bundle for the atlas smoke test.

Two agents walk a small 12x8 MettaScope world for 60 steps (delta-encoded
locations), one earns reward twice, one dies — enough motion that the
occupancy heatmap and the timeline are non-degenerate.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path


def _walk(start: tuple[int, int], steps: int, dx: int, dy: int, period: int) -> list:
    x, y = start
    out = [[0, [x, y]]]
    for t in range(1, steps + 1):
        if t % period == 0:
            x = (x + dx) % 12
            y = (y + dy) % 8
            out.append([t, [x, y]])
    return out


def main() -> None:
    output_path = Path(sys.argv[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    steps = 60
    results = {"scores": [3.0, 1.0], "steps": steps, "mission": "atlas_smoke"}
    replay = {
        "version": 4,
        "action_names": ["noop", "move"],
        "item_names": [],
        "type_names": ["agent", "wall"],
        "map_size": [12, 8],
        "num_agents": 2,
        "max_steps": steps,
        "objects": [
            {
                "id": 1,
                "type_name": "agent",
                "agent_id": 0,
                "location": _walk((1, 1), steps, 1, 0, 2),
                "total_reward": [[0, 0.0], [20, 1.0], [45, 3.0]],
                "alive": True,
                "policy_infos": {"policy_name": "alpha"},
            },
            {
                "id": 2,
                "type_name": "agent",
                "agent_id": 1,
                "location": _walk((10, 6), steps, 0, 1, 3),
                "total_reward": [[0, 0.0], [30, 1.0]],
                "alive": [[0, True], [40, False]],
                "policy_infos": {"policy_name": "beta"},
            },
            {"id": 3, "type_name": "wall", "location": [5, 5]},
        ],
        "infos": {},
    }
    manifest = {
        "ereq_id": "ereq_atlas_smoke",
        "status": "success",
        "include": ["results", "replay"],
        "files": {"results": "results.json", "replay": "replay.json"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results))
        zf.writestr("replay.json", json.dumps(replay))
    output_path.write_bytes(buf.getvalue())


if __name__ == "__main__":
    main()
