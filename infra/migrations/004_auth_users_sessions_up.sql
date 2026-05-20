-- ADR-0013 — Enterprise Auth v1 / schema_version 4 (UP)
--
-- Additive, idempotent, NO `ALTER` on W3 tables, NO FK back-refs into W3
-- tables (§A5 protected set: agents, agent_keys, operations, receipts,
-- epochs, exports, agent_sessions, intervention_log, governance_verdicts).
--
-- Tables in this revision: users, sessions, memberships,
-- password_reset_tokens, email_verification_tokens, invites,
-- totp_credentials. (api_keys + audit_log_auth land in revision 005.)

CREATE TABLE IF NOT EXISTS users (
  user_id              TEXT    PRIMARY KEY,        -- uuidv7 string
  email                TEXT    NOT NULL,            -- case-insensitive unique index below
  password_hash        TEXT    NOT NULL,            -- argon2id (§A1) + peppered
  password_pepper_kid  TEXT    NOT NULL,            -- which SHIELD_PASSWORD_PEPPERS kid this hash used
  name                 TEXT    NOT NULL DEFAULT '',
  status               TEXT    NOT NULL DEFAULT 'active',  -- active | locked | disabled
  email_verified_at    BIGINT,
  failed_login_count   INTEGER NOT NULL DEFAULT 0,
  locked_until         BIGINT,
  totp_enabled         BOOLEAN NOT NULL DEFAULT FALSE,
  created_at           BIGINT  NOT NULL,
  updated_at           BIGINT  NOT NULL,
  last_login_at        BIGINT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users (lower(email));
CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);

CREATE TABLE IF NOT EXISTS sessions (
  session_id           TEXT    PRIMARY KEY,        -- uuidv7 string
  user_id              TEXT    NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  token_hash           TEXT    NOT NULL UNIQUE,    -- sha256(cookie_value)
  csrf_token           TEXT    NOT NULL,           -- random 32B b64url; double-submit (§A10)
  ip                   TEXT,
  user_agent           TEXT,
  created_at           BIGINT  NOT NULL,
  last_used_at         BIGINT  NOT NULL,
  expires_at           BIGINT  NOT NULL,
  revoked_at           BIGINT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions (user_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);

-- NB: organizations(org_id) already exists from migration 001 (W1 Elydora
-- port). We REFERENCE it but never ALTER it; the demo-org row continues to
-- be seeded by the existing migrate.py _SEED_DEMO_ORG, and W3 has rows in
-- agents/operations that pre-date enterprise-auth — additive only.
CREATE TABLE IF NOT EXISTS memberships (
  user_id              TEXT    NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  org_id               TEXT    NOT NULL REFERENCES organizations (org_id),
  role                 TEXT    NOT NULL CHECK (role IN (
                          'org_owner',
                          'security_admin',
                          'integration_engineer',
                          'compliance_auditor',
                          'readonly_investigator'
                       )),
  invited_by           TEXT    REFERENCES users (user_id),
  joined_at            BIGINT  NOT NULL,
  PRIMARY KEY (user_id, org_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_org_role ON memberships (org_id, role);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  token_hash           TEXT    PRIMARY KEY,        -- sha256(one-time-token)
  user_id              TEXT    NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  expires_at           BIGINT  NOT NULL,
  consumed_at          BIGINT,
  created_at           BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens (user_id);

CREATE TABLE IF NOT EXISTS email_verification_tokens (
  token_hash           TEXT    PRIMARY KEY,
  user_id              TEXT    NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  expires_at           BIGINT  NOT NULL,
  consumed_at          BIGINT,
  created_at           BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_verify_user ON email_verification_tokens (user_id);

CREATE TABLE IF NOT EXISTS invites (
  invite_id            TEXT    PRIMARY KEY,        -- uuidv7
  org_id               TEXT    NOT NULL REFERENCES organizations (org_id),
  email                TEXT    NOT NULL,
  role                 TEXT    NOT NULL CHECK (role IN (
                          'org_owner',
                          'security_admin',
                          'integration_engineer',
                          'compliance_auditor',
                          'readonly_investigator'
                       )),
  invited_by           TEXT    NOT NULL REFERENCES users (user_id),
  expires_at           BIGINT  NOT NULL,
  consumed_at          BIGINT,
  created_at           BIGINT  NOT NULL,
  token_hash           TEXT    NOT NULL UNIQUE     -- sha256(invite-link-token)
);
CREATE INDEX IF NOT EXISTS idx_invites_org_email ON invites (org_id, lower(email));

CREATE TABLE IF NOT EXISTS totp_credentials (
  user_id              TEXT    PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
  secret_encrypted     TEXT    NOT NULL,           -- Fernet/MultiFernet wrap of base32 secret (§A6)
  active_kid           TEXT    NOT NULL,           -- SHIELD_AUTH_FERNET_KEYS kid that last wrote this
  recovery_codes_hash  TEXT[]  NOT NULL,           -- 10 codes, sha256, single-use (popped on use)
  enabled_at           BIGINT  NOT NULL,
  last_used_at         BIGINT
);

INSERT INTO schema_versions (version, applied_at, description)
VALUES (
  4,
  EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  'ADR-0013: users/sessions/memberships/reset/verify/invites/totp'
)
ON CONFLICT (version) DO NOTHING;
