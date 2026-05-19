"""AgentDojo defense entrypoint shim.

W0 STUB. NOTE (ADR-0005 / C9): the AgentDojo `--defense agent_shield
--module-to-load shield_sdk.defense` CLI path is code-verified NON-FUNCTIONAL
for a custom defense (DEFENSES is a static module-level literal bound by
click.Choice at import, before --module-to-load runs; no register_defense
hook; from_config raises ValueError). The Shield arm is wired PROGRAMMATICALLY
by the custom runner `python -m shield_eval.run_ab`, NOT via this CLI path.
This module exists only so the dead instruction has a documented home.
"""

from __future__ import annotations
