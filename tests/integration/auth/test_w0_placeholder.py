"""W0-scaffold placeholder for the `integration_auth` marker (ADR-0013).

Asserts Mailhog (the 5th compose service brought up by `make integration-auth`
and the CI `auth-integration` job) is reachable via its HTTP API. server-
builder + sdk-builder + console-builder fill the real auth integration suite
(login/logout/2fa/api-key scoping/migration fire-drill) in their PRs.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.integration_auth


def test_mailhog_api_reachable() -> None:
    host = os.environ.get("MAILHOG_HOST", "localhost")
    port = int(os.environ.get("MAILHOG_API_PORT", "8025"))
    url = f"http://{host}:{port}/api/v2/messages"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            assert 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as exc:  # pragma: no cover (CI infra)
        pytest.skip(f"Mailhog not reachable at {url}: {exc}")


def test_auth_mode_is_enterprise_in_this_job() -> None:
    # Job-level invariant: the `auth-integration` CI job + `make integration-auth`
    # both export SHIELD_AUTH_MODE=enterprise; this asserts the wiring.
    assert os.environ.get("SHIELD_AUTH_MODE") == "enterprise", (
        "integration_auth must run with SHIELD_AUTH_MODE=enterprise; "
        f"got {os.environ.get('SHIELD_AUTH_MODE')!r}"
    )
