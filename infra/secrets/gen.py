"""Generate enterprise-auth secret material (ADR-0013).

Subcommands:
  session       → base64url(32B), no padding   — for SHIELD_SESSION_SECRETS
  pepper        → base64url(32B), no padding   — for SHIELD_PASSWORD_PEPPERS
  fernet        → cryptography.fernet 44-char  — for SHIELD_AUTH_FERNET_KEYS
  jwt-ed25519   → Ed25519 PEM private + public — reserved for v1.x (ADR-0013 D3)

`--seed <int>` makes output deterministic (tests); otherwise random.

Output discipline: prints ONE line per invocation (the secret material),
no banners, no trailing whitespace — safe for `$(python ... gen.py session)`
substitution in shell. Errors print to stderr and exit non-zero.
"""

from __future__ import annotations

import argparse
import base64
import random
import secrets
import sys

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _rand_bytes(n: int, seed: int | None) -> bytes:
    if seed is None:
        return secrets.token_bytes(n)
    # Deterministic for tests: seeded PRNG, NEVER for production secrets.
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(n))


def cmd_session(seed: int | None) -> str:
    """32 bytes of entropy, base64url-encoded, no padding."""
    return base64.urlsafe_b64encode(_rand_bytes(32, seed)).rstrip(b"=").decode("ascii")


def cmd_pepper(seed: int | None) -> str:
    """Same shape as session; named separately for ADR-0013 traceability."""
    return base64.urlsafe_b64encode(_rand_bytes(32, seed)).rstrip(b"=").decode("ascii")


def cmd_fernet(seed: int | None) -> str:
    """44-char Fernet key (base64url-encoded 32B with padding, per cryptography lib)."""
    if seed is None:
        return Fernet.generate_key().decode("ascii")
    # Deterministic variant: build the 32B key ourselves, then base64-encode with
    # standard padding (Fernet's wire format, NOT no-pad base64url).
    return base64.urlsafe_b64encode(_rand_bytes(32, seed)).decode("ascii")


def cmd_jwt_ed25519(seed: int | None) -> str:
    """Ed25519 keypair — PEM private + PEM public, base64url-joined with a marker.

    Format (single line): `<b64url(private_pem)>.<b64url(public_pem)>` so the
    output stays one line for env-var substitution. Reserved for v1.x; v1 does
    not issue JWTs (ADR-0013 D3).
    """
    if seed is not None:
        # Use deterministic raw seed bytes to derive the Ed25519 key.
        private_key = Ed25519PrivateKey.from_private_bytes(_rand_bytes(32, seed))
    else:
        private_key = Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_b64 = base64.urlsafe_b64encode(priv_pem).rstrip(b"=").decode("ascii")
    pub_b64 = base64.urlsafe_b64encode(pub_pem).rstrip(b"=").decode("ascii")
    return f"{priv_b64}.{pub_b64}"


_COMMANDS = {
    "session": cmd_session,
    "pepper": cmd_pepper,
    "fernet": cmd_fernet,
    "jwt-ed25519": cmd_jwt_ed25519,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="infra/secrets/gen.py",
        description="Generate enterprise-auth secret material (ADR-0013).",
    )
    parser.add_argument("subcommand", choices=sorted(_COMMANDS.keys()))
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Deterministic seed for tests; OMIT in production (random by default).",
    )
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.subcommand]
    print(handler(args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
