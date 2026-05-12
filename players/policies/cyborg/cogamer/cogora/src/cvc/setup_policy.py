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
        "openai>=1.50.0",
    ]
)
