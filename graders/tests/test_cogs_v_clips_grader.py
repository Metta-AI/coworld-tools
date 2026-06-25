from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from graders.cogs_v_clips.cogs_v_clips_grader import cogs_v_clips_grader

ITEM_NAMES = [
    "oxygen",
    "carbon",
    "germanium",
    "silicon",
    "hp",
    "heart",
    "energy",
    "aligner",
    "scrambler",
    "miner",
    "scout",
]


def write_episode_bundle(
    path: Path,
    results: dict[str, object],
    replay: dict[str, object],
    results_path: str = "artifacts/results.json",
    replay_path: str = "artifacts/replay.json",
) -> None:
    manifest = {
        "ereq_id": "ereq_test",
        "status": "success",
        "include": ["results", "replay"],
        "files": {"results": results_path, "replay": replay_path},
    }
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr(results_path, json.dumps(results))
        bundle.writestr(replay_path, json.dumps(replay))


def flat_replay() -> dict[str, object]:
    return {
        "version": 4,
        "item_names": ITEM_NAMES,
        "tags": {"type:junction": 13},
        "objects": [
            {
                "id": 1,
                "is_agent": True,
                "agent_id": 0,
                "alive": True,
                "inventory": [[4, 100], [5, 0]],
                "total_reward": 0.0,
            },
            {
                "id": 2,
                "is_agent": True,
                "agent_id": 1,
                "alive": True,
                "inventory": [[4, 100], [5, 0]],
                "total_reward": 0.0,
            },
            {"id": 3, "type_name": "junction", "tag_ids": [13], "color": 0},
        ],
        "infos": {"episode_rewards": [0.0, 0.0]},
    }


def active_replay() -> dict[str, object]:
    return {
        "version": 4,
        "item_names": ITEM_NAMES,
        "tags": {"type:junction": 13},
        "objects": [
            {
                "id": 1,
                "is_agent": True,
                "agent_id": 0,
                "alive": True,
                "inventory": [
                    [0, [[4, 100], [5, 0]]],
                    [2, [[0, 1], [1, 3], [4, 80], [5, 1], [7, 1]]],
                ],
                "total_reward": 5.0,
                "vibe": [[0, 0], [2, 7]],
            },
            {
                "id": 2,
                "is_agent": True,
                "agent_id": 1,
                "alive": [[0, True], [3, False]],
                "inventory": [[0, [[4, 100]]], [3, [[4, 0]]]],
                "total_reward": 1.0,
            },
            {"id": 3, "type_name": "junction", "tag_ids": [13], "color": [[0, 0], [2, 1]]},
            {"id": 4, "type_name": "junction", "tag_ids": [13], "color": 0},
        ],
        "infos": {"episode_rewards": [5.0, 1.0]},
    }


class CogsVsClipsGraderTest(unittest.TestCase):
    def test_history_helpers_handle_scalars_and_histories(self) -> None:
        self.assertEqual(cogs_v_clips_grader.all_values(3), [3])
        self.assertEqual(cogs_v_clips_grader.all_values([[0, "a"], [2, "b"]]), ["a", "b"])
        self.assertEqual(cogs_v_clips_grader.first_value([[0, "a"], [2, "b"]]), "a")
        self.assertEqual(cogs_v_clips_grader.last_value([[0, "a"], [2, "b"]]), "b")

    def test_inventory_values_do_not_treat_item_pairs_as_history(self) -> None:
        inventory = [[0, 2], [1, 3]]

        self.assertEqual(cogs_v_clips_grader.inventory_values(inventory), [inventory])
        self.assertEqual(
            cogs_v_clips_grader.inventory_amounts(inventory, ITEM_NAMES),
            {"oxygen": 2.0, "carbon": 3.0},
        )

    def test_interestingness_returns_zero_for_flat_replay(self) -> None:
        self.assertEqual(
            cogs_v_clips_grader.cogs_v_clips_interestingness({"scores": [0.0, 0.0]}, flat_replay()),
            0.0,
        )

    def test_interestingness_combines_score_inventory_survival_and_junction_activity(self) -> None:
        self.assertEqual(
            cogs_v_clips_grader.cogs_v_clips_interestingness({"scores": [4.0, 1.0]}, active_replay()),
            0.855,
        )

    def test_missing_item_names_zeroes_inventory_and_role_signals(self) -> None:
        replay = active_replay()
        replay.pop("item_names")
        replay["objects"] = [
            {"id": 1, "is_agent": True, "agent_id": 0, "alive": True, "inventory": [[0, 3]], "total_reward": 0.0},
            {"id": 2, "is_agent": True, "agent_id": 1, "alive": True, "inventory": [[0, 0]], "total_reward": 0.0},
        ]
        replay["infos"] = {"episode_rewards": [0.0, 0.0]}

        self.assertEqual(cogs_v_clips_grader.cogs_v_clips_interestingness({"scores": [0.0, 0.0]}, replay), 0.0)

    def test_missing_objects_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "objects list"):
            cogs_v_clips_grader.cogs_v_clips_interestingness({"scores": [0.0, 0.0]}, {"item_names": ITEM_NAMES})

    def test_main_reads_bundle_and_writes_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / "episode.zip"
            grade_path = temp_path / "grade.json"
            write_episode_bundle(bundle_path, {"scores": [4.0, 1.0]}, active_replay())

            with mock.patch.dict(
                os.environ,
                {
                    "COGAME_EPISODE_BUNDLE_URI": str(bundle_path),
                    "COGAME_GRADE_URI": str(grade_path),
                },
                clear=False,
            ):
                cogs_v_clips_grader.main()

            self.assertEqual(
                json.loads(grade_path.read_text(encoding="utf-8")),
                {"grader_id": "cogs-v-clips-grader", "score": 0.855},
            )


if __name__ == "__main__":
    unittest.main()
