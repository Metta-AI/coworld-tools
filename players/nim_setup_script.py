import runpy
from pathlib import Path

build_module = Path.cwd() / "src" / "cogames_agents" / "policy" / "nim_agents" / "build.py"
mod = runpy.run_path(str(build_module))
mod["build_nim"]()
