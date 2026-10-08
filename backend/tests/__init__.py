"""The backend test package.

PR #54 review B1: the automatic demo materialization is OFF for every test
process. This runs before ``conftest.py`` imports ``minegen.main`` (which
builds the cached settings), so no test — and no application a test
constructs — ever bakes into the real ``data/demos``.
"""

import os

os.environ.setdefault("MINEGEN_DEMOS_AUTOBAKE", "0")
