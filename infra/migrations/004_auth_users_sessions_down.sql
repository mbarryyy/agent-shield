-- ADR-0013 — Enterprise Auth v1 / schema_version 4 (DOWN; CI-fire-drill-only, §A5)
--
-- DROPs ONLY the tables created by 004 up. NEVER touches W3 protected
-- tables (agents, agent_keys, operations, receipts, epochs, exports,
-- agent_sessions, intervention_log, governance_verdicts) — the §A5
-- fire-drill asserts W3 byte-identity (row_count AND row_checksum) before
-- vs. after up→down.
--
-- migrate.py has NO public `down` subcommand; invoked ONLY by the test
-- harness via internal `_apply_down(rev)`.

DROP TABLE IF EXISTS totp_credentials CASCADE;
DROP TABLE IF EXISTS invites CASCADE;
DROP TABLE IF EXISTS email_verification_tokens CASCADE;
DROP TABLE IF EXISTS password_reset_tokens CASCADE;
DROP TABLE IF EXISTS memberships CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS users CASCADE;

DELETE FROM schema_versions WHERE version = 4;
