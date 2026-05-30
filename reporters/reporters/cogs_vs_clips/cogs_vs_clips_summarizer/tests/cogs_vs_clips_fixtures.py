"""Synthetic Cogs vs Clips episode-bundle fixtures."""

from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy
from typing import Any


def make_results() -> dict[str, Any]:
    return {
        "scores": [1.5, 0.25],
        "steps": 4,
        "mission": "machina_1",
    }


def make_metadata() -> dict[str, Any]:
    return {
        "episode_id": "ep_cvc_001",
        "variant_id": "machina_1",
        "duration_seconds": 12.5,
        "players": [
            {"slot": 0, "policy_name": "alpha:v1"},
            {"slot": 1, "policy_name": "beta:v2"},
        ],
    }


def make_replay() -> dict[str, Any]:
    return deepcopy(
        {
            "version": 4,
            "action_names": [
                "noop",
                "move_north",
                "move_south",
                "move_west",
                "move_east",
            ],
            "item_names": ["ore", "gear", "heart", "scrambler"],
            "type_names": ["wall", "agent"],
            "map_size": [9, 7],
            "num_agents": 2,
            "max_steps": 4,
            "objects": [
                {
                    "id": 10,
                    "alive": True,
                    "type_name": "agent",
                    "agent_id": 0,
                    "location": [[0, [1, 1]], [1, [2, 1]], [3, [2, 2]]],
                    "action_id": [[0, 0], [1, 4], [3, 2]],
                    "action_param": 0,
                    "action_success": True,
                    "current_reward": [[0, 0.0], [3, 1.5]],
                    "total_reward": [[0, 0.0], [3, 1.5]],
                    "inventory": [[0, [[0, 3]]], [2, [[0, 1], [2, 1]]]],
                    "policy_infos": [[0, {"policy_name": "alpha:v1"}]],
                },
                {
                    "id": 11,
                    "alive": True,
                    "type_name": "agent",
                    "agent_id": 1,
                    "location": [6, 5],
                    "action_id": 0,
                    "action_param": 0,
                    "action_success": True,
                    "current_reward": 0.25,
                    "total_reward": 0.25,
                    "inventory": [[1, 2]],
                    "policy_infos": {"policy_name": "beta:v2"},
                },
                {
                    "id": 99,
                    "alive": True,
                    "type_name": "wall",
                    "location": [0, 0],
                },
            ],
            "infos": {
                "game": {"clips/aligned.junction.held": 2.0},
                "agent": {"action.noop.success": 1.5},
                "attributes": {"steps": 4},
                "episode_rewards": [1.5, 0.25],
            },
        }
    )


def make_bundle_zip(
    *,
    ereq_id: str = "ereq_cvc_001",
    status: str = "success",
    include_metadata: bool = True,
) -> bytes:
    include = ["results", "replay"]
    files = {"results": "results.json", "replay": "replay.json"}
    entries = [
        ("results.json", json.dumps(make_results()).encode("utf-8")),
        ("replay.json", json.dumps(make_replay()).encode("utf-8")),
    ]
    if include_metadata:
        include.append("metadata")
        files["metadata"] = "metadata.json"
        entries.append(("metadata.json", json.dumps(make_metadata()).encode("utf-8")))

    manifest = {
        "ereq_id": ereq_id,
        "status": status,
        "include": include,
        "files": files,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, payload in entries:
            zf.writestr(name, payload)
    return buf.getvalue()
