"""Wave-2 chunk #3a: two deterministic Defender tools (no LLM, no key).

* ``scan_code`` (governance_design §3.1) — model-free dangerous-code detector
  over free-text args (the air-gap-safe core of the LlamaFirewall CODE_SHIELD
  intent: flag eval/exec/os.system/subprocess/dangerous imports/shell
  backticks). Returns the same :class:`ScanFinding` shape as the other
  Defender scanners.
* ``value_sanity`` (governance_design §3.2 "numeric range vs baseline") — the
  deterministic half of hallucination_check/value_sanity: a numeric bounds /
  sanity predicate (non-negative, finite, not absurd-magnitude, within a
  configured ceiling). Returns the deterministic :class:`RuleOutcome` shape.
"""

from __future__ import annotations

import math

from shield_governance.defender.rules import value_sanity
from shield_governance.defender.scanners import CodeShieldScanner, scan_code
from shield_sdk.schema import Decision

# --------------------------------------------------------------------------- #
# scan_code
# --------------------------------------------------------------------------- #


def test_scan_code_flags_eval_exec() -> None:
    finding = scan_code("result = eval(user_input)", kind="subject")
    assert finding.blocked is True
    assert finding.label == "scanner.code.subject"
    assert finding.score == 1.0


def test_scan_code_flags_os_system_and_subprocess() -> None:
    assert scan_code("os.system('rm -rf /')", kind="arg").blocked is True
    assert scan_code("subprocess.Popen(['sh', '-c', 'x'])", kind="arg").blocked is True


def test_scan_code_flags_dangerous_import() -> None:
    assert scan_code("import os; os.remove(p)", kind="arg").blocked is True
    assert scan_code("__import__('subprocess')", kind="arg").blocked is True


def test_scan_code_flags_shell_backticks() -> None:
    assert scan_code("echo `cat /etc/passwd`", kind="arg").blocked is True


def test_scan_code_clean_text_passes() -> None:
    finding = scan_code("pay the December rent to my landlord", kind="subject")
    assert finding.blocked is False
    assert finding.escalate is False
    assert finding.label == "scanner.code.clean"
    assert finding.score == 0.0


def test_scan_code_empty_is_clean() -> None:
    assert scan_code("", kind="subject").blocked is False


def test_code_shield_scanner_adapter_is_async_and_matches_scan_code() -> None:
    import asyncio

    scanner = CodeShieldScanner()
    finding = asyncio.run(scanner.scan_text("eval('2+2')", kind="subject"))
    assert finding.blocked is True
    assert finding.label == "scanner.code.subject"


# --------------------------------------------------------------------------- #
# value_sanity
# --------------------------------------------------------------------------- #


def test_value_sanity_normal_amount_passes() -> None:
    outcome = value_sanity(1234.56)
    assert outcome.decision is Decision.PASS
    assert outcome.label == "value.sane"


def test_value_sanity_negative_blocks() -> None:
    outcome = value_sanity(-5.0)
    assert outcome.decision is Decision.BLOCK
    assert outcome.label == "value.negative"


def test_value_sanity_nan_blocks() -> None:
    assert value_sanity(math.nan).decision is Decision.BLOCK


def test_value_sanity_inf_blocks() -> None:
    assert value_sanity(math.inf).decision is Decision.BLOCK


def test_value_sanity_absurd_magnitude_blocks() -> None:
    # Above the sanity ceiling (default) → blocked as implausible.
    outcome = value_sanity(1e15)
    assert outcome.decision is Decision.BLOCK
    assert outcome.label == "value.implausible_magnitude"


def test_value_sanity_respects_configured_ceiling() -> None:
    assert value_sanity(500.0, ceiling=100.0).decision is Decision.BLOCK
    assert value_sanity(50.0, ceiling=100.0).decision is Decision.PASS


def test_value_sanity_unparseable_blocks() -> None:
    outcome = value_sanity("not-a-number")
    assert outcome.decision is Decision.BLOCK
    assert outcome.label == "value.unparseable"
