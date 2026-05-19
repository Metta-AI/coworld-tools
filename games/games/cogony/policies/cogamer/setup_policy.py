"""Setup script for cogames upload -- installs LLM dependencies in the episode runner."""

import subprocess
import sys

subprocess.check_call(
    [
        "uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "anthropic[bedrock]>=0.64.0",
    ]
)
