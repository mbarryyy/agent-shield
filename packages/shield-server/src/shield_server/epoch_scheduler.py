"""Background epoch generation for Merkle/EER audit evidence.

The scheduler is deliberately narrow: one run builds at most one deterministic
epoch for an org from stored operations and persists the matching signed EER.
Read routes keep their on-demand fallback for older/local deployments where no
background scheduler has populated the epochs table yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Literal

from .config import DEMO_ORG_ID, Settings
from .merkle import epoch_artifact_bytes, epoch_from_operation_rows, sign_eer
from .models import EER, Epoch
from .storage import Storage, build_storage

EpochSchedulerStatus = Literal["created", "already_persisted", "skipped_empty"]


@dataclass(frozen=True, slots=True)
class EpochSchedulerResult:
    status: EpochSchedulerStatus
    org_id: str
    epoch: Epoch | None = None
    eer: EER | None = None
    reason: str | None = None


def _result_dict(result: EpochSchedulerResult) -> dict[str, object]:
    return {
        "status": result.status,
        "org_id": result.org_id,
        "reason": result.reason,
        "epoch": None if result.epoch is None else result.epoch.model_dump(mode="json"),
        "eer": None if result.eer is None else result.eer.model_dump(mode="json"),
    }


async def _persisted_epoch(storage: Storage, org_id: str, epoch_id: str) -> Epoch | None:
    rows = await storage.db.fetch("SELECT * FROM epochs")
    matches = [Epoch.model_validate(row) for row in rows if row.get("org_id") == org_id]
    for epoch in matches:
        if epoch.epoch_id == epoch_id:
            return epoch
    return None


async def _persisted_eer(storage: Storage, epoch: Epoch) -> EER | None:
    raw = await storage.objects.get(epoch.r2_epoch_key)
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("eer"), dict):
        return None
    eer = EER.model_validate(obj["eer"])
    if eer.epoch_id != epoch.epoch_id or eer.org_id != epoch.org_id:
        return None
    return eer


async def run_epoch_once(storage: Storage, org_id: str, signing_key: str) -> EpochSchedulerResult:
    rows = await storage.db.fetch("SELECT * FROM operations")
    epoch = epoch_from_operation_rows(org_id, rows)
    if epoch is None:
        return EpochSchedulerResult(
            status="skipped_empty",
            org_id=org_id,
            reason="no_operations",
        )

    persisted = await _persisted_epoch(storage, org_id, epoch.epoch_id)
    if persisted is not None:
        return EpochSchedulerResult(
            status="already_persisted",
            org_id=org_id,
            epoch=persisted,
            eer=await _persisted_eer(storage, persisted),
            reason="epoch_id_exists",
        )

    eer = sign_eer(epoch, signing_key)
    await storage.objects.put(
        epoch.r2_epoch_key,
        epoch_artifact_bytes(epoch, eer),
        "application/json",
    )
    await storage.db.execute(
        "INSERT INTO epochs (epoch_id, org_id, start_time, end_time, root_hash, "
        "leaf_count, r2_epoch_key, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        epoch.epoch_id,
        epoch.org_id,
        epoch.start_time,
        epoch.end_time,
        epoch.root_hash,
        epoch.leaf_count,
        epoch.r2_epoch_key,
        epoch.created_at,
    )
    return EpochSchedulerResult(status="created", org_id=org_id, epoch=epoch, eer=eer)


async def run_epoch_interval(
    storage: Storage,
    org_id: str,
    signing_key: str,
    *,
    interval_seconds: float,
    max_runs: int | None = None,
) -> list[EpochSchedulerResult]:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if max_runs is not None and max_runs <= 0:
        raise ValueError("max_runs must be positive when provided")

    results: list[EpochSchedulerResult] = []
    runs = 0
    while max_runs is None or runs < max_runs:
        results.append(await run_epoch_once(storage, org_id, signing_key))
        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        await asyncio.sleep(interval_seconds)
    return results


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate persisted Agent Shield epochs.")
    parser.add_argument("--org-id", default=DEMO_ORG_ID)
    parser.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    parser.add_argument("--interval-seconds", type=float, default=None)
    parser.add_argument("--max-runs", type=int, default=None)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    storage = await build_storage(settings)
    if args.once or args.interval_seconds is None:
        result = await run_epoch_once(storage, args.org_id, settings.server_signing_key)
        print(json.dumps(_result_dict(result), sort_keys=True), flush=True)
        return 0

    results = await run_epoch_interval(
        storage,
        args.org_id,
        settings.server_signing_key,
        interval_seconds=args.interval_seconds,
        max_runs=args.max_runs,
    )
    for result in results:
        print(json.dumps(_result_dict(result), sort_keys=True), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
