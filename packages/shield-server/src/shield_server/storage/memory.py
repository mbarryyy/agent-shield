"""In-memory storage fakes.

A shipped module (not test-only) so the unit suite exercises the *real* 12-step
ingest / audit / agent logic against it and `--cov=packages` counts that
coverage without docker. The asyncpg/MinIO/Redis adapters run the identical
logic against real infra in the integration job.

`MemoryDatabase` is a deliberately tiny SQL-ish executor: it understands only
the fixed statement shapes the ingest/audit/agent services issue (faithful
ports of Elydora's queries), not arbitrary SQL.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class MemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        self._objects[key] = body

    async def get(self, key: str) -> bytes | None:
        return self._objects.get(key)


class MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: set[tuple[str, str]] = set()

    def _live(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires < time.time():
            del self._store[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        if self._live(key) is not None:
            return False
        self._store[key] = (value, time.time() + ttl_seconds)
        return True

    async def set(self, key: str, value: str) -> None:
        self._store[key] = (value, None)

    async def ensure_group(self, stream: str, group: str) -> None:
        self.streams.setdefault(stream, [])
        self.groups.add((stream, group))

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        entries = self.streams.setdefault(stream, [])
        msg_id = f"{len(entries) + 1}-0"
        entries.append((msg_id, dict(fields)))
        return msg_id

    async def xrange(
        self, stream: str, *, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        entries = [(mid, dict(f)) for mid, f in self.streams.get(stream, [])]
        return entries if count is None else entries[:count]


class _MemoryTx:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db
        self._ops: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *args: object) -> None:
        self._ops.append((sql, args))

    async def _commit(self) -> None:
        for sql, args in self._ops:
            await self._db.execute(sql, *args)


class MemoryDatabase:
    """Recognises only the fixed Elydora-ported statement shapes."""

    def __init__(self) -> None:
        self.agents: dict[str, dict[str, Any]] = {}
        self.agent_keys: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, dict[str, Any]] = {}
        self.intervention_log: list[dict[str, Any]] = []
        self.governance_verdicts: dict[str, dict[str, Any]] = {}

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        s = " ".join(sql.split())
        if s.startswith("SELECT * FROM agents WHERE agent_id"):
            row = self.agents.get(str(args[0]))
            return None if row is None else (dict(row) if row["org_id"] == args[1] else None)
        if s.startswith("SELECT * FROM agent_keys WHERE kid"):
            row = self.agent_keys.get(str(args[0]))
            return None if row is None else (dict(row) if row["agent_id"] == args[1] else None)
        if s.startswith("SELECT chain_hash, seq_no FROM operations WHERE agent_id"):
            owned = [o for o in self.operations.values() if o["agent_id"] == args[0]]
            if not owned:
                return None
            top = max(owned, key=lambda o: int(o["seq_no"]))
            return {"chain_hash": top["chain_hash"], "seq_no": top["seq_no"]}
        if s.startswith("SELECT chain_hash FROM operations WHERE agent_id"):
            for o in self.operations.values():
                if o["agent_id"] == args[0] and str(o["seq_no"]) == str(args[1]):
                    return {"chain_hash": o["chain_hash"]}
            return None
        if s.startswith("SELECT * FROM operations WHERE operation_id"):
            row = self.operations.get(str(args[0]))
            return None if row is None else (dict(row) if row["org_id"] == args[1] else None)
        if s.startswith("SELECT * FROM receipts WHERE operation_id"):
            for r in self.receipts.values():
                if r["operation_id"] == args[0]:
                    return dict(r)
            return None
        raise AssertionError(f"MemoryDatabase: unmodelled fetchrow: {s}")

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        # Only used by audit.query_audit, which sorts/filters in Python.
        if "FROM governance_verdicts" in sql:
            return [dict(v) for v in self.governance_verdicts.values()]
        if "FROM intervention_log" in sql:
            return [dict(r) for r in self.intervention_log]
        if "FROM operations" in sql:
            return [dict(o) for o in self.operations.values()]
        if "FROM agent_keys" in sql:
            return [dict(k) for k in self.agent_keys.values() if k["agent_id"] == args[0]]
        if "FROM agents" in sql:
            return [dict(a) for a in self.agents.values()]
        raise AssertionError(f"MemoryDatabase: unmodelled fetch: {sql}")  # pragma: no cover

    async def fetchval(self, sql: str, *args: object) -> object:
        raise AssertionError("MemoryDatabase: fetchval unused")  # pragma: no cover

    async def execute(self, sql: str, *args: object) -> None:
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO operations"):
            cols = [
                "operation_id",
                "org_id",
                "agent_id",
                "seq_no",
                "operation_type",
                "issued_at",
                "ttl_ms",
                "nonce",
                "subject",
                "action",
                "payload_hash",
                "prev_chain_hash",
                "chain_hash",
                "agent_pubkey_kid",
                "signature",
                "r2_payload_key",
                "created_at",
                # W3 PR-S2 additive (nullable) — present only on §4 ingest,
                # absent on the 17-col W1 Elydora-EOR insert (zip strict=False).
                "correlation_id",
                "run_id",
                "phase",
            ]
            row = dict(zip(cols, args, strict=False))
            self.operations[str(row["operation_id"])] = row
        elif s.startswith("INSERT INTO receipts"):
            cols = ["receipt_id", "operation_id", "r2_receipt_key", "created_at"]
            row = dict(zip(cols, args, strict=True))
            self.receipts[str(row["receipt_id"])] = row
        elif s.startswith("INSERT INTO agents"):
            cols = [
                "agent_id",
                "org_id",
                "display_name",
                "responsible_entity",
                "integration_type",
                "status",
                "created_at",
                "updated_at",
            ]
            row = dict(zip(cols, args, strict=True))
            self.agents[str(row["agent_id"])] = row
        elif s.startswith("INSERT INTO agent_keys"):
            cols = [
                "kid",
                "agent_id",
                "public_key",
                "algorithm",
                "status",
                "created_at",
                "retired_at",
            ]
            row = dict(zip(cols, args, strict=True))
            self.agent_keys[str(row["kid"])] = row
        elif s.startswith("UPDATE agents SET status"):
            self.agents[str(args[-1])]["status"] = args[0]
            self.agents[str(args[-1])]["updated_at"] = args[1]
        elif s.startswith("UPDATE agents SET integration_type"):
            self.agents[str(args[-1])]["integration_type"] = args[0]
            self.agents[str(args[-1])]["updated_at"] = args[1]
        elif s.startswith("UPDATE agent_keys SET status"):
            self.agent_keys[str(args[-1])]["status"] = args[0]
            self.agent_keys[str(args[-1])]["retired_at"] = args[1]
        elif s.startswith("DELETE FROM agent_keys WHERE agent_id"):
            for kid in [k for k, v in self.agent_keys.items() if v["agent_id"] == args[0]]:
                del self.agent_keys[kid]
        elif s.startswith("DELETE FROM agents WHERE agent_id"):
            self.agents.pop(str(args[0]), None)
        elif s.startswith("INSERT INTO intervention_log"):
            cols = [
                "verdict_id",
                "record_id",
                "correlation_id",
                "run_id",
                "decision",
                "step_index",
                "triggered_rule_id",
                "tokens_in",
                "tokens_out",
                "model_id",
                "served_via",
                "latency_ms",
                "created_at",
            ]
            self.intervention_log.append(dict(zip(cols, args, strict=True)))
        elif s.startswith("INSERT INTO governance_verdicts"):
            cols = [
                "verdict_id",
                "record_id",
                "correlation_id",
                "run_id",
                "org_id",
                "agent_id",
                "decision",
                "risk_score",
                "latency_ms",
                "prevented_loss",
                "r2_verdict_key",
                "created_at",
            ]
            row = dict(zip(cols, args, strict=True))
            self.governance_verdicts[str(row["verdict_id"])] = row
        else:  # pragma: no cover - defensive
            raise AssertionError(f"MemoryDatabase: unmodelled execute: {s}")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_MemoryTx]:
        tx = _MemoryTx(self)
        yield tx
        await tx._commit()
