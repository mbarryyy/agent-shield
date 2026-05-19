"""W0: import every shield-server submodule so the stub surface is covered."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from shield_server import app, audit, ingest, merkle, migrate, storage  # noqa: F401


def test_submodules_import() -> None:
    assert app and audit and ingest and merkle and storage


def test_migrate_stub_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        migrate.main()
    assert "W0 stub" in buf.getvalue()
