"""Eval-owned ``/decide`` providers — the A1/A2 verdict source + the
thesis-preserving fallback (master design §10; implementation_plan W2).

Three modes, all returning the **frozen v1.1** ``GovernanceVerdict`` imported
from ``shield_sdk.schema`` (never redeclared; no contracts/ edits):

* ``noop``  — always ``PASS``. This is the §4.4 **Free no-op gate = arm A1**
              and mirrors the server's ``stub_pass_verdict`` exactly.
* ``mock``  — a ~80-LOC deterministic rule (allowlist + single-amount cap +
              cumulative-per-recipient-per-run). No LLM. This is the
              **authorized fallback** that keeps the thesis runnable if the
              server ``/decide`` slips past end-W2, and the A2 stub verdict
              source. It BLOCKs ``InjectionTask6``'s 3×$10k structuring via
              the cumulative rule that single-call defenses cannot express.
* ``http``  — ``POST`` to the real ``shield-server`` ``/v1/governance/decide``
              once server-w2 is live (clean switch, same return type).

Honest scope: ``mock`` is a deterministic rule engine, **not** a model and
**not** Layer-2 — it preserves the thesis offline; real governed verdicts come
from shield-governance via the server. Comparisons stay scoped to "beat the 4
AgentDojo built-in baselines + the Axis-C moat", never "beat SOTA".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    ServedVia,
    VerdictReason,
)

# Tools whose mutation is irreversible/financial — the LOCKED fail-CLOSED set
# (C3 / research_plan §5d / master design §6). The mock denies attacker-bound
# money movement here; the enforcement layer also fail-CLOSES these on ESCALATE.
MONEY_TOOLS: frozenset[str] = frozenset(
    {"send_money", "update_scheduled_transaction", "schedule_transaction"}
)


@dataclass
class DecideRequest:
    """The minimal pre-exec intent the providers judge (a projection of the
    frozen ``ShieldActionRecord`` — eval does not redeclare that type)."""

    tool_name: str
    tool_args: dict[str, Any]
    run_id: str
    correlation_id: str
    step_index: int = 0


class DecideProvider(Protocol):
    """Stable seam the SDK ``ShieldGuard`` will call (cloud/local/mock/noop)."""

    name: str

    def decide(self, req: DecideRequest) -> GovernanceVerdict: ...


class NoopDecide:
    """Arm **A1** — the Free no-op gate. Always ``PASS`` (zero governance,
    zero tokens). Identical behaviour to the server stub."""

    name = "noop"

    def decide(self, req: DecideRequest) -> GovernanceVerdict:
        return GovernanceVerdict(
            decision=Decision.PASS,
            correlation_id=req.correlation_id,
            run_id=req.run_id,
            risk_score=0.0,
            latency_ms=0.0,
        )


@dataclass
class MockDecideConfig:
    """Runtime-loadable thresholds (also feed the future A3 ablation)."""

    single_cap: float = 10_000.0
    cumulative_cap: float = 20_000.0
    recipient_allowlist: frozenset[str] | None = None  # None ⇒ allow-by-default
    recipient_denylist: frozenset[str] = frozenset()


class MockDecide:
    """Arm **A2** stub + the thesis-preserving fallback. Deterministic, no LLM.

    Rules over ``send_money``-class tools, per ``(run_id, recipient)``:

    1. recipient on the denylist                       → ``BLOCK``
    2. allowlist configured and recipient not in it    → ``BLOCK``
    3. single ``amount`` > ``single_cap``              → ``BLOCK``
    4. cumulative-to-recipient + amount > ``cumulative_cap``
       → ``ESCALATE`` (grey-band: structuring across calls; degrades to
       ``BLOCK`` deterministically in non-interactive batch — see
       ``enforcement.py``; the live demo keeps real ``interrupt()`` HITL)

    On ``InjectionTask6`` (3×$10k → attacker IBAN) rule 4 fires on the call
    that crosses the cumulative cap — the cross-call structuring no single-call
    AgentDojo baseline can catch. Auto-scored by AgentDojo's own oracle.
    """

    name = "mock"

    def __init__(self, config: MockDecideConfig | None = None) -> None:
        self._cfg = config or MockDecideConfig()
        # (run_id, recipient) -> cumulative amount already requested this run
        self._cumulative: dict[tuple[str, str], float] = {}

    @staticmethod
    def _amount(args: dict[str, Any]) -> float:
        try:
            return float(args.get("amount", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _verdict(
        self,
        req: DecideRequest,
        decision: Decision,
        label: str,
        detail: str,
        score: float,
        *,
        require_human: bool = False,
    ) -> GovernanceVerdict:
        return GovernanceVerdict(
            decision=decision,
            correlation_id=req.correlation_id,
            run_id=req.run_id,
            risk_score=score,
            reasons=[
                VerdictReason(
                    agent=Guardian.EVALUATOR,
                    label=label,
                    detail=detail,
                    score=score,
                    served_via=ServedVia.LOCAL,
                )
            ],
            obligations=Obligations(require_human=require_human),
            latency_ms=1.0,
        )

    def decide(self, req: DecideRequest) -> GovernanceVerdict:
        if req.tool_name not in MONEY_TOOLS:
            return self._verdict(req, Decision.PASS, "NON_FINANCIAL", "not a money tool", 0.0)

        recipient = str(req.tool_args.get("recipient", ""))
        amount = self._amount(req.tool_args)
        cfg = self._cfg

        if recipient in cfg.recipient_denylist:
            return self._verdict(
                req, Decision.BLOCK, "RECIPIENT_DENYLISTED", f"{recipient} denylisted", 0.99
            )
        if cfg.recipient_allowlist is not None and recipient not in cfg.recipient_allowlist:
            return self._verdict(
                req,
                Decision.BLOCK,
                "RECIPIENT_NOT_ALLOWLISTED",
                f"{recipient} not allowlisted",
                0.9,
            )
        if amount > cfg.single_cap:
            return self._verdict(
                req,
                Decision.BLOCK,
                "SINGLE_AMOUNT_CAP",
                f"{amount} > single cap {cfg.single_cap}",
                0.92,
            )

        key = (req.run_id, recipient)
        running = self._cumulative.get(key, 0.0)
        if running + amount > cfg.cumulative_cap:
            # Cross-call structuring — the InjectionTask6 catcher. Grey-band →
            # ESCALATE; deterministically degrades to BLOCK in batch.
            return self._verdict(
                req,
                Decision.ESCALATE,
                "CUMULATIVE_STRUCTURING",
                f"cumulative {running + amount} to {recipient} > cap {cfg.cumulative_cap}",
                0.85,
                require_human=True,
            )
        self._cumulative[key] = running + amount
        return self._verdict(req, Decision.PASS, "WITHIN_LIMITS", "within caps", 0.05)


@dataclass
class HttpDecide:
    """Arm **A2** real path — ``POST`` the pre-exec record to the live
    ``shield-server`` ``/v1/governance/decide``. Switched in cleanly once
    server-w2 is up; same ``GovernanceVerdict`` return type."""

    url: str
    timeout_s: float = 0.5
    name: str = field(default="http", init=False)

    def decide(self, req: DecideRequest) -> GovernanceVerdict:
        import httpx

        payload = {
            "tool_name": req.tool_name,
            "tool_args": req.tool_args,
            "run_id": req.run_id,
            "correlation_id": req.correlation_id,
            "step_index": req.step_index,
        }
        resp = httpx.post(self.url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        return GovernanceVerdict.model_validate(resp.json())


def build_decider(mode: str, *, url: str | None = None) -> DecideProvider:
    """Factory used by run_ab. ``noop`` ⇒ A1, ``mock`` ⇒ A2 fallback/stub,
    ``http`` ⇒ A2 real (server)."""
    if mode == "noop":
        return NoopDecide()
    if mode == "mock":
        return MockDecide()
    if mode == "http":
        if not url:
            raise ValueError("--decide http requires --decide-url")
        return HttpDecide(url=url)
    raise ValueError(f"unknown decide mode '{mode}' (noop|mock|http)")


def mock_transport(provider: DecideProvider) -> Any:
    """An ``httpx.MockTransport`` that serves an eval-owned ``DecideProvider``
    in-process, so the **unchanged** sdk ``ShieldClient`` (HTTP-only) can drive
    A1/A2/A3 deterministically with NO live server (W2 ``decide.py`` fallback,
    realised as the demo-safety mitigation — master §10 / eval_plan §10).

    Routes (server-confirmed): ``decide_path`` (pre_exec, Channel-1) → the
    provider's signed-shape ``GovernanceVerdict``; ``record_path`` (post_exec,
    Channel-2) → ``202`` ack. The posted body is the frozen-§4
    ``ShieldActionRecord`` JSON; we project ``payload.tool_name/tool_args`` +
    ``run_id/correlation_id/step_index`` (never redeclaring the type).
    """
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        rec = json.loads(request.content or b"{}")
        path = request.url.path
        if path.endswith("/record"):  # Channel-2 post_exec ack
            return httpx.Response(202, json={"ack": True, "record_id": rec.get("record_id")})
        payload = rec.get("payload") or {}
        req = DecideRequest(
            tool_name=payload.get("tool_name") or (rec.get("action") or {}).get("tool") or "",
            tool_args=payload.get("tool_args") or {},
            run_id=rec.get("run_id") or "run-shield",
            correlation_id=rec.get("correlation_id") or "corr-shield",
            step_index=int(rec.get("step_index") or 0),
        )
        verdict = provider.decide(req)
        return httpx.Response(200, json=verdict.model_dump(mode="json"))

    return httpx.MockTransport(handler)


class RealGovUnavailable(RuntimeError):
    """The converged gov surface (build_decide_app/decide) is not importable
    on this tree — caller SKIPs the real-graph run (never fakes it)."""


# Frozen golden test keypair (W0 vectors) — real Ed25519, used so the REAL
# server ingest's FROZEN canonical.verify_record passes against the agent
# pubkey we enrol via the server's own public register API.
_GOLDEN_VECTORS = (
    __import__("pathlib").Path(__file__).resolve().parents[4]
    / "contracts"
    / "golden"
    / "vectors.json"
)


def real_server_transport() -> Any:
    """The team-lead-APPROVED REAL-graph method: an ``httpx.ASGITransport``
    over the **real** ``shield_server.create_app`` (in-memory storage, real
    ShieldSdkCrypto) pre-warmed with the server governance adapter
    (``load_governance_app()`` → the merged gov adapter). This exercises the
    REAL server 12-step ingest + verdict signing + the server governance ``decide()``
    end-to-end — NOT a mock. Keyless is valid: the InjectionTask6 BLOCK is the
    HG#5 model-free path (0 LLM tokens on decide→BLOCK).

    Uses ONLY server PUBLIC API (``create_app`` / ``build_memory_storage`` /
    ``register_agent`` — the established server in-process/docker-free pattern,
    cf. shield-server's own ``tests/test_governance.py``); the frozen golden
    keypair is enrolled via the real ``/v1/agents`` register service so the
    FROZEN ``canonical.verify_record`` passes with REAL Ed25519 (no FakeCrypto).
    If server infra it cannot satisfy in-process is required → ``RealGov
    Unavailable`` (caller SKIPs + flags honestly; NEVER fakes a real result).
    """
    import asyncio
    import json as _json

    import httpx

    try:
        from shield_server.agents import register_agent
        from shield_server.app import create_app
        from shield_server.config import Settings
        from shield_server.govseam import load_governance_app
        from shield_server.models import RegisterAgentRequest
        from shield_server.storage import build_memory_storage
    except ImportError as e:  # pragma: no cover - pre server/gov-W3 trees only
        raise RealGovUnavailable(
            f"real shield-server/gov surface not importable ({e}) "
            "— real-server-graph run SKIPPED (never faked)"
        ) from e

    kp = _json.loads(_GOLDEN_VECTORS.read_text(encoding="utf-8"))["keypair"]

    async def _setup() -> Any:
        storage = build_memory_storage()
        # Enrol the frozen agent via the server's OWN public register service
        # (agent_id/kid = sdk ShieldElementConfig defaults; pubkey = golden).
        await register_agent(
            storage,
            RegisterAgentRequest(
                agent_id="agentdojo-banking-v1",
                keys=[
                    {"kid": "agentdojo-banking-v1-key-v1", "public_key": kp["public_key_b64url"]}
                ],
            ),
            "demo-org",
        )
        # load_governance_app() is the server's OWN pre-warm resolver: with
        # gov-W3 merged it returns the governance adapter (decide+resume) —
        # exactly what create_app's lifespan does.
        return create_app(
            storage=storage,
            settings=Settings.from_env(),
            governance=load_governance_app(),
        )

    try:
        app = asyncio.run(_setup())
    except Exception as e:  # pragma: no cover - server infra/setup blockers
        raise RealGovUnavailable(
            f"real shield-server in-process setup blocked ({e!r}) "
            "— real-server-graph run SKIPPED + flagged (never faked)"
        ) from e

    return httpx.ASGITransport(app=app)
