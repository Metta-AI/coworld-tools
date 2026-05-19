from __future__ import annotations

from players_lib.eval.cogsguard.eval_result_metrics import extract_cogsguard_eval_metrics, parse_eval_result_text


def _modern_result() -> dict:
    return {
        "missions": [
            {
                "mission_name": "cogsguard_machina_1.basic",
                "mission_summary": {
                    "episodes": 2,
                    "policy_summaries": [
                        {
                            "agent_count": 8,
                            "avg_agent_metrics": {
                                "heart.gained": 2.0,
                                "heart.lost": 1.0,
                            },
                            "action_timeouts": 3,
                        }
                    ],
                    "avg_game_stats": {
                        "cogs/aligned.junction.held": 150.0,
                        "cogs/aligned.junction.gained": 4.0,
                    },
                    "per_episode_per_policy_avg_rewards": {
                        "0": [1.0],
                        "1": [3.0],
                    },
                },
            }
        ]
    }


def test_extract_cogsguard_eval_metrics_modern_schema() -> None:
    metrics = extract_cogsguard_eval_metrics(_modern_result())

    assert metrics == {
        "aligned.junction.held": 150.0,
        "aligned.junction.gained": 4.0,
        "heart.gained": 2.0,
        "heart.lost": 1.0,
        "reward": 2.0,
        "action_timeouts": 3.0,
    }


def test_extract_cogsguard_eval_metrics_uses_current_cogs_junction_keys() -> None:
    result = {
        "missions": [
            {
                "mission_summary": {
                    "policy_summaries": [
                        {
                            "avg_agent_metrics": {
                                "heart.gained": 5.0,
                                "heart.lost": 2.0,
                                "reward": 7.0,
                            },
                            "action_timeouts": 0,
                        }
                    ],
                    "avg_game_stats": {
                        "junction.held": 12.0,
                        "junction.gained": 3.0,
                    },
                    "per_episode_per_policy_avg_rewards": {},
                }
            }
        ]
    }

    metrics = extract_cogsguard_eval_metrics(result)

    assert metrics["aligned.junction.held"] == 0.0
    assert metrics["aligned.junction.gained"] == 0.0
    assert metrics["reward"] == 7.0


def test_parse_eval_result_text_handles_scrimmage_preamble() -> None:
    raw = 'Preparing evaluation for 1 policies across 1 mission(s)\nSimulating (machina_1)\n{"missions": []}\n'

    parsed = parse_eval_result_text(raw)

    assert parsed == {"missions": []}


def test_extract_cogsguard_eval_metrics_defaults_missing_junction_stats_to_zero() -> None:
    result = {
        "missions": [
            {
                "mission_summary": {
                    "policy_summaries": [
                        {
                            "avg_agent_metrics": {},
                            "action_timeouts": 0,
                        }
                    ],
                    "avg_game_stats": {
                        "cogs/heart.withdrawn": 2.0,
                    },
                    "per_episode_per_policy_avg_rewards": {"0": [0.5]},
                }
            }
        ]
    }

    metrics = extract_cogsguard_eval_metrics(result)

    assert metrics["aligned.junction.held"] == 0.0
    assert metrics["aligned.junction.gained"] == 0.0
