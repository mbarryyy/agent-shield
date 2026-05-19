"""`python -m shield_eval.changelog --since-last-tag` — conventional-commit
changelog for release.yml. W0 STUB: prints a placeholder, exits 0."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shield_eval.changelog")
    p.add_argument("--since-last-tag", action="store_true")
    p.parse_args(argv)
    print("## Release notes\n\n- W0 stub (conventional-commit changelog generated at release).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
