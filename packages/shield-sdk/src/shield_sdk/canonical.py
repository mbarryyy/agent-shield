"""The FROZEN §4 signable-field projection (W1 freeze — server-builder depends).

This module is the single, frozen definition of *which bytes get signed and
hashed* for a ``ShieldActionRecord`` / ``GovernanceVerdict``. shield-server's
12-step ingest MUST reproduce these bytes exactly (it imports this module — it
never re-derives the rule), or every chain breaks. The byte-exact JCS / SHA-256
/ Ed25519 primitives live in ``shield_sdk.crypto`` (verbatim Elydora port);
this module is the thin, frozen §4 application layer on top.

================================================================================
FROZEN RULE (the explicit present-null-vs-omit freeze team-lead asked for)
================================================================================

1.  The signable form of a model is::

        model.model_dump(mode="json", exclude_none=True)   # then drop unsigned keys

    fed to ``crypto.jcs_canonicalize`` and UTF-8 encoded.

2.  PRESENT-NULL ≡ ABSENT ≡ OMITTED. ``exclude_none=True`` is applied
    recursively at every level, so a field that is ``None`` *or* unset is
    **omitted** from the signed/hashed bytes — never serialized as JSON
    ``null``. The signature is therefore stable whether an optional field is
    explicitly ``None`` or simply not provided. (The Elydora JCS port itself
    *does* emit present-null keys; we strip ``None`` *before* canonicalization
    so the two can never diverge. The port's null-emitting behavior is still
    verified byte-exact against Elydora via the golden vectors, which feed
    null-bearing dicts straight into ``jcs_canonicalize``.)

3.  Empty containers are NOT dropped: ``{}`` / ``[]`` are present, non-None
    values and appear in the canonical form (deterministic, server-reproducible).

4.  ``mode="json"`` ⇒ enums serialize to their string values, ints stay ints,
    nested models become plain dicts — exactly what crosses the wire and what
    the ``contracts/*.schema.json`` snapshot validates.

5.  Excluded-from-signature keys (dropped AFTER the dump, unconditionally, even
    if non-None — because the server legitimately sets them):
      * ``ShieldActionRecord``: ``signature`` (cannot sign itself) and
        ``chain_hash`` (server-derived, never signed/trusted from the client —
        §4 line 49/120; dropped explicitly so the client signature stays valid
        after the server attaches the derived ``chain_hash``).
      * ``GovernanceVerdict``: ``signature_by_shield`` only.

6.  ``payload_hash`` = base64url(SHA-256(JCS(payload-subobject))) where the
    payload sub-object is dumped with the same rule (2)+(3)+(4). It is a
    signed field of the record.

7.  ``chain_hash`` = SHA-256(prev | payload_hash | record_id | issued_at),
    server-derived only. ``record_id`` is the §4 ``operation_id``;
    ``issued_at`` is the unix-epoch-ms integer.
"""

from __future__ import annotations

from typing import Any

from . import crypto
from .schema import GovernanceVerdict, ShieldActionRecord

RECORD_UNSIGNED: tuple[str, ...] = ("signature", "chain_hash")
VERDICT_UNSIGNED: tuple[str, ...] = ("signature_by_shield",)


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #


def _signable_dict(
    model: ShieldActionRecord | GovernanceVerdict, drop: tuple[str, ...]
) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json", exclude_none=True)
    for key in drop:
        data.pop(key, None)
    return data


def record_signable_dict(record: ShieldActionRecord) -> dict[str, Any]:
    """The exact dict that gets JCS-canonicalized and signed for a record."""
    return _signable_dict(record, RECORD_UNSIGNED)


def verdict_signable_dict(verdict: GovernanceVerdict) -> dict[str, Any]:
    """The exact dict that gets JCS-canonicalized and signed for a verdict."""
    return _signable_dict(verdict, VERDICT_UNSIGNED)


def record_signing_string(record: ShieldActionRecord) -> str:
    """The exact JCS canonical string that is Ed25519-signed for a record."""
    return crypto.jcs_canonicalize(record_signable_dict(record))


def verdict_signing_string(verdict: GovernanceVerdict) -> str:
    """The exact JCS canonical string that is Ed25519-signed for a verdict."""
    return crypto.jcs_canonicalize(verdict_signable_dict(verdict))


# --------------------------------------------------------------------------- #
# Payload hash & chain hash
# --------------------------------------------------------------------------- #


def compute_record_payload_hash(record: ShieldActionRecord) -> str:
    """base64url(SHA-256(JCS(payload sub-object))) — a signed field (§4)."""
    payload = record.payload.model_dump(mode="json", exclude_none=True)
    return crypto.compute_payload_hash(payload)


def derive_chain_hash(prev_chain_hash: str, record: ShieldActionRecord) -> str:
    """Server-side chain-hash derivation (SDK exposes it for parity tests).

    SHA-256(prev | payload_hash | record_id | issued_at). ``record_id`` is the
    §4 ``operation_id``; ``issued_at`` is the unix-epoch-ms integer.
    """
    return crypto.compute_chain_hash(
        prev_chain_hash,
        record.payload_hash,
        record.record_id,
        record.issued_at,
    )


# --------------------------------------------------------------------------- #
# Sign / verify (records use the agent key; verdicts the shield-server key)
# --------------------------------------------------------------------------- #


def sign_record(record: ShieldActionRecord, private_key_base64url: str) -> str:
    """Ed25519 signature over ``record_signing_string(record)``."""
    return crypto.sign_ed25519(private_key_base64url, record_signing_string(record).encode("utf-8"))


def verify_record(record: ShieldActionRecord, public_key_base64url: str) -> bool:
    """True iff ``record.signature`` is a valid Ed25519 sig over the record."""
    if record.signature is None:
        return False
    return crypto.verify_ed25519(
        public_key_base64url,
        record_signing_string(record).encode("utf-8"),
        record.signature,
    )


def verify_ingest(record: ShieldActionRecord, public_key_base64url: str) -> bool:
    """Server-side single ingest call-site — a PURE pass-through to
    ``verify_record`` (W3 U3 / HG#1 byte-parity).

    This function adds ZERO independent verification logic: it returns exactly
    ``verify_record(record, public_key_base64url)``. shield-server's real
    ``/v1/governance/decide`` (and ``/v1/governance/record``) 12-step ingest
    can call this single name and is byte-identical to the SDK's own signature
    check by construction — there is no second implementation to drift. The
    contract test ``test_verify_ingest_is_pure_passthrough`` pins
    ``verify_ingest`` ≡ ``verify_record`` over the golden vectors + property
    inputs; if that equivalence ever cannot be guaranteed this wrapper must be
    removed and the server must call ``verify_record`` directly.
    """
    return verify_record(record, public_key_base64url)


def sign_verdict(verdict: GovernanceVerdict, private_key_base64url: str) -> str:
    """Ed25519 signature over ``verdict_signing_string(verdict)``."""
    return crypto.sign_ed25519(
        private_key_base64url, verdict_signing_string(verdict).encode("utf-8")
    )


def verify_verdict(verdict: GovernanceVerdict, public_key_base64url: str) -> bool:
    """True iff ``verdict.signature_by_shield`` is a valid Ed25519 sig."""
    if verdict.signature_by_shield is None:
        return False
    return crypto.verify_ed25519(
        public_key_base64url,
        verdict_signing_string(verdict).encode("utf-8"),
        verdict.signature_by_shield,
    )


# --------------------------------------------------------------------------- #
# Finalizers — assemble payload_hash then signature (the SDK build path)
# --------------------------------------------------------------------------- #


def finalize_record(record: ShieldActionRecord, private_key_base64url: str) -> ShieldActionRecord:
    """Return a copy with ``payload_hash`` computed and ``signature`` set.

    ``chain_hash`` is intentionally left ``None`` — it is server-derived.
    """
    finalized = record.model_copy(deep=True)
    finalized.payload_hash = compute_record_payload_hash(finalized)
    finalized.signature = sign_record(finalized, private_key_base64url)
    return finalized


def finalize_verdict(verdict: GovernanceVerdict, private_key_base64url: str) -> GovernanceVerdict:
    """Return a copy with ``signature_by_shield`` set (shield-server key)."""
    finalized = verdict.model_copy(deep=True)
    finalized.signature_by_shield = sign_verdict(finalized, private_key_base64url)
    return finalized
