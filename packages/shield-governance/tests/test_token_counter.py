"""Cost hook #1 (SOURCE) — token counter keyed to record_id/correlation_id."""

from __future__ import annotations

from shield_governance.model_router import ShieldModelRouter
from shield_governance.token_counter import LLMUsageSample, TokenCounter
from shield_sdk.schema import Guardian, ServedVia


def test_record_and_totals() -> None:
    tc = TokenCounter()
    tc.record(
        LLMUsageSample("r1", "c1", Guardian.EVALUATOR, "claude-sonnet-4", ServedVia.CLOUD, 100, 40)
    )
    tc.record(
        LLMUsageSample("r1", "c1", Guardian.SUPERVISOR, "claude-opus-4", ServedVia.CLOUD, 50, 10)
    )
    tc.record(LLMUsageSample("r2", "c2", Guardian.EVALUATOR, "Qwen2.5-32B", ServedVia.LOCAL, 7, 3))
    assert tc.totals_for("r1") == (150, 50)
    assert tc.totals_for("r2") == (7, 3)
    assert tc.totals_for("absent") == (0, 0)
    assert len(tc.samples_for("r1")) == 2


def test_record_router_call_pulls_model_and_served_via() -> None:
    """Cost hook #1 (tokens) + hook #2 (model_id/served_via) share ONE source:
    the ShieldModelRouter — no divergence possible."""
    router = ShieldModelRouter.from_profile("cloud")
    tc = TokenCounter()
    s = tc.record_router_call(
        record_id="rec-9",
        correlation_id="cor-9",
        agent=Guardian.EVALUATOR,
        router=router,
        role="evaluator",
        prompt_tokens=12,
        completion_tokens=4,
    )
    assert s.model_id == "claude-sonnet-4-20250514"
    assert s.served_via is ServedVia.CLOUD
    assert tc.totals_for("rec-9") == (12, 4)

    local = ShieldModelRouter.from_profile("local")
    s2 = tc.record_router_call(
        record_id="rec-9",
        correlation_id="cor-9",
        agent=Guardian.SUPERVISOR,
        router=local,
        role="supervisor",
        prompt_tokens=1,
        completion_tokens=1,
    )
    assert s2.model_id == "Llama-3.3-70B-Instruct"
    assert s2.served_via is ServedVia.LOCAL


def test_intervention_rows_are_the_server_sink_contract() -> None:
    tc = TokenCounter()
    tc.record(
        LLMUsageSample("r1", "c1", Guardian.EVALUATOR, "m", ServedVia.LOCAL, 5, 2, step_index=3)
    )
    rows = tc.intervention_rows()
    assert len(rows) == 1
    row = rows[0]
    # The exact value contract that POPULATES server's intervention_log columns.
    assert row.record_id == "r1"
    assert row.correlation_id == "c1"
    assert row.step_index == 3
    assert row.agent == "evaluator"
    assert row.served_via == "local"
    assert (row.tokens_in, row.tokens_out) == (5, 2)


def test_negative_tokens_clamped_and_reset() -> None:
    router = ShieldModelRouter.from_profile("cloud")
    tc = TokenCounter()
    tc.record_router_call(
        record_id="r",
        correlation_id="c",
        agent=Guardian.AUDITOR,
        router=router,
        role="auditor",
        prompt_tokens=-5,
        completion_tokens=-1,
    )
    assert tc.totals_for("r") == (0, 0)
    tc.reset()
    assert tc.intervention_rows() == []
