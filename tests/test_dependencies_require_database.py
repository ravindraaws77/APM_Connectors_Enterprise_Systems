"""Confirms the API server's own dependency providers (get_state_store,
get_action_graph) refuse to build anything without DATABASE_URL -- there
is no file-backed/SQLite/in-memory fallback, mirroring apm_orchestrator's
poller.py/run_case.py raising SystemExit without DATABASE_URL for its own
(separate) Postgres-only case-graph checkpointer. Both providers are
@lru_cache'd, but functools.lru_cache never caches a call that raises, so
these don't need to clear anything after a failing call; they still clear
before/after in case DATABASE_URL happens to be set in this environment
and a prior/later test populated the cache with a real Postgres pool.
"""

import pytest

from apm_connectors.api import dependencies as dependencies_module


@pytest.fixture(autouse=True)
def _clear_dependency_caches():
    dependencies_module.get_state_store.cache_clear()
    dependencies_module.get_action_graph.cache_clear()
    dependencies_module._get_postgres_pool.cache_clear()
    yield
    dependencies_module.get_state_store.cache_clear()
    dependencies_module.get_action_graph.cache_clear()
    dependencies_module._get_postgres_pool.cache_clear()


def test_get_state_store_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        dependencies_module.get_state_store()


def test_get_action_graph_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        dependencies_module.get_action_graph()
