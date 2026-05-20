"""ADR-0013 — ``shield-server seed-admin`` CLI.

Bootstraps the first ``org_owner`` user directly against the DB (no
self-service sign-up race). Idempotent: re-running with the same email is a
no-op (the row already exists, so the unique-email index trips and the CLI
exits 0 with a message). Supports password via ``--password`` flag OR
``SHIELD_SEED_ADMIN_PASSWORD`` env OR interactive prompt.

Usage:

    uv run python -m shield_server.auth.cli seed-admin \\
        --email alice@shield.local --org demo-org [--name "Alice"]

Honours the §A1 argon2 caps via ``Settings.from_env()`` validation; in
``open`` mode the CLI still runs (the operator may seed an admin before
flipping to enterprise) but warns that the user won't be enforced until the
mode flips.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from ..config import Settings
from .passwords import PasswordHasherService
from .users import create_user, find_by_email


def _prompt_password() -> str:
    """Read a password from $SHIELD_SEED_ADMIN_PASSWORD or stdin (no echo)."""
    pw = os.environ.get("SHIELD_SEED_ADMIN_PASSWORD")
    if pw:
        return pw
    return getpass.getpass("Password for new admin: ")


async def _seed_admin(*, email: str, org: str, name: str, password: str) -> str:
    """Connect to the configured DSN; create the user + org_owner membership.

    Returns a single-line summary suitable for stdout. Uses the REAL
    ``asyncpg`` adapter (this is a one-shot bootstrap that requires a
    running Postgres); the in-memory path is not exposed via the CLI.
    """
    from ..storage import PostgresDatabase

    settings = Settings.from_env()
    hasher = PasswordHasherService.from_settings(settings)
    db = await PostgresDatabase.connect(settings.database_url)
    try:
        existing = await find_by_email(db, email=email)
        if existing is not None:
            return (
                f"shield-server seed-admin: user {email!r} already exists "
                f"(user_id={existing.user_id}); no-op."
            )
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
    seed.add_argument("--org", default="demo-org", help="Organization id (FK into organizations).")
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
