"""`python -m shield_server.migrate` — DB migration entrypoint.

W1 W3-baseline (preserved byte-identically): Elydora 001 port + W2/W3 schema
inlined as ``SCHEMA_SQL`` (schema_versions 1/2/3).

ADR-0013 enterprise-auth additive revisions are file-resolved at runtime:

  4. ``infra/migrations/004_auth_users_sessions_up.sql``
        users / sessions / memberships / password_reset_tokens /
        email_verification_tokens / invites / totp_credentials
  5. ``infra/migrations/005_auth_api_keys_audit_up.sql``
        api_keys (D1 tri-mode) + audit_log_auth (auth SINK)

The runner applies ``SCHEMA_SQL`` first then every revision in the
``MIGRATIONS`` list in version order. No public ``down`` subcommand exists
(ADR-0013 §A5: down migrations are CI-fire-drill-only). The internal
``_apply_down(conn, version)`` helper is invoked ONLY by the test harness
in ``tests/integration/auth/test_a5_firedrill_fulldrill.py``; the runbook
forbids running down in production.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .config import DEMO_ORG_ID

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_versions (
  version     INTEGER PRIMARY KEY,
  applied_at  BIGINT NOT NULL,
  description TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
  org_id     TEXT   NOT NULL PRIMARY KEY,
  name       TEXT   NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
  agent_id           TEXT   NOT NULL PRIMARY KEY,
  org_id             TEXT   NOT NULL,
  display_name       TEXT   NOT NULL,
  responsible_entity TEXT   NOT NULL,
  integration_type   TEXT   NOT NULL DEFAULT 'sdk',
  status             TEXT   NOT NULL DEFAULT 'active',
  created_at         BIGINT NOT NULL,
  updated_at         BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_org_id ON agents (org_id);

CREATE TABLE IF NOT EXISTS agent_keys (
  kid        TEXT   NOT NULL PRIMARY KEY,
  agent_id   TEXT   NOT NULL REFERENCES agents (agent_id),
  public_key TEXT   NOT NULL,
  algorithm  TEXT   NOT NULL DEFAULT 'ed25519',
  status     TEXT   NOT NULL DEFAULT 'active',
  created_at BIGINT NOT NULL,
  retired_at BIGINT
);
CREATE INDEX IF NOT EXISTS idx_agent_keys_agent_id ON agent_keys (agent_id);

CREATE TABLE IF NOT EXISTS operations (
  operation_id     TEXT    NOT NULL PRIMARY KEY,
  org_id           TEXT    NOT NULL,
  agent_id         TEXT    NOT NULL REFERENCES agents (agent_id),
  seq_no           INTEGER NOT NULL,
  operation_type   TEXT    NOT NULL,
  issued_at        BIGINT  NOT NULL,
  ttl_ms           INTEGER NOT NULL,
  nonce            TEXT    NOT NULL,
  subject          TEXT    NOT NULL,
  action           TEXT    NOT NULL,
  payload_hash     TEXT    NOT NULL,
  prev_chain_hash  TEXT    NOT NULL,
  chain_hash       TEXT    NOT NULL,
  agent_pubkey_kid TEXT    NOT NULL,
  signature        TEXT    NOT NULL,
  r2_payload_key   TEXT,
  created_at       BIGINT  NOT NULL,
  UNIQUE (agent_id, seq_no)
);
CREATE INDEX IF NOT EXISTS idx_operations_org_created ON operations (org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_operations_agent_seq ON operations (agent_id, seq_no);
CREATE INDEX IF NOT EXISTS idx_operations_type ON operations (operation_type);

CREATE TABLE IF NOT EXISTS receipts (
  receipt_id     TEXT   NOT NULL PRIMARY KEY,
  operation_id   TEXT   NOT NULL UNIQUE REFERENCES operations (operation_id),
  r2_receipt_key TEXT   NOT NULL,
  created_at     BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS epochs (
  epoch_id     TEXT    NOT NULL PRIMARY KEY,
  org_id       TEXT    NOT NULL,
  start_time   BIGINT  NOT NULL,
  end_time     BIGINT  NOT NULL,
  root_hash    TEXT    NOT NULL,
  leaf_count   INTEGER NOT NULL,
  r2_epoch_key TEXT    NOT NULL,
  created_at   BIGINT  NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
  export_id      TEXT   NOT NULL PRIMARY KEY,
  org_id         TEXT   NOT NULL,
  status         TEXT   NOT NULL DEFAULT 'queued',
  query_params   TEXT   NOT NULL,
  r2_export_key  TEXT,
  created_at     BIGINT NOT NULL,
  completed_at   BIGINT
);
CREATE INDEX IF NOT EXISTS idx_exports_org_status ON exports (org_id, status);

CREATE TABLE IF NOT EXISTS intervention_log (
  verdict_id        TEXT    NOT NULL PRIMARY KEY,
  record_id         TEXT    NOT NULL,
  correlation_id    TEXT    NOT NULL,
  run_id            TEXT,
  decision          TEXT    NOT NULL,
  step_index        INTEGER NOT NULL,
  triggered_rule_id TEXT,
  tokens_in         INTEGER NOT NULL DEFAULT 0,
  tokens_out        INTEGER NOT NULL DEFAULT 0,
  model_id          TEXT,
  served_via        TEXT,
  latency_ms        DOUBLE PRECISION,
  created_at        BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intervention_run ON intervention_log (run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_intervention_corr ON intervention_log (correlation_id);

ALTER TABLE operations ADD COLUMN IF NOT EXISTS correlation_id TEXT;
ALTER TABLE operations ADD COLUMN IF NOT EXISTS run_id         TEXT;
ALTER TABLE operations ADD COLUMN IF NOT EXISTS phase          TEXT;
CREATE INDEX IF NOT EXISTS idx_operations_corr ON operations (correlation_id);
CREATE INDEX IF NOT EXISTS idx_operations_run  ON operations (org_id, run_id, created_at);

CREATE TABLE IF NOT EXISTS governance_verdicts (
  verdict_id      TEXT    NOT NULL PRIMARY KEY,
  record_id       TEXT    NOT NULL,
  correlation_id  TEXT    NOT NULL,
  run_id          TEXT,
  org_id          TEXT    NOT NULL,
  agent_id        TEXT    NOT NULL,
  decision        TEXT    NOT NULL,
  risk_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
  latency_ms      DOUBLE PRECISION,
  prevented_loss  DOUBLE PRECISION NOT NULL DEFAULT 0,
  r2_verdict_key  TEXT    NOT NULL,
  created_at      BIGINT  NOT NULL,
  resolution      TEXT,
  resolved_at     BIGINT
);
CREATE INDEX IF NOT EXISTS idx_gv_incident
  ON governance_verdicts (org_id, decision, created_at);
CREATE INDEX IF NOT EXISTS idx_gv_run  ON governance_verdicts (org_id, run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_gv_corr ON governance_verdicts (correlation_id);

INSERT INTO schema_versions (version, applied_at, description)
VALUES (1, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 'Initial schema (Elydora 001 port)')
ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_versions (version, applied_at, description)
VALUES (
  2,
  EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  'W2: Channel-2 intervention_log (cost hook #3)'
)
ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_versions (version, applied_at, description)
VALUES (
  3,
  EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  'W3 PR-S2: operations correlation/run/phase + governance_verdicts (console READ)'
)
ON CONFLICT (version) DO NOTHING;
"""

_SEED_DEMO_ORG = """
INSERT INTO organizations (org_id, name, created_at, updated_at)
VALUES ($1, 'Demo Org', EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
        EXTRACT(EPOCH FROM NOW())::BIGINT * 1000)
ON CONFLICT (org_id) DO NOTHING;
"""


# Repo-root-relative path to the migration SQL directory. The Path resolves
# from this file: ``packages/shield-server/src/shield_server/migrate.py`` →
# parents[4] = repo root → ``infra/migrations``.
_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "infra" / "migrations"


@dataclass(frozen=True, slots=True)
class MigrationRevision:
    """An ADR-0013 additive revision file pair (up + down).

    Down is CI-fire-drill-only per §A5; ``_apply_down`` invokes it via the
    test harness. The public ``apply`` runner NEVER invokes down.
    """

    version: int
    description: str
    up_path: Path
    down_path: Path


MIGRATIONS: tuple[MigrationRevision, ...] = (
    MigrationRevision(
        version=4,
        description="ADR-0013: users/sessions/memberships/reset/verify/invites/totp",
        up_path=_MIGRATIONS_DIR / "004_auth_users_sessions_up.sql",
        down_path=_MIGRATIONS_DIR / "004_auth_users_sessions_down.sql",
    ),
    MigrationRevision(
        version=5,
        description="ADR-0013: api_keys (tri-mode D1/§A8) + audit_log_auth (auth SINK)",
        up_path=_MIGRATIONS_DIR / "005_auth_api_keys_audit_up.sql",
        down_path=_MIGRATIONS_DIR / "005_auth_api_keys_audit_down.sql",
    ),
)


def schema_sql() -> str:
    """The W3-baseline DDL (unit-asserted; idempotent)."""
    return SCHEMA_SQL


def read_revision_sql(rev: MigrationRevision, *, direction: str) -> str:
    """Read an ADR-0013 revision file from disk; ``direction`` ∈ {up,down}."""
    if direction not in {"up", "down"}:
        raise ValueError(f"direction must be 'up' or 'down'; got {direction!r}")
    path = rev.up_path if direction == "up" else rev.down_path
    return path.read_text(encoding="utf-8")


# Awaitable[None]-returning executor type (asyncpg.Connection.execute matches).
_Executor = Callable[[str], Awaitable[None]]


async def _apply_schema(execute: _Executor) -> None:
    """Apply the W3-baseline SCHEMA_SQL through the supplied executor."""
    await execute(SCHEMA_SQL)


async def _apply_up(execute: _Executor, rev: MigrationRevision) -> None:
    """Apply one ADR-0013 up revision through the supplied executor."""
    await execute(read_revision_sql(rev, direction="up"))


async def _apply_down(execute: _Executor, version: int) -> None:
    """Apply one ADR-0013 down revision — TEST HARNESS ONLY (§A5).

    Raises ``ValueError`` if ``version`` does not correspond to an
    ADR-0013-managed revision. This intentional check guards against an
    accidental ``_apply_down(rev=1)`` (W3 baseline) from the test harness:
    only the auth additive revisions own a down file.
    """
    for rev in MIGRATIONS:
        if rev.version == version:
            await execute(read_revision_sql(rev, direction="down"))
            return
    raise ValueError(
        f"no down migration for version={version}; ADR-0013 manages "
        f"{[r.version for r in MIGRATIONS]} only (W3 baseline has no down per §A5)"
    )


async def apply(dsn: str) -> None:  # pragma: no cover - integration-only (real PG)
    """Public entrypoint: apply W3 baseline + every ADR-0013 up revision.

    Idempotent (all DDL is ``CREATE TABLE IF NOT EXISTS``); safe to rerun.
    """
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await _apply_schema(conn.execute)
        for rev in MIGRATIONS:
            await _apply_up(conn.execute, rev)
        await conn.execute(_SEED_DEMO_ORG, DEMO_ORG_ID)
    finally:
        await conn.close()


def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "postgresql://shield:shield@localhost:5432/shield")
    asyncio.run(apply(dsn))
    versions = ", ".join(str(r.version) for r in MIGRATIONS)
    print(
        f"shield_server.migrate: W3 baseline + ADR-0013 revisions [{versions}] "
        f"applied; demo org '{DEMO_ORG_ID}' seeded"
    )


if __name__ == "__main__":
    main()
