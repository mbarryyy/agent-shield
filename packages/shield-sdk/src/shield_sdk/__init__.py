"""Agent Shield Layer-1 Free SDK.

``shield_sdk.schema`` is the single FROZEN §4 source of truth — server,
governance, eval and the console contract tests import it and never re-declare
it. W1 freezes it at ``shield_version`` 1.1 (C11 / ADR-0007).

  * ``shield_sdk.crypto``    — byte-exact Elydora JCS/SHA-256/Ed25519 port
  * ``shield_sdk.canonical`` — the frozen §4 signable-field projection
  * ``shield_sdk.schema``    — the frozen §4 pydantic models (v1.1)
"""

from . import canonical, crypto, schema

__all__ = ["canonical", "crypto", "schema"]
