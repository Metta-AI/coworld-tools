from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from graders.among_them.among_them_grader import among_them_grader


def write_episode_bundle(path: Path, results: dict[str, object], results_path: str = "artifacts/results.json") -> None:
    manifest = {
        "ereq_id": "ereq_test",
        "status": "success",
        "include": ["results"],
        "files": {"results": results_path},
    }
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr(results_path, json.dumps(results))


class AmongThemGraderTest(unittest.TestCase):
    def test_interestingness_scores_expected_signals(self) -> None:
        results = {
            "scores": [1.0, -1.0, 0.25],
            "win": [True, False, False],
            "tasks": [4, 2, 0],
            "kills": [1, 0, 0],
        }

        self.assertEqual(among_them_grader.interestingness(results), 0.9625)

    def test_main_reads_bundle_and_writes_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / "episode.zip"
            grade_path = temp_path / "grade.json"
            write_episode_bundle(
                bundle_path,
                {
                    "scores": [1.0, 0.0],
                    "win": [True, False],
                    "tasks": [8, 0],
                    "kills": [0, 1],
                },
            )

            with mock.patch.dict(
                os.environ,
                {
                    "COGAME_EPISODE_BUNDLE_URI": str(bundle_path),
                    "COGAME_GRADE_URI": str(grade_path),
                },
                clear=False,
            ):
                among_them_grader.main()

            self.assertEqual(
                json.loads(grade_path.read_text(encoding="utf-8")),
                {"grader_id": "among-them-grader", "score": 0.8},
            )

    def test_write_uri_supports_file_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested dir" / "grade file.json"

            among_them_grader.write_uri(output_path.as_uri(), {"grader_id": "test", "score": 1.0})

            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                {"grader_id": "test", "score": 1.0},
            )


if __name__ == "__main__":
    unittest.main()
