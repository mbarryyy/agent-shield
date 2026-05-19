-- Agent Shield — minimal DB bootstrap (W0 scaffold).
-- Real migrations are owned by server-builder at W1 (`python -m shield_server.migrate`,
-- see implementation_plan.md W1). This file only guarantees the database exists with
-- the extensions the W1 schema will need, so `migrate` starts from a known state.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS shield;

COMMENT ON SCHEMA shield IS 'Agent Shield action records / Merkle audit (tables created by shield_server.migrate at W1)';
