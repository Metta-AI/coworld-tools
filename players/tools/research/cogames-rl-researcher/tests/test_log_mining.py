from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.log_mining import LogMiningConfig, mine_cogames_failures, run_log_mining_service


def test_mine_cogames_failures_extracts_agent_failures(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    (logs_dir / "claude-run.log").write_text(
        "claude run: cogames scrimmage --mission arena\nERROR authentication failed: token expired\n",
        encoding="utf-8",
    )
    (logs_dir / "codex-run.log").write_text(
        "codex run: cogames upload --name test-policy --season beta-cogsguard\n"
        "failed: timeout reached while uploading\n",
        encoding="utf-8",
    )

    report = mine_cogames_failures(
        log_roots=[logs_dir],
        agents=["gastown", "claude", "codex"],
        max_failures=20,
    )

    assert report.files_scanned == 2
    assert report.total_failures == 2
    assert report.failures_by_agent["claude"] == 1
    assert report.failures_by_agent["codex"] == 1
    assert any(item.category == "setup/auth" for item in report.failures)


def test_log_mining_service_writes_json_and_markdown(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    (logs_dir / "gastown.log").write_text(
        "gastown: cogames submit test-policy --season beta-cogsguard\nerror: submit failed due to server issue\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "report.json"
    report = run_log_mining_service(
        LogMiningConfig(
            log_roots=[logs_dir],
            output_path=output_path,
            agents=["gastown", "claude", "codex"],
            max_failures=10,
            iterations=1,
            poll_interval_seconds=1,
        )
    )

    assert report.total_failures == 1
    assert output_path.exists()
    assert output_path.with_suffix(".md").exists()
