from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from graders.paint_arena.paint_arena_grader import paint_arena_grader


def write_episode_bundle(
    path: Path,
    results: dict[str, object],
    replay: dict[str, object] | str,
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
        if isinstance(replay, str):
            bundle.writestr(replay_path, replay)
        else:
            bundle.writestr(replay_path, json.dumps(replay))


class PaintArenaGraderTest(unittest.TestCase):
    def test_interestingness_normalizes_final_score_margin_by_board_area(self) -> None:
        results = {"scores": [80, 20, 10]}
        replay = {"config": {"width": 10, "height": 10}}

        self.assertEqual(paint_arena_grader.paintarena_interestingness(results, replay), 0.6)

    def test_interestingness_returns_zero_for_tie(self) -> None:
        results = {"scores": [25, 25, 10]}
        replay = {"config": {"width": 10, "height": 10}}

        self.assertEqual(paint_arena_grader.paintarena_interestingness(results, replay), 0.0)

    def test_interestingness_returns_zero_for_single_player(self) -> None:
        results = {"scores": [25]}
        replay = {"config": {"width": 10, "height": 10}}

        self.assertEqual(paint_arena_grader.paintarena_interestingness(results, replay), 0.0)

    def test_interestingness_clamps_oversized_margin(self) -> None:
        results = {"scores": [200, 0]}
        replay = {"config": {"width": 10, "height": 10}}

        self.assertEqual(paint_arena_grader.paintarena_interestingness(results, replay), 1.0)

    def test_missing_replay_config_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "config.width and config.height"):
            paint_arena_grader.paintarena_interestingness({"scores": [2, 1]}, {})

    def test_main_reads_bundle_and_writes_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / "episode.zip"
            grade_path = temp_path / "grade.json"
            write_episode_bundle(
                bundle_path,
                {"scores": [80, 20, 10]},
                {"config": {"width": 10, "height": 10}},
            )

            with mock.patch.dict(
                os.environ,
                {
                    "COGAME_EPISODE_BUNDLE_URI": str(bundle_path),
                    "COGAME_GRADE_URI": str(grade_path),
                },
                clear=False,
            ):
                paint_arena_grader.main()

            self.assertEqual(
                json.loads(grade_path.read_text(encoding="utf-8")),
                {"grader_id": "paint-arena-grader", "score": 0.6},
            )

    def test_malformed_replay_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_path = Path(temp_dir) / "episode.zip"
            write_episode_bundle(bundle_path, {"scores": [2, 1]}, "{not json")

            with self.assertRaises(json.JSONDecodeError):
                paint_arena_grader.load_bundle_artifacts(bundle_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
