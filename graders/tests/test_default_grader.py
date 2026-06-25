from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from graders.default.default_grader import default_grader


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


class DefaultGraderTest(unittest.TestCase):
    def test_default_interestingness_scores_normalized_score_spread(self) -> None:
        self.assertEqual(default_grader.default_interestingness({"scores": [100, 70, 90]}), 0.3)

    def test_default_interestingness_clamps_large_signed_spread(self) -> None:
        self.assertEqual(default_grader.default_interestingness({"scores": [1, -1]}), 1.0)

    def test_default_interestingness_returns_zero_without_usable_scores(self) -> None:
        self.assertEqual(default_grader.default_interestingness({}), 0.0)
        self.assertEqual(default_grader.default_interestingness({"scores": ["winner", False]}), 0.0)
        self.assertEqual(default_grader.default_interestingness({"scores": [3]}), 0.0)

    def test_main_reads_bundle_and_writes_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / "episode.zip"
            grade_path = temp_path / "grade.json"
            write_episode_bundle(bundle_path, {"scores": [10, 7, 9]})

            with mock.patch.dict(
                os.environ,
                {
                    "COGAME_EPISODE_BUNDLE_URI": str(bundle_path),
                    "COGAME_GRADE_URI": str(grade_path),
                },
                clear=False,
            ):
                default_grader.main()

            self.assertEqual(
                json.loads(grade_path.read_text(encoding="utf-8")),
                {"grader_id": "default-grader", "score": 0.3},
            )

    def test_write_uri_supports_file_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested dir" / "grade file.json"

            default_grader.write_uri(output_path.as_uri(), {"grader_id": "test", "score": 1.0})

            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                {"grader_id": "test", "score": 1.0},
            )


if __name__ == "__main__":
    unittest.main()
