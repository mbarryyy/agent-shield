"""Binary Merkle (sorted leaves, odd-dup, SHA-256(rawL||rawR)) — REWRITE of
Elydora packages/server/src/utils/merkle.ts. W0 STUB -> W4 server-builder."""

from __future__ import annotations


def merkle_root(leaves: list[bytes]) -> bytes:
    raise NotImplementedError("W4: binary Merkle root")  # pragma: no cover
