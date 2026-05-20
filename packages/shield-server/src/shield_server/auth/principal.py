"""Principal — the enterprise-auth identity object resolved by the dep layer.

ADR-0013 §A2: in ``open`` mode the dep layer auto-injects a **synthetic**
``dev_principal`` populated with the demo org and all 5 roles; in ``enterprise``
mode it carries the resolved user + role + session; in ``api_token_only`` mode
it carries a fixed legacy-bearer principal. The dep ALWAYS executes — routes
uniformly receive a populated principal, regardless of mode.

This module is import-cycle-free: it depends ONLY on stdlib + the typed Role /
AuthKind aliases. The dep layer (``auth/dep.py``) consumes it; submodules
(api_keys, sessions, users) construct instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# 5-role RBAC enum (verbatim from ADR-0013 §2 + §A7).
Role = Literal[
    "org_owner",
    "security_admin",
    "integration_engineer",
    "compliance_auditor",
    "readonly_investigator",
]

# Authority kind. ``open`` is the synthetic-dev-principal mode; ``session`` is
# the cookie-bound human session (§A10); ``api_key`` is a tri-mode SDK Bearer
# key (D1/§A8); ``api_token_only`` is the legacy single-token path (§A11).
AuthKind = Literal["open", "session", "api_key", "api_token_only"]

ALL_ROLES: tuple[Role, ...] = (
    "org_owner",
    "security_admin",
    "integration_engineer",
    "compliance_auditor",
    "readonly_investigator",
)


@dataclass(frozen=True, slots=True)
class Principal:
    """The unified identity object the dep layer hands to every route.

    ``roles`` is a frozenset for membership tests; ``role`` is the SINGLE
    primary role used by ``require_role`` and ``require_2fa_if_admin``. In
    ``open`` mode ``roles == ALL_ROLES`` (synthetic) and ``role == "org_owner"``
    so any RBAC-gated route admits the synthetic dev_principal — preserving
    the W3 314-test default behaviour byte-identically.

    ``api_key_*`` fields are populated only when ``auth_kind == "api_key"``;
    they carry the tri-mode (D1/§A8) scoping that ``authorize_ingest`` reads.
    """

    org_id: str
    user_id: str
    role: Role
    auth_kind: AuthKind
    roles: frozenset[Role] = field(default_factory=frozenset)
    session_id: str | None = None
    email: str | None = None
    totp_enabled: bool = False
    # api_key tri-mode scoping (§A8 D1) — only meaningful when auth_kind="api_key".
    api_key_id: str | None = None
    api_key_agent_id: str | None = None
    api_key_agent_id_allowlist: tuple[str, ...] | None = None

    @property
    def is_admin(self) -> bool:
        """§A9 admin check — ``role`` ∈ {org_owner, security_admin}."""
        return self.role in ("org_owner", "security_admin")

    @property
    def is_open_synthetic(self) -> bool:
        return self.auth_kind == "open"

    @property
    def is_session(self) -> bool:
        return self.auth_kind == "session"

    @property
    def is_api_key(self) -> bool:
        return self.auth_kind == "api_key"

    def has_role(self, *roles: Role) -> bool:
        """Membership check against ``roles`` set (open-mode admits any)."""
        return bool(self.roles.intersection(roles))


def synthetic_dev_principal(org_id: str) -> Principal:
    """ADR-0013 §A2: the open-mode synthetic principal.

    All 5 roles → any ``require_role`` dep admits it. ``role="org_owner"``
    keeps ``require_2fa_if_admin`` semantics meaningful in open mode while
    still gated by ``totp_enabled=False`` (the open-mode synthetic never has
    TOTP enabled — admin-only routes in open mode would 403 with
    ``totp_setup_required`` if §A9 ran in open. The dep short-circuits §A9
    when ``is_open_synthetic`` for back-compat with W3 tests).
    """
    return Principal(
        org_id=org_id,
        user_id="dev-principal",
        role="org_owner",
        auth_kind="open",
        roles=frozenset(ALL_ROLES),
        session_id=None,
        email="dev@shield.local",
        totp_enabled=False,
    )


def api_token_only_principal(org_id: str) -> Principal:
    """ADR-0013 §A11: the legacy ``SHIELD_API_TOKEN`` principal.

    ``role=org_owner`` so all RBAC-gated routes admit it (back-compat with
    pre-tri-mode-api-key deployments). Console session routes are NOT mounted
    under this mode — the principal NEVER reaches a session-cookie route.
    """
    return Principal(
        org_id=org_id,
        user_id="api-token-principal",
        role="org_owner",
        auth_kind="api_token_only",
        roles=frozenset(ALL_ROLES),
        totp_enabled=False,
    )


__all__ = [
    "ALL_ROLES",
    "AuthKind",
    "Principal",
    "Role",
    "api_token_only_principal",
    "synthetic_dev_principal",
]
