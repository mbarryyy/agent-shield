"""`python -m shield_eval.metrics` — ASR/UR/DR/FPR/IL/TO + BCR + gate `--check`.
W0 STUB: prints and exits 0. W4 eval-builder implements the metrics table."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shield_eval.metrics")
    p.add_argument("--check", default=None, help="e.g. 'asr<=0.10,ur>=0.80,il_p95_ms<=2000'")
    p.parse_args(argv)
    print("shield_eval.metrics: W0 stub (metrics table lands at W4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
