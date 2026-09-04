"""MCP server exposing apm_connectors' /tools/* API as agent tools.

See server.py's module docstring for the full picture; this package is
the agent-facing side of the split docs/api-contract.md and this
repo's CLAUDE.md commit to -- connectors stay reasoning-free, and
whatever reasoning layer consumes them (here, via MCP) is deployed
separately.
"""
