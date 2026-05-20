"""Forcing-function for ADR-0013 §A5: the auth-integration job MUST import
the migration-firedrill helper signature server-builder is mandated to land.

This is intentionally RED on the w0-scaffold head (ImportError at collection)
and turns green automatically when server-builder's PR lands
`shield_server.auth.migration_firedrill.compare_w3_tables_byte_identity` per
ADR-0013 §A5. Closes the reviewer-flagged "silent-green" gap on auth-integration."""

import pytest

pytestmark = pytest.mark.integration_auth


def test_a5_migration_firedrill_helper_exists() -> None:
    # Server-builder lands this helper module per ADR-0013 §A5
    # (compare_w3_tables_byte_identity: pre_up vs post_down row_count + row_checksum
    # over W3_PROTECTED_TABLES). Until then this ImportErrors at collection and the
    # auth-integration CI job goes red — the forcing-function guarantee against
    # server-builder shipping without §A5 delivery.
    from shield_server.auth.migration_firedrill import compare_w3_tables_byte_identity  # noqa: F401
