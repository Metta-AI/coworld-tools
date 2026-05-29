from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from graders.bitworld_score.bitworld_score_grader import bitworld_score_grader
from graders.crewrift.crewrift_grader import crewrift_grader
from graders.liarliar.liarliar_grader import liarliar_grader
from graders.mettagrid.mettagrid_score_grader import mettagrid_score_grader
from graders.persephones_escape.persephones_escape_grader import persephones_escape_grader
from graders.tribal_cog.tribal_cog_grader import tribal_cog_grader


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


class NewGradersTest(unittest.TestCase):
    def test_bitworld_score_interestingness_uses_score_and_activity_signals(self) -> None:
        results = {
            "scores": [120, 80, 10],
            "distance_walked": [300, 50, 0],
            "win": [True, False, False],
            "stats": {"catches": [3, 0, 1]},
        }

        self.assertEqual(bitworld_score_grader.interestingness(results), 0.8)

    def test_crewrift_interestingness_uses_social_deduction_signals(self) -> None:
        results = {
            "scores": [1, -1, 0],
            "win": [True, False, False],
            "tasks": [8, 4, 0],
            "kills": [2, 0, 0],
            "vote_players": [2, 1, 0],
            "vote_skip": [0, 1, 0],
            "vote_timeout": [0, 0, 0],
        }

        self.assertEqual(crewrift_grader.interestingness(results), 0.8083)

    def test_mettagrid_score_interestingness_scores_simple_results(self) -> None:
        self.assertEqual(
            mettagrid_score_grader.interestingness({"scores": [25, 5, 0], "steps": 250}),
            0.705,
        )

    def test_liarliar_interestingness_scores_module_outcomes(self) -> None:
        results = {
            "scores": [40, 20, -5, 0, 10, 15],
            "survived": [True, True, False, True, False, True],
            "detonated": [False, False, True, False, True, False],
            "modules_solved": [2, 1, 0, 1, 0, 1],
            "modules_failed": [0, 0, 2, 0, 1, 0],
            "hint_recoveries": [1, 0, 0, 2, 0, 0],
            "duration_seconds": 180,
        }

        self.assertEqual(liarliar_grader.interestingness(results), 0.6112)

    def test_persephones_escape_interestingness_rewards_decisive_games(self) -> None:
        results = {"scores": [1, 1, 0, 0], "winner": "Shades", "players": [{}, {}, {}, {}], "ticks": 240}

        self.assertEqual(persephones_escape_grader.interestingness(results), 0.9033)

    def test_tribal_cog_interestingness_scores_team_outcomes(self) -> None:
        results = {
            "team_scores": [100, 75, 50, 25],
            "winner_team": 0,
            "steps": 800,
            "truncation_reason": "victory_condition_met",
        }

        self.assertEqual(tribal_cog_grader.interestingness(results), 0.7325)

    def test_one_new_grader_main_reads_bundle_and_writes_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / "episode.zip"
            grade_path = temp_path / "grade.json"
            write_episode_bundle(bundle_path, {"scores": [25, 5, 0], "steps": 250})

            with mock.patch.dict(
                os.environ,
                {
                    "COGAME_EPISODE_BUNDLE_URI": str(bundle_path),
                    "COGAME_GRADE_URI": str(grade_path),
                },
                clear=False,
            ):
                mettagrid_score_grader.main()

            self.assertEqual(
                json.loads(grade_path.read_text(encoding="utf-8")),
                {"grader_id": "mettagrid-score-grader", "score": 0.705},
            )


if __name__ == "__main__":
    unittest.main()
