#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SHIELD_PREFLIGHT_ENV_FILE:-$ROOT_DIR/.env}"
MIN_FREE_KIB="${SHIELD_PREFLIGHT_MIN_FREE_KIB:-5242880}"

FAILURES=0
SKIPS=0

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf '[FAIL] %s\n' "$1"
}

skip() {
  SKIPS=$((SKIPS + 1))
  printf '[SKIP] %s\n' "$1"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

check_command() {
  local name="$1"
  local version_arg="${2:---version}"

  if ! have "$name"; then
    fail "$name missing"
    return
  fi

  local version
  version="$("$name" "$version_arg" 2>/dev/null | head -n 1 || true)"
  if [ -n "$version" ]; then
    pass "$name available: $version"
  else
    pass "$name available"
  fi
}

check_os_arch() {
  local os arch
  os="$(uname -s 2>/dev/null || true)"
  arch="$(uname -m 2>/dev/null || true)"

  if [ -n "$os" ] && [ -n "$arch" ]; then
    pass "host platform: $os/$arch"
  else
    fail "unable to detect host platform"
  fi
}

check_docker() {
  if ! have docker; then
    fail "docker missing"
    return
  fi

  pass "docker CLI available: $(docker --version 2>/dev/null | head -n 1)"

  if docker info >/dev/null 2>&1; then
    pass "docker daemon reachable"
  else
    fail "docker daemon unreachable"
  fi

  if docker compose version >/dev/null 2>&1; then
    pass "docker compose available: $(docker compose version 2>/dev/null | head -n 1)"
  else
    fail "docker compose missing"
  fi
}

check_disk() {
  local available
  available="$(df -Pk "$ROOT_DIR" 2>/dev/null | awk 'NR == 2 {print $4}')"

  if [ -z "$available" ]; then
    fail "unable to check free disk space"
    return
  fi

  if [ "$available" -ge "$MIN_FREE_KIB" ]; then
    pass "free disk space >= ${MIN_FREE_KIB} KiB"
  else
    fail "free disk space below ${MIN_FREE_KIB} KiB"
  fi
}

check_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    fail ".env missing at $ENV_FILE"
    return
  fi

  pass ".env file exists"

  if grep -Eq '^[[:space:]]*ANTHROPIC_API_KEY[[:space:]]*=' "$ENV_FILE"; then
    pass ".env contains ANTHROPIC_API_KEY key name (value redacted)"
  else
    fail ".env missing ANTHROPIC_API_KEY key name"
  fi
}

check_egress_capability() {
  local os
  os="$(uname -s 2>/dev/null || true)"

  if [ "$os" = "Darwin" ]; then
    skip "SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin"
    return
  fi

  if [ "$os" != "Linux" ]; then
    skip "SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on $os"
    return
  fi

  if have unshare && have ip; then
    pass "egress-deny smoke capability available"
  else
    skip "SKIP_HOST_UNSUPPORTED: egress-deny smoke requires unshare and ip"
  fi
}

check_tcp() {
  local label="$1"
  local host="$2"
  local port="$3"

  if have nc; then
    if nc -z "$host" "$port" >/dev/null 2>&1; then
      pass "$label reachable at $host:$port"
    else
      fail "$label unreachable at $host:$port"
    fi
    return
  fi

  if have python3; then
    if python3 -c 'import socket, sys; s=socket.create_connection((sys.argv[1], int(sys.argv[2])), 2); s.close()' "$host" "$port" >/dev/null 2>&1; then
      pass "$label reachable at $host:$port"
    else
      fail "$label unreachable at $host:$port"
    fi
    return
  fi

  skip "$label reachability needs nc or python3"
}

check_service_reachability() {
  if [ "${SHIELD_PREFLIGHT_SKIP_SERVICE_REACHABILITY:-0}" = "1" ]; then
    skip "service reachability checks disabled by SHIELD_PREFLIGHT_SKIP_SERVICE_REACHABILITY"
    return
  fi

  if [ "${SHIELD_PREFLIGHT_CHECK_INFRA:-0}" != "1" ]; then
    skip "service reachability not requested; set SHIELD_PREFLIGHT_CHECK_INFRA=1"
    return
  fi

  check_tcp "Postgres" "127.0.0.1" "5432"
  check_tcp "Redis" "127.0.0.1" "6379"
  check_tcp "MinIO" "127.0.0.1" "9000"
  check_tcp "ChromaDB" "127.0.0.1" "8000"
}

main() {
  printf 'Agent Shield preflight\n'
  check_os_arch
  check_command python3
  check_command uv
  check_command node
  check_command npm
  check_docker
  check_disk
  check_env_file
  check_egress_capability
  check_service_reachability

  if [ "$FAILURES" -eq 0 ]; then
    printf 'GO: preflight passed with %s skip(s)\n' "$SKIPS"
    return 0
  fi

  printf 'NO-GO: preflight failed with %s failure(s) and %s skip(s)\n' "$FAILURES" "$SKIPS"
  return 1
}

main "$@"
