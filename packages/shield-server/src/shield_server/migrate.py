"""`python -m shield_server.migrate` — DB migration entrypoint.

1:1 port of Elydora packages/server/migrations/001_initial.sql (idempotent
`CREATE TABLE IF NOT EXISTS`), plus an idempotent demo-org seed so the console
boots against a known-good schema. `integration.yml` runs this against the
docker-compose Postgres before the integration suite.
"""

from __future__ import annotations

import asyncio
import os

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

-- W2: structured intervention log (master design §2.5 cost hook #3 ≡ eval §9
-- dep #2). One server-owned write per /v1/governance/decide; tokens_in/out +
-- model_id + served_via are populated by governance's token counter (hook #1)
-- via the §4 record/verdict — server owns the TABLE+WRITE, not the counts.
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

-- W3 PR-S2: §4 correlation/run/phase made queryable on the per-agent chain.
-- ADDITIVE nullable columns — the W1 Elydora-EOR ingest leaves them NULL;
-- the §4 /decide + /record paths populate them so the console READ contract
-- (timeline / verdicts-by-correlation_id / provenance DAG) can query the
-- chain directly. NOT a §4 schema change (server-owned PG, not contracts/).
ALTER TABLE operations ADD COLUMN IF NOT EXISTS correlation_id TEXT;
ALTER TABLE operations ADD COLUMN IF NOT EXISTS run_id         TEXT;
ALTER TABLE operations ADD COLUMN IF NOT EXISTS phase          TEXT;
CREATE INDEX IF NOT EXISTS idx_operations_corr ON operations (correlation_id);
CREATE INDEX IF NOT EXISTS idx_operations_run  ON operations (org_id, run_id, created_at);

-- W3 PR-S2: signed-verdict store backing the console verdict tab. The full
-- signed GovernanceVerdict envelope is object-stored (r2_verdict_key); this
-- row indexes it by correlation_id/run_id for the console READ contract.
-- Distinct from intervention_log (the cost hook#3 SINK) — no token columns.
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
  -- W3 PR-S4 (hook#5 /cost): server stores the value gov/sdk put in the §4
  -- GovernanceVerdict.obligations.prevented_loss (the MEASURED AgentDojo
  -- env-diff). /cost is a pure READ-rollup of this — NO server recompute.
  prevented_loss  DOUBLE PRECISION NOT NULL DEFAULT 0,
  r2_verdict_key  TEXT    NOT NULL,
  created_at      BIGINT  NOT NULL
);
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


def schema_sql() -> str:
    """The DDL applied by `migrate` (unit-asserted; idempotent)."""
    return SCHEMA_SQL


async def apply(dsn: str) -> None:  # pragma: no cover - integration-only (real PG)
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(_SEED_DEMO_ORG, DEMO_ORG_ID)
    finally:
        await conn.close()


def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "postgresql://shield:shield@localhost:5432/shield")
    asyncio.run(apply(dsn))
    print(f"shield_server.migrate: schema applied; demo org '{DEMO_ORG_ID}' seeded")


if __name__ == "__main__":
    main()
