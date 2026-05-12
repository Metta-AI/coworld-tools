"""Tests for the scenario harness.

Orchestration tests stub `_drive_rollout` so no real mettagrid env
is built. A separate scenario-marked test (tests/scenarios/) drives
a real episode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cvc_policy.scenarios import Scenario
from cvc_policy.scenarios.assertions import AssertResult
from cvc_policy.scenarios.harness import resolve_mission, run_scenario


def _stub_drive(**kwargs: Any) -> int:
    run_dir: Path = kwargs["run_dir"]
    spec = kwargs["spec"]
    record_dir = Path(spec.init_kwargs["record_dir"])
    assert record_dir == run_dir
    (run_dir / "events.json").write_text(
        json.dumps(
            [
                {
                    "step": 0,
                    "agent": 0,
                    "stream": "py",
                    "type": "action",
                    "payload": {"role": "miner"},
                }
            ]
        )
    )
    return 3


def test_resolve_mission_machina_1() -> None:
    m = resolve_mission("machina_1", cogs=2)
    assert m.num_agents == 2


def test_resolve_mission_tutorial_variant() -> None:
    m = resolve_mission("tutorial.miner")
    assert "miner" in m._base_variants


def test_resolve_mission_unknown_raises() -> None:
    with pytest.raises(KeyError):
        resolve_mission("does_not_exist")


def test_resolve_mission_unknown_lists_valid_names() -> None:
    """The error should list known missions so typos self-diagnose."""
    with pytest.raises(KeyError) as excinfo:
        resolve_mission("no_such")
    msg = str(excinfo.value)
    assert "no_such" in msg
    # All known names should appear in the message.
    for name in ("machina_1", "tutorial.miner", "tutorial.aligner"):
        assert name in msg


def test_run_scenario_writes_run_folder(tmp_path: Path) -> None:
    s = Scenario(
        name="my_test", tier=0, mission="machina_1", cogs=2, steps=3,
        assertions=[lambda run: AssertResult(name="dummy", passed=True)],
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_stub_drive):
        run = run_scenario(s, runs_root=tmp_path)
    assert run.run_dir.parent == tmp_path
    assert (run.run_dir / "events.json").exists()
    assert (run.run_dir / "result.json").exists()
    result = json.loads((run.run_dir / "result.json").read_text())
    assert result["scenario"] == "my_test"
    assert result["status"] == "passed"
    assert result["assertions"][0]["passed"] is True


def test_run_scenario_status_failed_when_assertion_fails(tmp_path: Path) -> None:
    s = Scenario(
        name="fail_test", tier=0, mission="machina_1", cogs=2, steps=3,
        assertions=[
            lambda run: AssertResult(name="x", passed=False, message="nope", failed_at_step=2)
        ],
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_stub_drive):
        run = run_scenario(s, runs_root=tmp_path)
    result = json.loads((run.run_dir / "result.json").read_text())
    assert result["status"] == "failed"


def test_run_scenario_applies_mission_overrides(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> int:
        captured["env"] = kwargs["env_cfg"]
        return _stub_drive(**kwargs)

    s = Scenario(
        name="override_test", tier=0, mission="machina_1", cogs=2, steps=7,
        mission_overrides={"max_steps": 7},
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_capture):
        run_scenario(s, runs_root=tmp_path)
    assert captured["env"].game.max_steps == 7


def test_run_scenario_runs_setup_hook(tmp_path: Path) -> None:
    called = []

    def _setup(env_cfg: Any) -> None:
        called.append(env_cfg)
        env_cfg.game.agents[0].inventory.initial["miner"] = 1

    s = Scenario(
        name="setup_test", tier=0, mission="machina_1", cogs=1, steps=3,
        setup=_setup,
    )

    def _verify(**kwargs: Any) -> int:
        assert kwargs["env_cfg"].game.agents[0].inventory.initial.get("miner") == 1
        return _stub_drive(**kwargs)

    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_verify):
        run_scenario(s, runs_root=tmp_path)
    assert len(called) == 1


def test_resolve_mission_machina_default_cogs() -> None:
    m = resolve_mission("machina_1")
    assert m.num_agents >= 1


def test_resolve_mission_tutorial_with_cogs() -> None:
    m = resolve_mission("tutorial.miner", cogs=1)
    assert m.num_agents == 1


def test_run_scenario_variants_applied(tmp_path: Path) -> None:
    def _capture(**kwargs: Any) -> int:
        return _stub_drive(**kwargs)

    # Cover the `if scenario.variants:` branch (line 159-160)
    s = Scenario(
        name="variants_test", tier=0, mission="tutorial.miner", cogs=1, steps=3,
        variants=("miner",),
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_capture):
        run_scenario(s, runs_root=tmp_path)


def test_run_scenario_variant_overrides_applied(tmp_path: Path) -> None:
    def _capture(**kwargs: Any) -> int:
        return _stub_drive(**kwargs)

    # Cover the `for vname, patches in scenario.variant_overrides.items():`
    # branch (lines 163-166). description is a writable field on the variant.
    s = Scenario(
        name="variant_override", tier=0, mission="tutorial.miner", cogs=1, steps=3,
        variants=("miner",),
        variant_overrides={"miner": {"description": "tweaked"}},
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_capture):
        run_scenario(s, runs_root=tmp_path)


def test_run_scenario_rejects_unknown_policy_kwargs(tmp_path: Path) -> None:
    s = Scenario(
        name="bad_kwargs", tier=0, mission="machina_1", cogs=1, steps=3,
        policy_kwargs={"not_a_real_kwarg": 42},
    )
    with pytest.raises(ValueError, match="unknown CvCPolicy kwarg"):
        run_scenario(s, runs_root=tmp_path)


def test_run_scenario_renders_report_html(tmp_path: Path) -> None:
    """After `run_scenario`, a non-empty report.html lands in the run folder."""
    s = Scenario(
        name="render_test", tier=0, mission="machina_1", cogs=2, steps=3,
        assertions=[lambda run: AssertResult(name="dummy", passed=True)],
    )
    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_stub_drive):
        run = run_scenario(s, runs_root=tmp_path)
    report = run.run_dir / "report.html"
    assert report.exists()
    assert report.stat().st_size > 0


def test_run_scenario_propagates_render_failure(tmp_path: Path) -> None:
    """If `render()` raises, let the error surface — don't mask it."""
    s = Scenario(
        name="render_crash", tier=0, mission="machina_1", cogs=1, steps=3,
        assertions=[lambda run: AssertResult(name="dummy", passed=True)],
    )

    class _Boom(RuntimeError):
        pass

    def _boom(_run_dir: Path) -> Path:
        raise _Boom("render exploded")

    with patch("cvc_policy.scenarios.harness._drive_rollout", side_effect=_stub_drive):
        with patch("cvc_policy.scenarios.harness.render_report", side_effect=_boom):
            with pytest.raises(_Boom):
                run_scenario(s, runs_root=tmp_path)
    # result.json was still written before the render step.
    # Find the single run dir that was created.
    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "result.json").exists()
