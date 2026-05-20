"""ADR-0013 — ``shield-server seed-admin`` CLI.

Bootstraps the first ``org_owner`` user directly against the DB (no
self-service sign-up race; sign-up is hard-disabled in enterprise mode per
§A1.c). Idempotent at three levels:

  1. The ``organizations`` row is upserted ``ON CONFLICT (org_id) DO NOTHING``
     so ``--org <existing-id>`` is a no-op for the org and ``--org <new-id>``
     auto-creates it. The 12-step W3 ingest already enforces ``org_id`` FK
     into ``organizations``; without this insert the very first admin in a
     fresh org bootstraps a foreign-key violation.
  2. ``find_by_email`` short-circuits if the email already exists (no
     ``users`` row recreation).
  3. The UNIQUE INDEX on lower(email) is the final backstop if (2) races.

Password via ``--password`` flag OR ``SHIELD_SEED_ADMIN_PASSWORD`` env OR
interactive prompt. Argon2id parameters are validated against §A1 caps via
``Settings.from_env()`` → ``PasswordHasherService.from_settings``.

Usage:

    uv run python -m shield_server.auth.cli seed-admin \\
        --email alice@example.com --org demo-org [--name "Alice"]
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from ..config import Settings
from ..storage.interfaces import Database
from .passwords import PasswordHasherService
from .users import create_user, find_by_email
from .utils import now_ms


def _prompt_password() -> str:
    """Read a password from $SHIELD_SEED_ADMIN_PASSWORD or stdin (no echo)."""
    pw = os.environ.get("SHIELD_SEED_ADMIN_PASSWORD")
    if pw:
        return pw
    return getpass.getpass("Password for new admin: ")


async def _ensure_organization(db: Database, *, org_id: str, name: str) -> None:
    """Idempotently INSERT an ``organizations`` row.

    ``ON CONFLICT (org_id) DO NOTHING`` so ``--org`` IDs that already exist
    (``demo-org`` after the standard W3 migrate seed) become a clean no-op,
    and ``--org`` IDs that are NEW are bootstrapped here so the subsequent
    ``memberships.org_id`` FK is satisfied.
    """
    now = now_ms()
    await db.execute(
        "INSERT INTO organizations (org_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $3) ON CONFLICT (org_id) DO NOTHING",
        org_id,
        name,
        now,
    )


async def _seed_admin_via_db(
    db: Database, *, email: str, org: str, name: str, password: str
) -> str:
    """Core seed logic against an already-open ``Database`` handle.

    Factored out of ``_seed_admin`` so unit tests can drive the flow
    against ``MemoryDatabase`` (the CLI itself talks to the real Postgres
    adapter; the in-memory path is test-only). Returns a single-line
    summary suitable for stdout.
    """
    hasher = PasswordHasherService.from_settings(Settings.from_env())
    # (1) Ensure the org row exists — idempotent ON CONFLICT DO NOTHING.
    await _ensure_organization(db, org_id=org, name=org)
    # (2) If the user already exists, no-op.
    existing = await find_by_email(db, email=email)
    if existing is not None:
        return (
            f"shield-server seed-admin: user {email!r} already exists "
            f"(user_id={existing.user_id}); no-op."
        )
    # (3) Create the user + org_owner membership.
    user = await create_user(
        db,
        hasher,
        email=email,
        password=password,
        name=name,
        org_id=org,
        role="org_owner",
    )
    return (
        f"shield-server seed-admin: created org_owner user_id={user.user_id} "
        f"email={email} org={org}"
    )


async def _seed_admin(*, email: str, org: str, name: str, password: str) -> str:
    """Connect to the configured DSN and seed via ``_seed_admin_via_db``.

    Uses the real ``PostgresDatabase`` adapter (this is a one-shot
    bootstrap that requires a running Postgres); the in-memory path is
    test-only and not exposed via the CLI.
    """
    from ..storage import PostgresDatabase

    settings = Settings.from_env()
    db = await PostgresDatabase.connect(settings.database_url)
    try:
        return await _seed_admin_via_db(db, email=email, org=org, name=name, password=password)
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shield-server",
        description="Shield-server enterprise-auth bootstrap CLI.",
    )
    sub = parser.add_subparsers(dest="command")
    seed = sub.add_parser("seed-admin", help="Create the first org_owner user.")
    seed.add_argument("--email", required=True, help="Email of the new admin user.")
    seed.add_argument(
        "--org",
        default="demo-org",
        help="Organization id (FK into organizations; auto-created if not present).",
    )
    seed.add_argument("--name", default="", help="Display name.")
    seed.add_argument(
        "--password",
        default=None,
        help="Password (else $SHIELD_SEED_ADMIN_PASSWORD env, else interactive prompt).",
    )
    args = parser.parse_args(argv)
    if args.command != "seed-admin":
        parser.print_help(file=sys.stderr)
        return 2
    password = args.password or _prompt_password()
    if not password or len(password) < 8:
        sys.stderr.write("Password must be at least 8 characters.\n")
        return 2
    try:
        result = asyncio.run(
            _seed_admin(email=args.email, org=args.org, name=args.name, password=password)
        )
        sys.stdout.write(result + "\n")
        return 0
    except Exception as exc:  # pragma: no cover - prod-only DB error path
        sys.stderr.write(f"shield-server seed-admin: ERROR: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
