import subprocess
import sys

# Pin older cogames/mettagrid to match v65 era game mechanics
subprocess.check_call(
    [
        "uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "cogames>=0.19,<0.20",
        "mettagrid>=0.19,<0.20",
        "anthropic[bedrock]>=0.64.0",
        "openai>=1.50.0",
    ]
)
