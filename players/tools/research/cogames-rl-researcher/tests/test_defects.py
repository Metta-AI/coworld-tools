from __future__ import annotations

import json
from pathlib import Path

from cogames_rl_researcher.defects import (
    build_defect_backlog,
    build_defect_fix_plan,
    set_defect_status,
    submit_crash_defect,
    validate_defect_fix,
)


def test_submit_crash_defect_persists_and_builds_backlog(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"

    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="claude",
        command="cogames upload --name p --policy metta://policy/role_py --season beta-cogsguard",
        observed_error="authentication failed: token expired",
        context="startup upload stage",
        season="beta-cogsguard",
        policy_name="p",
    )

    assert defect.status == "open"
    assert defect.likely_owner == "auth"
    assert (store_dir / "crash_defects.jsonl").exists()
    assert (store_dir / "defect_backlog.json").exists()

    backlog = build_defect_backlog(store_dir)
    assert backlog.total_defects == 1
    assert backlog.open_defects == 1


def test_set_defect_status_updates_existing_record(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"

    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames scrimmage --mission arena",
        observed_error="failed: timeout in rollout",
    )

    updated = set_defect_status(store_dir=store_dir, defect_id=defect.defect_id, status="fixed")

    assert updated.status == "fixed"
    backlog = build_defect_backlog(store_dir)
    assert backlog.status_counts["fixed"] == 1


def test_build_defect_fix_plan_includes_triaged_defects(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"
    open_defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="claude",
        command="cogames upload --name p --policy metta://policy/role_py --season beta-cogsguard",
        observed_error="authentication failed: token expired",
    )
    triaged_defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames submit p --season beta-cogsguard",
        observed_error="failed: submit timed out",
    )
    set_defect_status(store_dir=store_dir, defect_id=triaged_defect.defect_id, status="triaged")

    plan = build_defect_fix_plan(store_dir, max_items=3)

    assert plan.open_defects == 1
    assert len(plan.items) == 2
    assert plan.items[0].priority == 1
    assert {item.defect_id for item in plan.items} == {open_defect.defect_id, triaged_defect.defect_id}
    assert (store_dir / "defect_fix_plan.json").exists()


def test_validate_defect_fix_marks_defect_fixed_on_success(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"
    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames submit test-policy --season beta-cogsguard",
        observed_error="failed: submit timed out",
    )

    attempt = validate_defect_fix(
        store_dir=store_dir,
        defect_id=defect.defect_id,
        fix_command="true",
        timeout_seconds=5,
        mark_fixed_on_success=True,
    )

    assert attempt.status == "success"
    assert attempt.return_code == 0
    assert (store_dir / "fix_attempts.jsonl").exists()
    backlog = build_defect_backlog(store_dir)
    assert backlog.status_counts["fixed"] == 1


def test_validate_defect_fix_success_does_not_close_without_opt_in(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"
    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames submit test-policy --season beta-cogsguard",
        observed_error="failed: submit timed out",
    )

    attempt = validate_defect_fix(
        store_dir=store_dir,
        defect_id=defect.defect_id,
        fix_command="true",
        timeout_seconds=5,
    )

    assert attempt.status == "success"
    backlog = build_defect_backlog(store_dir)
    assert backlog.open_defects == 1


def test_validate_defect_fix_records_failure_without_closing_defect(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"
    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames submit test-policy --season beta-cogsguard",
        observed_error="failed: submit timed out",
    )

    attempt = validate_defect_fix(
        store_dir=store_dir,
        defect_id=defect.defect_id,
        fix_command="false",
        timeout_seconds=5,
    )

    assert attempt.status == "failed"
    lines = (store_dir / "fix_attempts.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    assert payload["defect_id"] == defect.defect_id
    backlog = build_defect_backlog(store_dir)
    assert backlog.open_defects == 1


def test_validate_defect_fix_records_missing_command_failure(tmp_path: Path) -> None:
    store_dir = tmp_path / "defects"
    defect = submit_crash_defect(
        store_dir=store_dir,
        reporter="codex",
        command="cogames submit test-policy --season beta-cogsguard",
        observed_error="failed: submit timed out",
    )

    attempt = validate_defect_fix(
        store_dir=store_dir,
        defect_id=defect.defect_id,
        fix_command="definitely-not-a-real-executable-xyz",
        timeout_seconds=5,
    )

    assert attempt.status == "failed"
    assert attempt.return_code == 127
    lines = (store_dir / "fix_attempts.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    assert payload["defect_id"] == defect.defect_id
    assert payload["status"] == "failed"
    backlog = build_defect_backlog(store_dir)
    assert backlog.open_defects == 1
