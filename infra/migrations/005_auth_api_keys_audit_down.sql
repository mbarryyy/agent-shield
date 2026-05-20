-- ADR-0013 — Enterprise Auth v1 / schema_version 5 (DOWN; CI-fire-drill-only, §A5)
--
-- DROPs ONLY the tables created by 005 up. NEVER touches W3 protected
-- tables. Invoked ONLY by the test harness via internal `_apply_down(rev)`;
-- migrate.py has no public `down` subcommand.

DROP TABLE IF EXISTS audit_log_auth CASCADE;
DROP TABLE IF EXISTS api_keys CASCADE;

DELETE FROM schema_versions WHERE version = 5;
