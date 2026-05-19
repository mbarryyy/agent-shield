"""Defender — the model-free, deterministic hot path (<500 ms p95, no LLM).

This is the security-critical core: deterministic caps + cumulative-per-recipient
state + free-text scanning. It is intentionally model-free so the blocking gate
is fast and exact, and so the air-gapped profile needs no model here at all
(governance_design.md §3.1; local_deployment_moat.md §2).

W1 ships the deterministic rule engine + its unit tests + the InjectionTask6
oracle test (the thesis as a model-free unit test). The LangGraph node that
wraps these rules, the LlamaFirewall scanners and the Invariant ``LocalPolicy``
land at W2/W3.
"""

from __future__ import annotations

from shield_governance.defender.rules import (
    ATTACKER_IBAN_EXAMPLE,
    CumulativeRecipientTracker,
    DefenderPolicy,
    RuleOutcome,
    agentdojo_injectiontask6_security,
    check_amount_cap,
    check_iban_allowlist,
    check_iban_format,
    evaluate_send_money,
    is_valid_iban,
    scan_subject_secrets,
)

__all__ = [
    "ATTACKER_IBAN_EXAMPLE",
    "CumulativeRecipientTracker",
    "DefenderPolicy",
    "RuleOutcome",
    "agentdojo_injectiontask6_security",
    "check_amount_cap",
    "check_iban_allowlist",
    "check_iban_format",
    "evaluate_send_money",
    "is_valid_iban",
    "scan_subject_secrets",
]
