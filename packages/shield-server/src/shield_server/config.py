"""Server configuration (env-driven). Defaults match infra/docker-compose.yml.

W3 baseline preserved: ``dev_auth_open``, ``api_token``, ``cors_origins``,
``server_signing_key``, ``database_url``, ``redis_url``, ``minio_*``,
``minio_bucket`` are all byte-identical to the W3 read path.

ADR-0013 additive (all optional, env-driven, sensible-default):

  * ``auth_mode``                         ∈ {open, enterprise, api_token_only}
  * ``allow_open_auth``                   the CLI flag, set by app entrypoint (NOT env)
  * ``session_secrets`` / ``password_peppers`` / ``fernet_keys``
                                          ordered ``(kid, secret)`` lists; first
                                          is the active key, the rest accept
                                          decryption for lazy-rotation
  * ``argon2_memory_kib`` / ``argon2_time_cost`` / ``argon2_parallelism``
                                          env-tunable, capped per §A1 (refuse-
                                          to-start when env exceeds cap)
  * ``email_backend``                     ∈ {console, file, smtp}; ``console``
                                          REFUSED under ``enterprise`` per §A4
  * cookie / SMTP / rate-limit transport knobs

Cap validation runs at ``Settings.from_env()`` so a misconfigured deployment
fails LOUDLY at startup, not silently per-request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# Elydora protocol limits (verbatim from
# Related_Work/Elydora-Open-Source-main/packages/server/src/shared/constants/limits.ts).
MAX_PAYLOAD_SIZE = 256 * 1024
MAX_TTL_MS = 300_000
MIN_TTL_MS = 1_000
MAX_NONCE_LENGTH = 64
MAX_QUERY_LIMIT = 1000
DEFAULT_QUERY_LIMIT = 100

PROTOCOL_VERSION = "1.0"
ELYDORA_KID = "elydora-server-key-v1"
DEMO_ORG_ID = "demo-org"

# Channel-2 (§4.3) — async action stream + consumer groups.
SHIELD_KID = "shield-server-key-v1"  # signs GovernanceVerdicts (golden-vector kid)
ACTIONS_STREAM_PREFIX = "shield:actions"  # XADD shield:actions:{workflow_id}
VERDICTS_STREAM_PREFIX = "shield:verdicts"  # XADD shield:verdicts:{workflow_id} (PR-S3)
CONSUMER_GROUPS = ("shield-evaluator", "shield-auditor")

# ADR-0013 §A1 — argon2id parameter HARDCODED CAPS (not env-tunable).
ARGON2_MEMORY_KIB_CAP = 262_144  # 256 MiB per-hash memory budget
ARGON2_TIME_COST_CAP = 8
ARGON2_PARALLELISM_CAP = 8

# ADR-0013 §A1 — argon2id parameter DEFAULTS (OWASP 2024-current).
ARGON2_MEMORY_KIB_DEFAULT = 65_536  # 64 MiB
ARGON2_TIME_COST_DEFAULT = 3
ARGON2_PARALLELISM_DEFAULT = 4

# ADR-0013 — session cookie defaults.
DEFAULT_COOKIE_NAME = "shield_session"
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 3600  # sliding 7 days

# Auth-mode + email-backend typed enums (used by deps + middleware).
AuthMode = Literal["open", "enterprise", "api_token_only"]
EmailBackend = Literal["console", "file", "smtp"]

# Governance LLM-router profile (cloud vs local/air-gapped) — selects which
# ``packages/shield-governance/src/shield_governance/config/models.<profile>.yaml``
# the async verdict worker loads to back the router-driven guardians.
RouterProfile = Literal["cloud", "local"]


def _parse_kid_list(raw: str | None) -> tuple[tuple[str, str], ...]:
    """Parse a ``kid:secret,kid:secret`` env list into an ordered tuple.

    Used for ``SHIELD_SESSION_SECRETS``, ``SHIELD_PASSWORD_PEPPERS``,
    ``SHIELD_AUTH_FERNET_KEYS``. Empty / None → ``()``. First entry is the
    active key (encryption/signing); the rest accept decrypt / re-hash for
    lazy rotation (§A6 MultiFernet pattern). Raises ``ValueError`` on
    malformed input (no ``:`` separator, empty kid/secret, duplicate kid) so
    a misconfigured deployment fails loudly at startup.
    """
    if not raw:
        return ()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_entry in raw.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"kid-list entry must be 'kid:secret'; got {entry!r}. "
                "Generate via `infra/secrets/gen.py {session,pepper,fernet}` and "
                "format as 'k1:<material>,k2:<material>'."
            )
        kid, secret = entry.split(":", 1)
        kid = kid.strip()
        secret = secret.strip()
        if not kid or not secret:
            raise ValueError(f"kid-list entry has empty kid or secret: {entry!r}")
        if kid in seen:
            raise ValueError(f"duplicate kid {kid!r} in kid-list")
        seen.add(kid)
        pairs.append((kid, secret))
    return tuple(pairs)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; got {raw!r}") from exc


def _validate_argon2_caps(memory_kib: int, time_cost: int, parallelism: int) -> None:
    """§A1 fail-loud-startup: raise if any env value exceeds the hardcoded cap."""
    if memory_kib > ARGON2_MEMORY_KIB_CAP:
        raise RuntimeError(
            f"SHIELD_ARGON2_MEMORY_COST_KIB={memory_kib} exceeds §A1 hardcoded "
            f"cap {ARGON2_MEMORY_KIB_CAP} (256 MiB per-hash memory budget). "
            "Caps are NOT env-tunable; misconfiguration is a startup error, "
            "not a per-request DoS."
        )
    if time_cost > ARGON2_TIME_COST_CAP:
        raise RuntimeError(
            f"SHIELD_ARGON2_TIME_COST={time_cost} exceeds §A1 hardcoded cap {ARGON2_TIME_COST_CAP}."
        )
    if parallelism > ARGON2_PARALLELISM_CAP:
        raise RuntimeError(
            f"SHIELD_ARGON2_PARALLELISM={parallelism} exceeds §A1 hardcoded "
            f"cap {ARGON2_PARALLELISM_CAP}."
        )
    if memory_kib <= 0 or time_cost <= 0 or parallelism <= 0:
        raise RuntimeError(
            "argon2id parameters must be positive integers: "
            f"memory_kib={memory_kib} time_cost={time_cost} parallelism={parallelism}"
        )


def _resolve_auth_mode() -> AuthMode:
    """Resolve effective AuthMode from env.

    Precedence: ``SHIELD_AUTH_MODE`` (§A2 single source of truth) over the
    legacy W3 ``SHIELD_DEV_AUTH`` heuristic. If neither is set, defaults to
    ``open`` (preserves W3 314-test default behaviour byte-identically).
    """
    explicit = os.environ.get("SHIELD_AUTH_MODE")
    if explicit:
        m = explicit.strip().lower()
        if m not in ("open", "enterprise", "api_token_only"):
            raise RuntimeError(
                f"SHIELD_AUTH_MODE must be one of open|enterprise|api_token_only; got {explicit!r}"
            )
        return m  # type: ignore[return-value]
    if os.environ.get("SHIELD_DEV_AUTH", "open").lower() == "open":
        return "open"
    return "api_token_only"


@dataclass(frozen=True, slots=True)
class Settings:
    # --- W3 baseline (byte-identical) ---
    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_bucket: str
    server_signing_key: str
    api_token: str | None
    cors_origins: tuple[str, ...]
    dev_auth_open: bool

    # --- ADR-0013 additive (all defaulted; back-compat under `open`) ---
    auth_mode: AuthMode = "open"
    allow_open_auth: bool = False
    session_secrets: tuple[tuple[str, str], ...] = ()
    password_peppers: tuple[tuple[str, str], ...] = ()
    fernet_keys: tuple[tuple[str, str], ...] = ()
    argon2_memory_kib: int = ARGON2_MEMORY_KIB_DEFAULT
    argon2_time_cost: int = ARGON2_TIME_COST_DEFAULT
    argon2_parallelism: int = ARGON2_PARALLELISM_DEFAULT
    email_backend: EmailBackend = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@shield.local"
    email_file_dir: str = "var/mailbox"
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_name: str = DEFAULT_COOKIE_NAME
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    ratelimit_redis_url: str | None = None
    public_base_url: str = "http://localhost:3000"

    # M2 / Phase A — governance router profile (cloud or local/air-gapped).
    # Selects which ``models.<profile>.yaml`` the async verdict worker hands to
    # the router-backed guardians. ``cloud`` matches the existing W3 demo path.
    router_profile: RouterProfile = "cloud"

    @property
    def is_enterprise(self) -> bool:
        return self.auth_mode == "enterprise"

    @property
    def is_open(self) -> bool:
        return self.auth_mode == "open"

    @property
    def is_api_token_only(self) -> bool:
        return self.auth_mode == "api_token_only"

    @property
    def active_session_secret(self) -> tuple[str, str] | None:
        return self.session_secrets[0] if self.session_secrets else None

    @property
    def active_pepper(self) -> tuple[str, str] | None:
        return self.password_peppers[0] if self.password_peppers else None

    @property
    def active_fernet_key(self) -> tuple[str, str] | None:
        return self.fernet_keys[0] if self.fernet_keys else None

    @staticmethod
    def from_env() -> Settings:
        origins = os.environ.get("SHIELD_CORS_ORIGINS", "http://localhost:3000")
        mode = _resolve_auth_mode()

        argon2_memory_kib = _env_int("SHIELD_ARGON2_MEMORY_COST_KIB", ARGON2_MEMORY_KIB_DEFAULT)
        argon2_time_cost = _env_int("SHIELD_ARGON2_TIME_COST", ARGON2_TIME_COST_DEFAULT)
        argon2_parallelism = _env_int("SHIELD_ARGON2_PARALLELISM", ARGON2_PARALLELISM_DEFAULT)
        _validate_argon2_caps(argon2_memory_kib, argon2_time_cost, argon2_parallelism)

        email_backend_raw = os.environ.get("SHIELD_EMAIL_BACKEND", "console").lower()
        if email_backend_raw not in ("console", "file", "smtp"):
            raise RuntimeError(
                f"SHIELD_EMAIL_BACKEND must be one of console|file|smtp; got {email_backend_raw!r}"
            )
        email_backend: EmailBackend = email_backend_raw  # type: ignore[assignment]

        router_profile_raw = os.environ.get("SHIELD_ROUTER_PROFILE", "cloud").lower()
        if router_profile_raw not in ("cloud", "local"):
            raise RuntimeError(
                f"SHIELD_ROUTER_PROFILE must be one of cloud|local; got {router_profile_raw!r}"
            )
        router_profile: RouterProfile = router_profile_raw  # type: ignore[assignment]

        # Cookie Secure attribute defaults True in enterprise mode (HTTPS-only
        # cookies); local-dev override via SHIELD_ALLOW_INSECURE_COOKIES=1.
        cookie_secure_default = (mode == "enterprise") and (
            os.environ.get("SHIELD_ALLOW_INSECURE_COOKIES", "0") != "1"
        )
        cookie_secure_env = os.environ.get("SHIELD_COOKIE_SECURE", "").lower()
        cookie_secure = (
            cookie_secure_env.startswith(("1", "t", "y"))
            if cookie_secure_env
            else cookie_secure_default
        )

        return Settings(
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://shield:shield@localhost:5432/shield"
            ),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
            minio_access_key=os.environ.get("MINIO_ROOT_USER", "shield"),
            minio_secret_key=os.environ.get("MINIO_ROOT_PASSWORD", "shieldsecret"),
            minio_secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
            minio_bucket=os.environ.get("MINIO_BUCKET", "shield-evidence"),
            # base64url 32-byte Ed25519 seed for EAR signing. A fixed dev seed by
            # default (zeros) so the demo runs key-less; production injects a real
            # secret. Real signing is gated on shield_sdk.crypto (Task #2).
            server_signing_key=os.environ.get("SHIELD_SERVER_SIGNING_KEY", "A" * 43),
            api_token=os.environ.get("SHIELD_API_TOKEN") or None,
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            dev_auth_open=mode == "open",
            # --- ADR-0013 additive ---
            auth_mode=mode,
            allow_open_auth=False,  # CLI-only (§A3); app entrypoint flips after argparse
            session_secrets=_parse_kid_list(os.environ.get("SHIELD_SESSION_SECRETS")),
            password_peppers=_parse_kid_list(os.environ.get("SHIELD_PASSWORD_PEPPERS")),
            fernet_keys=_parse_kid_list(os.environ.get("SHIELD_AUTH_FERNET_KEYS")),
            argon2_memory_kib=argon2_memory_kib,
            argon2_time_cost=argon2_time_cost,
            argon2_parallelism=argon2_parallelism,
            email_backend=email_backend,
            smtp_host=os.environ.get("SMTP_HOST", "localhost"),
            smtp_port=_env_int("SMTP_PORT", 1025),
            smtp_user=os.environ.get("SMTP_USER") or None,
            smtp_password=os.environ.get("SMTP_PASSWORD") or None,
            smtp_from=os.environ.get("SMTP_FROM", "no-reply@shield.local"),
            email_file_dir=os.environ.get("SHIELD_EMAIL_FILE_DIR", "var/mailbox"),
            cookie_secure=cookie_secure,
            cookie_domain=os.environ.get("SHIELD_COOKIE_DOMAIN") or None,
            cookie_name=os.environ.get("SHIELD_COOKIE_NAME", DEFAULT_COOKIE_NAME),
            session_ttl_seconds=_env_int("SHIELD_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS),
            ratelimit_redis_url=os.environ.get("SHIELD_RATELIMIT_REDIS_URL") or None,
            public_base_url=os.environ.get("SHIELD_PUBLIC_BASE_URL", "http://localhost:3000"),
            router_profile=router_profile,
        )

    def with_allow_open_auth(self, allow: bool) -> Settings:
        """Return a new Settings with the CLI ``--allow-open-auth`` flag set.

        The flag is intentionally CLI-only (§A3); the env path leaves it False
        and the app entrypoint flips it on after argparse. Frozen dataclasses
        are immutable so we replace via copy.
        """
        from dataclasses import replace

        return replace(self, allow_open_auth=allow)
