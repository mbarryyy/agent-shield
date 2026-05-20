"""Enterprise-auth secret-material generation (ADR-0013).

`gen.py` is invoked as a CLI from CI ("Generate ephemeral auth secrets" step
on `python-auth` / `auth-integration` jobs) and locally during onboarding.
No state, no persistence — the caller stores the printed material in an env
var, a secrets manager, or a `.env` (gitignored except `.env.example`).
"""
