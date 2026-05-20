"""In-memory storage fakes.

A shipped module (not test-only) so the unit suite exercises the *real* 12-step
ingest / audit / agent / auth logic against it and ``--cov=packages`` counts
that coverage without docker. The asyncpg/MinIO/Redis adapters run the
identical logic against real infra in the integration job.

``MemoryDatabase`` is a deliberately tiny SQL-ish executor: it understands
only the fixed statement shapes the ingest/audit/agent/auth services issue
(faithful ports of Elydora's W3 queries + ADR-0013 §A1-§A11 enterprise auth
shapes), not arbitrary SQL.
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
        # Preserve TTL if previously set (Redis SET semantics under our usage).
        previous = self._store.get(key)
        expires = previous[1] if previous else None
        self._store[key] = (value, expires)

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
    """Recognises only the fixed Elydora-ported + ADR-0013 statement shapes."""

    def __init__(self) -> None:
        # --- W3 baseline tables ---
        self.organizations: dict[str, dict[str, Any]] = {}
        self.agents: dict[str, dict[str, Any]] = {}
        self.agent_keys: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, dict[str, Any]] = {}
        self.intervention_log: list[dict[str, Any]] = []
        self.governance_verdicts: dict[str, dict[str, Any]] = {}
        # --- ADR-0013 enterprise-auth tables ---
        self.users: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.memberships: dict[tuple[str, str], dict[str, Any]] = {}
        self.password_reset_tokens: dict[str, dict[str, Any]] = {}
        self.email_verification_tokens: dict[str, dict[str, Any]] = {}
        self.invites: dict[str, dict[str, Any]] = {}
        self.totp_credentials: dict[str, dict[str, Any]] = {}
        self.api_keys: dict[str, dict[str, Any]] = {}
        self.audit_log_auth: list[dict[str, Any]] = []

    # ---- fetchrow -------------------------------------------------------- #

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        s = " ".join(sql.split())
        # W3 — existing shapes preserved byte-identically.
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

        # --- ADR-0013 auth shapes --------------------------------------- #

        if s.startswith("SELECT user_id, email, password_hash, password_pepper_kid"):
            # find_by_email OR find_by_user_id
            if "lower(email)" in s.lower() or "WHERE lower(email)" in s:
                key = str(args[0]).lower()
                for u in self.users.values():
                    if str(u["email"]).lower() == key:
                        return dict(u)
                return None
            row = self.users.get(str(args[0]))
            return None if row is None else dict(row)

        if s.startswith("SELECT session_id, user_id, csrf_token"):
            # Two queries share this SELECT prefix; discriminate on WHERE:
            #   lookup_session: ... WHERE token_hash = $1
            #   /session refetch: ... WHERE session_id = $1
            if "WHERE token_hash" in s:
                for sess in self.sessions.values():
                    if sess["token_hash"] == args[0]:
                        return dict(sess)
                return None
            if "WHERE session_id" in s:
                sess_lookup = self.sessions.get(str(args[0]))
                return None if sess_lookup is None else dict(sess_lookup)
            return None

        if s.startswith("SELECT failed_login_count FROM users WHERE user_id"):
            row = self.users.get(str(args[0]))
            if row is None:
                return None
            return {"failed_login_count": row.get("failed_login_count", 0)}

        if s.startswith("SELECT role FROM memberships WHERE user_id"):
            m = self.memberships.get((str(args[0]), str(args[1])))
            return None if m is None else {"role": m["role"]}

        if s.startswith("SELECT api_key_id, org_id, agent_id, agent_id_allowlist, prefix"):
            for k in self.api_keys.values():
                if k["token_hash"] == args[0]:
                    return dict(k)
            return None

        if s.startswith("SELECT user_id, expires_at, consumed_at FROM password_reset_tokens"):
            row = self.password_reset_tokens.get(str(args[0]))
            return None if row is None else dict(row)
        if s.startswith("SELECT user_id, expires_at, consumed_at FROM email_verification_tokens"):
            row = self.email_verification_tokens.get(str(args[0]))
            return None if row is None else dict(row)

        if s.startswith("SELECT user_id, secret_encrypted, active_kid"):
            row = self.totp_credentials.get(str(args[0]))
            return None if row is None else dict(row)

        if s.startswith("SELECT 1 FROM information_schema.tables"):
            # The migration-firedrill helper calls this; the MemoryDatabase
            # is the unit-test path where the tables that ``_table_exists``
            # asks about are always considered present (we don't simulate
            # the up→down migration on the in-memory store).
            return {"?": 1}

        if s.startswith("SELECT invite_id, org_id, email, role, invited_by"):
            for inv in self.invites.values():
                if inv["token_hash"] == args[0]:
                    return dict(inv)
            return None

        raise AssertionError(f"MemoryDatabase: unmodelled fetchrow: {s}")

    # ---- fetch ---------------------------------------------------------- #

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        s = " ".join(sql.split())
        # W3-baseline `FROM agents` org-wide list (no args) and `FROM agents
        # WHERE org_id` filtered list are both modelled here.
        if "FROM agents WHERE org_id" in s:
            return [dict(a) for a in self.agents.values() if a["org_id"] == args[0]]
        if "SELECT agent_id FROM agents WHERE org_id" in s:
            return [dict(a) for a in self.agents.values() if a["org_id"] == args[0]]
        if "FROM agents" in s:
            return [dict(a) for a in self.agents.values()]
        if "FROM agent_keys" in s:
            return [dict(k) for k in self.agent_keys.values() if k["agent_id"] == args[0]]
        if "FROM operations" in s:
            return [dict(o) for o in self.operations.values()]
        if "FROM intervention_log" in s:
            return [dict(r) for r in self.intervention_log]
        if "FROM governance_verdicts" in s:
            return [dict(v) for v in self.governance_verdicts.values()]
        # W3-protected tables that have no Memory state (Postgres-only or
        # rarely-fetched) — return empty so the §A5 fire-drill snapshot
        # helper can call ``SELECT * FROM <protected_table>`` against the
        # MemoryDatabase without falling through to the unmodelled-fetch
        # AssertionError below.
        if "FROM receipts" in s:
            return [dict(r) for r in self.receipts.values()]
        if "FROM epochs" in s or "FROM exports" in s or "FROM agent_sessions" in s:
            return []
        # --- auth tables ---
        if s.startswith("SELECT session_id, user_id, ip, user_agent"):
            return [dict(r) for r in self.sessions.values() if r["user_id"] == args[0]]
        if s.startswith("SELECT org_id, role FROM memberships WHERE user_id"):
            rows = [dict(m) for k, m in self.memberships.items() if k[0] == args[0]]
            rows.sort(key=lambda r: int(r["joined_at"]))
            return rows
        if "FROM api_keys" in s:
            return [dict(k) for k in self.api_keys.values() if k["org_id"] == args[0]]
        if "FROM users" in s:
            return [dict(u) for u in self.users.values()]
        if "FROM audit_log_auth" in s:
            return [dict(a) for a in self.audit_log_auth]
        if "FROM information_schema.tables" in s:
            # Used by migration_firedrill._table_exists (unit-test stub).
            return [{"?": 1}]
        raise AssertionError(f"MemoryDatabase: unmodelled fetch: {sql}")  # pragma: no cover

    async def fetchval(self, sql: str, *args: object) -> object:
        raise AssertionError("MemoryDatabase: fetchval unused")  # pragma: no cover

    # ---- execute --------------------------------------------------------- #

    async def execute(self, sql: str, *args: object) -> None:
        s = " ".join(sql.split())
        # ============================================================ W3 ==
        if s.startswith("INSERT INTO organizations"):
            # Idempotent ``ON CONFLICT (org_id) DO NOTHING`` mirror — keyed
            # on org_id; second insert with the same id is a no-op.
            cols = ["org_id", "name", "created_at", "updated_at"]
            # The seed-admin SQL uses VALUES ($1, $2, $3, $3) — i.e. 3 args
            # with the 4th repeated. Map by index up to len(args).
            row_args = list(args)
            if len(row_args) == 3:
                row_args.append(row_args[2])  # updated_at = created_at
            row = dict(zip(cols, row_args, strict=False))
            self.organizations.setdefault(str(row["org_id"]), row)
            return
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
        elif s.startswith("UPDATE governance_verdicts SET resolution"):
            gv = self.governance_verdicts.get(str(args[-1]))
            if gv is not None:
                gv["resolution"] = args[0]
                gv["resolved_at"] = args[1]

        # ====================================================== ADR-0013 ==
        elif s.startswith("INSERT INTO users"):
            cols = [
                "user_id",
                "email",
                "password_hash",
                "password_pepper_kid",
                "name",
                "created_at",  # status/email_verified/etc are literals in SQL
            ]
            # SQL literal columns: status='active', email_verified_at=NULL,
            # failed_login_count=0, locked_until=NULL, totp_enabled=FALSE,
            # updated_at=$6, last_login_at=NULL.
            row = dict(zip(cols, args, strict=False))
            row.setdefault("status", "active")
            row.setdefault("email_verified_at", None)
            row.setdefault("failed_login_count", 0)
            row.setdefault("locked_until", None)
            row.setdefault("totp_enabled", False)
            row.setdefault("updated_at", row.get("created_at"))
            row.setdefault("last_login_at", None)
            self.users[str(row["user_id"])] = row
        elif s.startswith("INSERT INTO memberships"):
            cols = ["user_id", "org_id", "role", "invited_by", "joined_at"]
            row = dict(zip(cols, args, strict=True))
            self.memberships[(str(row["user_id"]), str(row["org_id"]))] = row
        elif s.startswith("INSERT INTO sessions"):
            cols = [
                "session_id",
                "user_id",
                "token_hash",
                "csrf_token",
                "ip",
                "user_agent",
                "created_at",
                "last_used_at",
                "expires_at",
                "revoked_at",
            ]
            row = dict(zip(cols, args, strict=False))
            row.setdefault("revoked_at", None)
            self.sessions[str(row["session_id"])] = row
        elif s.startswith("INSERT INTO password_reset_tokens"):
            # consumed_at is LITERAL NULL in the SQL → 4 args, not 5.
            cols = ["token_hash", "user_id", "expires_at", "created_at"]
            row = dict(zip(cols, args, strict=True))
            row["consumed_at"] = None
            self.password_reset_tokens[str(row["token_hash"])] = row
        elif s.startswith("INSERT INTO email_verification_tokens"):
            cols = ["token_hash", "user_id", "expires_at", "created_at"]
            row = dict(zip(cols, args, strict=True))
            row["consumed_at"] = None
            self.email_verification_tokens[str(row["token_hash"])] = row
        elif s.startswith("INSERT INTO invites"):
            # consumed_at is a LITERAL NULL in the admin/invite SQL → only 8
            # positional args. Skip consumed_at in the col mapping so the
            # values land in the right keys (mirrors the password_reset_tokens
            # / email_verification_tokens shape).
            cols = [
                "invite_id",
                "org_id",
                "email",
                "role",
                "invited_by",
                "expires_at",
                "created_at",
                "token_hash",
            ]
            row = dict(zip(cols, args, strict=True))
            row["consumed_at"] = None
            self.invites[str(row["invite_id"])] = row
        elif s.startswith("INSERT INTO totp_credentials"):
            cols = [
                "user_id",
                "secret_encrypted",
                "active_kid",
                "recovery_codes_hash",
                "enabled_at",
                "last_used_at",
            ]
            row = dict(zip(cols, args, strict=False))
            row.setdefault("last_used_at", None)
            self.totp_credentials[str(row["user_id"])] = row
        elif s.startswith("INSERT INTO api_keys"):
            cols = [
                "api_key_id",
                "org_id",
                "agent_id",
                "agent_id_allowlist",
                "token_hash",
                "prefix",
                "display_name",
                "created_by",
                "created_at",
                "expires_at",
                "last_used_at",
                "revoked_at",
            ]
            row = dict(zip(cols, args, strict=False))
            row.setdefault("last_used_at", None)
            row.setdefault("revoked_at", None)
            self.api_keys[str(row["api_key_id"])] = row
        elif s.startswith("INSERT INTO audit_log_auth"):
            cols = [
                "audit_id",
                "user_id",
                "org_id",
                "event",
                "ip",
                "user_agent",
                "detail",
                "created_at",
            ]
            self.audit_log_auth.append(dict(zip(cols, args, strict=True)))

        # ---- session UPDATEs ----
        elif s.startswith("UPDATE sessions SET last_used_at"):
            sess = self.sessions.get(str(args[-1]))
            if sess is not None:
                sess["last_used_at"] = args[0]
        elif s.startswith("UPDATE sessions SET token_hash"):
            sess = self.sessions.get(str(args[-1]))
            if sess is not None:
                sess["token_hash"] = args[0]
                sess["csrf_token"] = args[1]
                sess["last_used_at"] = args[2]
        elif s.startswith("UPDATE sessions SET revoked_at = $1 WHERE session_id"):
            sess = self.sessions.get(str(args[-1]))
            if sess is not None:
                sess["revoked_at"] = args[0]
        elif s.startswith("UPDATE sessions SET revoked_at = $1 WHERE user_id"):
            for sess in self.sessions.values():
                if sess["user_id"] == args[1] and sess.get("revoked_at") is None:
                    sess["revoked_at"] = args[0]

        # ---- token UPDATEs ----
        elif s.startswith("UPDATE password_reset_tokens SET consumed_at"):
            tok = self.password_reset_tokens.get(str(args[-1]))
            if tok is not None:
                tok["consumed_at"] = args[0]
        elif s.startswith("UPDATE email_verification_tokens SET consumed_at"):
            tok = self.email_verification_tokens.get(str(args[-1]))
            if tok is not None:
                tok["consumed_at"] = args[0]
        elif s.startswith("UPDATE invites SET consumed_at"):
            inv = self.invites.get(str(args[-1]))
            if inv is not None:
                inv["consumed_at"] = args[0]

        # ---- user UPDATEs ----
        # Two distinct shapes; reset variant matched FIRST so the more
        # specific prefix wins:
        #   reset: "UPDATE users SET failed_login_count = 0, ..." (2 args)
        #   inc:   "UPDATE users SET failed_login_count = $1, ..." (4 args)
        elif s.startswith("UPDATE users SET failed_login_count = 0"):
            user = self.users.get(str(args[-1]))
            if user is not None:
                user["failed_login_count"] = 0
                user["locked_until"] = None
                if user.get("status") == "locked":
                    user["status"] = "active"
                user["last_login_at"] = args[0]
                user["updated_at"] = args[0]
        elif s.startswith("UPDATE users SET failed_login_count"):
            user = self.users.get(str(args[-1]))
            if user is not None:
                user["failed_login_count"] = args[0]
                user["locked_until"] = args[1]
                user["updated_at"] = args[2]
                if args[1] is not None:
                    user["status"] = "locked"
        elif s.startswith("UPDATE users SET password_hash"):
            user = self.users.get(str(args[-1]))
            if user is not None:
                user["password_hash"] = args[0]
                user["password_pepper_kid"] = args[1]
                user["updated_at"] = args[2]
        elif s.startswith("UPDATE users SET totp_enabled"):
            user = self.users.get(str(args[-1]))
            if user is not None:
                user["totp_enabled"] = args[0]
                user["updated_at"] = args[1]
        elif s.startswith("UPDATE users SET email_verified_at"):
            user = self.users.get(str(args[-1]))
            if user is not None:
                user["email_verified_at"] = args[0]
                user["updated_at"] = args[0]
        elif s.startswith("UPDATE memberships SET role"):
            key = (str(args[1]), str(args[2]))
            m = self.memberships.get(key)
            if m is not None:
                m["role"] = args[0]

        # ---- api_key UPDATEs ----
        elif s.startswith("UPDATE api_keys SET last_used_at"):
            k = self.api_keys.get(str(args[-1]))
            if k is not None:
                k["last_used_at"] = args[0]
        elif s.startswith("UPDATE api_keys SET revoked_at"):
            k = self.api_keys.get(str(args[-1]))
            if k is not None:
                k["revoked_at"] = args[0]

        # ---- totp updates (re-wrap) ----
        elif s.startswith("UPDATE totp_credentials SET secret_encrypted"):
            tc = self.totp_credentials.get(str(args[-1]))
            if tc is not None:
                tc["secret_encrypted"] = args[0]
                tc["active_kid"] = args[1]
        elif s.startswith("UPDATE totp_credentials SET recovery_codes_hash"):
            tc = self.totp_credentials.get(str(args[-1]))
            if tc is not None:
                tc["recovery_codes_hash"] = args[0]
                tc["last_used_at"] = args[1]
        elif s.startswith("DELETE FROM totp_credentials WHERE user_id"):
            self.totp_credentials.pop(str(args[0]), None)

        else:  # pragma: no cover - defensive
            raise AssertionError(f"MemoryDatabase: unmodelled execute: {s}")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_MemoryTx]:
        tx = _MemoryTx(self)
        yield tx
        await tx._commit()
