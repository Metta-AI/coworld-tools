from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from cogames_rl_researcher.startup import StartupConfig, run_startup

from softmax.auth import DEFAULT_COGAMES_SERVER, has_saved_token
from softmax.token_storage import TokenKind


@pytest.mark.integration
def test_startup_live_auth_and_leaderboard(tmp_path: Path) -> None:
    if os.getenv("COGAMES_RL_RESEARCHER_RUN_LIVE") != "1":
        pytest.skip("Set COGAMES_RL_RESEARCHER_RUN_LIVE=1 to run live integration checks")

    if shutil.which("cogames") is None:
        pytest.skip("cogames binary not available")

    login_server = os.getenv("COGAMES_RL_RESEARCHER_LIVE_LOGIN_SERVER", DEFAULT_COGAMES_SERVER)
    if not has_saved_token(token_kind=TokenKind.COGAMES, server=login_server):
        pytest.skip(f"no saved auth token for {login_server}")

    policy_uri = os.getenv("COGAMES_RL_RESEARCHER_LIVE_POLICY", "metta://policy/role_py")
    policy_name = os.getenv("COGAMES_RL_RESEARCHER_LIVE_POLICY_NAME")
    if not policy_name:
        pytest.skip("set COGAMES_RL_RESEARCHER_LIVE_POLICY_NAME to a policy name visible on leaderboard")

    bundle = run_startup(
        StartupConfig(
            policy=policy_uri,
            policy_name=policy_name,
            season=os.getenv("COGAMES_RL_RESEARCHER_LIVE_SEASON", "beta-cvc"),
            output_root=tmp_path / "artifacts",
            cogames_bin="cogames",
            login_server=login_server,
            server=os.getenv("COGAMES_RL_RESEARCHER_LIVE_SERVER", "https://api.observatory.softmax-research.net"),
            episodes=1,
            steps=50,
            detect_idle_seconds=120,
            max_step_seconds=1800,
            run_upload=False,
            run_submit=False,
            run_leaderboard=True,
            allow_interactive_login=False,
        )
    )

    assert bundle.status == "success"
    assert bundle.docs_digest_path is not None
    assert Path(bundle.docs_digest_path).exists()
    assert any(step.step_name == "docs_readthrough" and step.status == "success" for step in bundle.steps)
