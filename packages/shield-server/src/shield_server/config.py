"""Server configuration (env-driven). Defaults match infra/docker-compose.yml.

Single-tenant prototype: Better-Auth + 5-role RBAC is DISCARDED per
sdk_layer_design.md §1.4/§2 — a permissive demo-org context is the default so
the Elydora console boots unchanged against this FastAPI backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class Settings:
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

    @staticmethod
    def from_env() -> Settings:
        origins = os.environ.get("SHIELD_CORS_ORIGINS", "http://localhost:3000")
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
            dev_auth_open=os.environ.get("SHIELD_DEV_AUTH", "open").lower() == "open",
        )
