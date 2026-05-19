"""Poll Postgres / Redis / MinIO until healthy or a ~60 s budget expires.

Referenced by the `Makefile` `integration` target and `cicd.md` §3
`integration.yml` ("Wait for health" step: `uv run python infra/wait_for_health.py`).
Stdlib only (no extra deps; mypy/ruff clean): TCP reachability for Postgres,
a real RESP `PING` for Redis, and the HTTP liveness endpoint for MinIO.

Exit 0 once all three are ready; exit 1 if the budget expires.
"""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.error
import urllib.request

BUDGET_S = 60.0
INTERVAL_S = 2.0

PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = int(os.environ.get("MINIO_PORT", "9000"))


def _tcp_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _redis_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"PING\r\n")
            return b"PONG" in sock.recv(64)
    except OSError:
        return False


def _minio_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    url = f"http://{host}:{port}/minio/health/live"
    try:
        # Fixed localhost health URL (not user input).
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    checks = {
        "postgres": lambda: _tcp_ok(PG_HOST, PG_PORT),
        "redis": lambda: _redis_ok(REDIS_HOST, REDIS_PORT),
        "minio": lambda: _minio_ok(MINIO_HOST, MINIO_PORT),
    }
    deadline = time.monotonic() + BUDGET_S
    pending = set(checks)
    while time.monotonic() < deadline:
        for name in sorted(pending):
            if checks[name]():
                print(f"wait_for_health: {name} ready")
                pending.discard(name)
        if not pending:
            print("wait_for_health: all services ready")
            return 0
        time.sleep(INTERVAL_S)
    print(f"wait_for_health: TIMEOUT after {BUDGET_S:.0f}s; not ready: {sorted(pending)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
