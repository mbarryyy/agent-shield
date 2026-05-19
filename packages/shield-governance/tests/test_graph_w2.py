"""W2 graph: live LangGraph spine + Channel-2 wiring (END-TO-END)."""

from __future__ import annotations

import pytest
from shield_governance.channel2 import Channel2Consumer, InMemoryChannel2Transport, stream_key
from shield_governance.defender import DefenderConfig, DefenderEngine, DefenderPolicy
from shield_governance.graph import build_graph, make_channel2_handler
from shield_sdk.schema import ActionPayload, Decision, GovernanceVerdict, Phase, ShieldActionRecord

ATT = "US133000000121212121212"
WF = "banking"


def _rec(i: int, amount: float = 10_000) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id="run-1",
        step_index=i,
        phase=Phase.PRE_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": ATT, "amount": amount, "subject": "Hacked!"},
        ),
    )


@pytest.mark.asyncio
async def test_build_graph_compiles_and_runs_defender() -> None:
    eng = DefenderEngine(DefenderConfig(enabled=True, policy=DefenderPolicy(amount_cap=10_000)))
    app = build_graph(eng)
    out = await app.ainvoke({"record": _rec(0, amount=99_999)})  # > cap -> BLOCK
    v = out["verdict"]
    assert isinstance(v, GovernanceVerdict)
    assert v.decision is Decision.BLOCK
    assert out["defender"]["decision"] == "BLOCK"


@pytest.mark.asyncio
async def test_channel2_wired_to_graph_blocks_structuring_end_to_end() -> None:
    """The W2 deliverable proven: server-style records on shield:actions ->
    Channel-2 consumer -> live LangGraph -> real Defender verdict. The 3rd
    structuring leg is BLOCKed; all 3 are consumed + acked (at-least-once)."""
    eng = DefenderEngine(
        DefenderConfig(
            enabled=True, policy=DefenderPolicy(amount_cap=10_000, cumulative_cap=20_000)
        )
    )
    app = build_graph(eng)

    verdicts: list[Decision] = []

    async def handler(record: ShieldActionRecord) -> None:
        out = await app.ainvoke({"record": record})
        verdicts.append(out["verdict"].decision)

    transport = InMemoryChannel2Transport()
    stream = stream_key(WF)
    for i in range(3):
        transport.publish(stream, _rec(i))

    handled = await Channel2Consumer(transport).run_once(WF, handler, count=10, block_ms=0)
    assert handled == 3
    assert verdicts == [Decision.PASS, Decision.PASS, Decision.BLOCK]
    assert transport.acked_ids(stream, "shield-governance") == {"1-0", "2-0", "3-0"}


@pytest.mark.asyncio
async def test_make_channel2_handler_smoke() -> None:
    eng = DefenderEngine(DefenderConfig(enabled=False))  # flag off -> PASS path
    handler = make_channel2_handler(eng)
    transport = InMemoryChannel2Transport()
    transport.publish(stream_key(WF), _rec(0))
    n = await Channel2Consumer(transport).run_once(WF, handler, count=5, block_ms=0)
    assert n == 1
