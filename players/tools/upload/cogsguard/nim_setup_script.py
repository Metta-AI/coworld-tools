"""Build bundled CogsGuard Nim agents during CoGames upload setup."""

import runpy
from pathlib import Path

build_module = (
    Path.cwd()
    / "src"
    / "agent_policies"
    / "policies"
    / "scripted"
    / "cogsguard"
    / "nim_agents"
    / "build.py"
)
mod = runpy.run_path(str(build_module))
mod["build_nim"]()
