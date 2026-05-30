from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    output_path = Path(sys.argv[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results = {"scores": [0.0, 0.0], "steps": 1, "mission": "machina_1"}
    replay = {
        "version": 4,
        "action_names": ["noop"],
        "item_names": [],
        "type_names": ["agent"],
        "map_size": [3, 3],
        "num_agents": 2,
        "max_steps": 1,
        "objects": [
            {
                "id": 1,
                "alive": True,
                "type_name": "agent",
                "agent_id": 0,
                "location": [1, 1],
                "action_id": 0,
                "action_param": 0,
                "action_success": True,
                "current_reward": 0.0,
                "total_reward": 0.0,
                "inventory": [],
                "policy_infos": {"policy_name": "alpha"},
            },
            {
                "id": 2,
                "alive": True,
                "type_name": "agent",
                "agent_id": 1,
                "location": [2, 1],
                "action_id": 0,
                "action_param": 0,
                "action_success": True,
                "current_reward": 0.0,
                "total_reward": 0.0,
                "inventory": [],
                "policy_infos": {"policy_name": "beta"},
            },
        ],
        "infos": {},
    }
    manifest = {
        "ereq_id": "ereq_smoke",
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
