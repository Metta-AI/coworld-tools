"""Put the implementation modules on the import path for the tests.

The default commissioner is a flat, self-contained app (the container runs it
with this directory as the working directory), so the tests import `server`,
`strategies`, and `graduation` by bare name.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
