"""Defender — the model-free, deterministic hot path (<500 ms p95, no LLM).

This is the security-critical core: deterministic caps + cumulative-per-recipient
state + free-text scanning. It is intentionally model-free so the blocking gate
is fast and exact, and so the air-gapped profile needs no model here at all
(governance_design.md §3.1; local_deployment_moat.md §2).

W1 shipped the deterministic rule engine + the InjectionTask6 thesis test.
W2 adds :class:`DefenderEngine` (the real, flag-gated hot path emitting a
frozen §4 ``GovernanceVerdict``) wrapping the W1 rules + LlamaFirewall
``scan_async`` + Invariant ``LocalPolicy``.
"""

from __future__ import annotations

from shield_governance.defender.engine import DefenderConfig, DefenderEngine
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
from shield_governance.defender.scanners import (
    FakeInjectionScanner,
    FakeStructuringAnalyzer,
    InjectionScanner,
    LlamaFirewallScanner,
    LocalPolicyStructuringAnalyzer,
    NullInjectionScanner,
    ScanFinding,
    StructuringAnalyzer,
)

__all__ = [
    "ATTACKER_IBAN_EXAMPLE",
    "CumulativeRecipientTracker",
    "DefenderConfig",
    "DefenderEngine",
    "DefenderPolicy",
    "FakeInjectionScanner",
    "FakeStructuringAnalyzer",
    "InjectionScanner",
    "LlamaFirewallScanner",
    "LocalPolicyStructuringAnalyzer",
    "NullInjectionScanner",
    "RuleOutcome",
    "ScanFinding",
    "StructuringAnalyzer",
    "agentdojo_injectiontask6_security",
    "check_amount_cap",
    "check_iban_allowlist",
    "check_iban_format",
    "evaluate_send_money",
    "is_valid_iban",
    "scan_subject_secrets",
]
