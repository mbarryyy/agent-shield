"""Binary Merkle (sorted leaves, odd-dup, SHA-256(rawL||rawR)) — REWRITE of
Elydora packages/server/src/utils/merkle.ts. W0 STUB -> W4 server-builder."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

import shield_sdk.crypto as sdk_crypto

from .models import EER, Epoch

HASH_ALG = "sha256-binary-merkle-v1"


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return hashlib.sha256(b"").digest()
    level = sorted(bytes(leaf) for leaf in leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0]


def _i(x: object) -> int:
    return int(cast(Any, x))


def leaf_bytes(chain_hash: object) -> bytes:
    value = str(chain_hash)
    try:
        return sdk_crypto.base64url_decode(value)
    except Exception:
        return value.encode("utf-8")


def epoch_id(org_id: str, start: int, end: int, root_hash: str, leaf_count: int) -> str:
    seed = f"{org_id}|{start}|{end}|{root_hash}|{leaf_count}"
    return "epoch_" + sdk_crypto.sha256_base64url(seed)


def epoch_from_operation_rows(org_id: str, rows: Sequence[Mapping[str, object]]) -> Epoch | None:
    scoped = [row for row in rows if row.get("org_id") == org_id]
    if not scoped:
        return None
    scoped.sort(key=lambda r: (_i(r["created_at"]), str(r["operation_id"])))
    start = _i(scoped[0]["created_at"])
    end = _i(scoped[-1]["created_at"])
    leaves = [leaf_bytes(row["chain_hash"]) for row in scoped]
    root_hash = sdk_crypto.base64url_encode(merkle_root(leaves))
    leaf_count = len(leaves)
    eid = epoch_id(org_id, start, end, root_hash, leaf_count)
    return Epoch(
        epoch_id=eid,
        org_id=org_id,
        start_time=start,
        end_time=end,
        root_hash=root_hash,
        leaf_count=leaf_count,
        r2_epoch_key=f"{org_id}/epochs/{eid}.json",
        created_at=end,
    )


def eer_signable(eer: EER) -> bytes:
    body = eer.model_dump(mode="json", exclude={"signature_by_elydora"})
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_eer(epoch: Epoch, signing_key: str) -> EER:
    eer = EER(
        epoch_id=epoch.epoch_id,
        org_id=epoch.org_id,
        start_time=epoch.start_time,
        end_time=epoch.end_time,
        leaf_count=epoch.leaf_count,
        root_hash=epoch.root_hash,
        hash_alg=HASH_ALG,
        signature_by_elydora="",
    )
    eer.signature_by_elydora = sdk_crypto.sign_ed25519(signing_key, eer_signable(eer))
    return eer


def epoch_artifact_bytes(epoch: Epoch, eer: EER) -> bytes:
    return json.dumps(
        {"epoch": epoch.model_dump(mode="json"), "eer": eer.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
