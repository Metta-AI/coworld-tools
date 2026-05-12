import subprocess
import sys

try:
    subprocess.check_call(
        [
            "uv", "pip", "install",
            "--python", sys.executable,
            "anthropic[bedrock]>=0.64.0",
            "openai>=1.50.0",
        ]
    )
except Exception:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install",
         "anthropic[bedrock]>=0.64.0",
         "openai>=1.50.0"]
    )
