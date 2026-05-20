"""Binary Merkle (sorted leaves, odd-dup, SHA-256(rawL||rawR)) — REWRITE of
Elydora packages/server/src/utils/merkle.ts. W0 STUB -> W4 server-builder."""

from __future__ import annotations

import hashlib


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return hashlib.sha256(b"").digest()
    level = sorted(bytes(leaf) for leaf in leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)
        ]
    return level[0]
