"""Skips tests/test_mcp_server.py when the optional `mcp` extra isn't
installed (`pip install .` / `.[connectors]`, no `[mcp]`), same "don't
fail collection over an optional dependency's test module" pattern as
AIAGENT_APM's root conftest.py handles for nicegui. Must live at the
repository root: pytest's pythonpath (pyproject.toml) collects
tests/test_mcp_server.py by walking from here.
"""

import importlib.util

if importlib.util.find_spec("mcp") is None:
    collect_ignore = ["tests/test_mcp_server.py"]
