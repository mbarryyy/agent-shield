-- ADR-0013 — Enterprise Auth v1 / schema_version 5 (UP)
--
-- Additive, idempotent, NO ALTER on W3 tables, NO FK back-refs into W3
-- tables. Tables in this revision:
--   * api_keys           — D1/§A8 tri-mode scoping (org-wide / single-agent / allowlist)
--   * audit_log_auth     — every auth event (mirrors intervention_log:110 SINK pattern)
--
-- api_keys.agent_id is NULLABLE — a NULL agent_id with a NULL agent_id_allowlist
-- means "org-wide" (UI default). The cross-check predicate
-- `authorize_ingest(principal, record)` enforces tri-mode scope at /v1/governance/
-- {decide,record} ingest (§A8); SDK cannot enforce — server is authoritative.

CREATE TABLE IF NOT EXISTS api_keys (
  api_key_id            TEXT    PRIMARY KEY,           -- uuidv7
  org_id                TEXT    NOT NULL REFERENCES organizations (org_id),
  -- NULLABLE: NULL agent_id + NULL agent_id_allowlist = org-wide scope (D1).
  agent_id              TEXT,
  -- TEXT[] of agent_ids; mutually exclusive with a non-NULL agent_id (the
  -- predicate handles all three modes; the schema permits both NULL for
  -- org-wide, exactly-one-non-NULL for single-agent, exactly-one-non-NULL
  -- for allowlist — application-level invariant, not a DB CHECK so the
  -- ALTERless ADR-0013 evolution path is preserved).
  agent_id_allowlist    TEXT[],
  token_hash            TEXT    NOT NULL UNIQUE,       -- sha256(opaque bearer)
  prefix                TEXT    NOT NULL,              -- `as_live_` / `as_test_` (display-only, see §A7)
  display_name          TEXT    NOT NULL DEFAULT '',
  created_by            TEXT    NOT NULL REFERENCES users (user_id),
  created_at            BIGINT  NOT NULL,
  expires_at            BIGINT,                        -- NULL = never expires (admin must rotate)
  last_used_at          BIGINT,
  revoked_at            BIGINT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys (org_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_agent ON api_keys (agent_id);

CREATE TABLE IF NOT EXISTS audit_log_auth (
  audit_id              TEXT    PRIMARY KEY,           -- uuidv7
  user_id               TEXT,                          -- NULL if sign-in failed for unknown email
  org_id                TEXT,
  event                 TEXT    NOT NULL,
  ip                    TEXT,
  user_agent            TEXT,
  detail                JSONB   NOT NULL DEFAULT '{}'::JSONB,
  created_at            BIGINT  NOT NULL
);
-- Reserved for the future PII-retention purge job (D7): purge by created_at.
CREATE INDEX IF NOT EXISTS idx_audit_auth_user_created ON audit_log_auth (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_auth_created ON audit_log_auth (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_auth_event ON audit_log_auth (event, created_at);

INSERT INTO schema_versions (version, applied_at, description)
VALUES (
  5,
  EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  'ADR-0013: api_keys (tri-mode D1/§A8) + audit_log_auth (auth SINK)'
)
ON CONFLICT (version) DO NOTHING;
