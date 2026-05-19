"""Every shield-server submodule imports; migrate exposes the real schema."""

from __future__ import annotations

from shield_server import (  # noqa: F401
    agents,
    app,
    audit,
    auth,
    config,
    errors,
    ingest,
    merkle,
    migrate,
    models,
    storage,
)
from shield_server.routes import router


def test_submodules_import() -> None:
    assert app and audit and ingest and merkle and storage and agents and auth
    assert router is not None


def test_migrate_schema_sql_is_real() -> None:
    sql = migrate.schema_sql()
    for table in ("agents", "agent_keys", "operations", "receipts", "epochs"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    # The Elydora chain-serialization guarantee must survive the port.
    assert "UNIQUE (agent_id, seq_no)" in sql
