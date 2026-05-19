"""`python -m shield_eval.run_ab` — THE canonical A/B runner (W0 step 6a LOCKED
name; conforms to tech_stack §2 layout). Behavioral spec = evaluation_plan.md §3.

W0 STUB: argparse skeleton; --smoke exits 0. W1: builds AgentPipeline([...]) and
calls benchmark_suite_with/without_injections() directly (NOT the --defense CLI,
which is code-verified non-functional — ADR-0005/C9). The 5 arms (A0/A0b/A1/A2/A3)
are wired W1->W3.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shield_eval.run_ab")
    p.add_argument("--suite", default="banking")
    p.add_argument("--user-task", action="append", default=[])
    p.add_argument("--injection-task", action="append", default=[])
    p.add_argument("--attack", default=None)
    p.add_argument("--assert", dest="asserts", action="append", default=[])
    p.add_argument("--metrics", default=None)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--full", action="store_true")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    print(
        f"shield_eval.run_ab: W0 stub (suite={args.suite}, smoke={args.smoke}). "
        "Real A/B arms wired W1->W3."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
