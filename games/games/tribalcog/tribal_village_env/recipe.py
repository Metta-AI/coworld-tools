"""Metta recipe entrypoints for the standalone TribalCog package."""

from __future__ import annotations

import subprocess
from typing import Literal

from tribal_village_env.config import DEFAULT_ANSI_STEPS, DEFAULT_PROFILE_STEPS


def play():
    from metta.common.tool import Tool
    from metta.common.util.fs import get_repo_root

    class TribalCogPlayTool(Tool):
        render: Literal["gui", "ansi", "none"] = "none"
        steps: int = DEFAULT_ANSI_STEPS
        max_steps: int | None = None
        random_actions: bool = True
        profile: bool = False
        profile_steps: int = DEFAULT_PROFILE_STEPS
        step_timing: bool = False
        step_timing_target: int = 0
        step_timing_window: int = 0
        render_timing: bool = False
        render_timing_target: int = 0
        render_timing_window: int = 0
        render_timing_every: int = 1
        render_timing_exit: int | None = None
        policy_uri: str | None = None
        num_agents: int | None = None
        cogs: int | None = None

        def invoke(self, args: dict[str, str]) -> int:
            del args
            if self.policy_uri is not None:
                raise ValueError("tribalcog external play does not support policy_uri overrides")
            if self.num_agents is not None or self.cogs is not None:
                raise ValueError("tribalcog external play uses the standalone game's fixed agent count")

            repo_root = get_repo_root()
            cli_render = "ansi" if self.render == "none" else self.render
            cmd = [
                "uv",
                "run",
                "--project",
                str(repo_root),
                "--extra",
                "tribalcog",
                "tribalcog",
                "play",
                "--render",
                cli_render,
                "--steps",
                str(self.steps),
                "--random-actions" if self.random_actions else "--no-random-actions",
            ]
            if self.max_steps is not None:
                cmd.extend(["--max-steps", str(self.max_steps)])
            if self.profile:
                cmd.extend(["--profile", "--profile-steps", str(self.profile_steps)])
            if self.step_timing:
                cmd.extend(
                    [
                        "--step-timing",
                        "--step-timing-target",
                        str(self.step_timing_target),
                        "--step-timing-window",
                        str(self.step_timing_window),
                    ]
                )
            if self.render_timing:
                cmd.extend(
                    [
                        "--render-timing",
                        "--render-timing-target",
                        str(self.render_timing_target),
                        "--render-timing-window",
                        str(self.render_timing_window),
                        "--render-timing-every",
                        str(self.render_timing_every),
                    ]
                )
            if self.render_timing_exit is not None:
                cmd.extend(["--render-timing-exit", str(self.render_timing_exit)])

            run_kwargs: dict[str, object] = {"cwd": repo_root, "check": True}
            if self.render == "none":
                run_kwargs["stdout"] = subprocess.DEVNULL
            subprocess.run(cmd, **run_kwargs)
            return 0

    return TribalCogPlayTool()
