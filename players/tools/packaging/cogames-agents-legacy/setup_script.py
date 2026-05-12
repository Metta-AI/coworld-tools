import subprocess
import sys

subprocess.check_call(["uv", "pip", "install", "--python", sys.executable, "cogames", "numpy"])
