# ADR-0013 — Enterprise Auth v1

- **Status**: Accepted — 2026-05-20
- **Authors**: Jiawei Yang
- **Supersedes**: dev-auth-open prototype posture (`packages/shield-server/src/shield_server/auth.py:3-4` / `config.py:3-5`); the `/v1/auth/token` stub at `packages/shield-server/src/shield_server/routes/__init__.py:352-358`.

## Context

W3 closed at integrated `main` `48a9707` with `[reviewer G3-GATE] = G3 PASS`. The single-tenant dev-auth-open prototype auth posture (auth.py explicitly declares Better-Auth + 5-role RBAC discarded for the prototype; `SHIELD_DEV_AUTH=open` is the default) is replaced with **enterprise-grade real authentication on our own Python/FastAPI server**. Better-Auth (Node) is rejected: architectural mismatch with the Python stack; wire-shape leakage of Node assumptions; no value over a clean own design that we maintain ourselves.

## Decision — Architecture (13 items, unanimous across server / sdk / console / w0-scaffolder)

1. **Own clean `/v1/auth/*` wire-shape**, not better-auth-wire-compatible.
2. **Strict orthogonality.** Human session = HttpOnly Secure SameSite=Lax cookie + server-side `sessions` table + CSRF double-submit `X-CSRF-Token` header. SDK programmatic = `Authorization: Bearer as_live_<≥32B b64url>`. Ingest endpoints `/v1/governance/decide` + `/record` accept Bearer api-key **only** (humans cannot ingest §4 records); other routes accept the session cookie **only**. Enforced at the FastAPI dep layer via default-deny `require_role(...)`. The two paths never cross.
3. **Server-authoritative opaque sessions in PostgreSQL**, not JWT. Instant revocation; no `alg` pitfalls; no refresh-on-hot-path conflicts with the /decide 500 ms budget (`master_design §2.3` / ADR-0004).
4. **argon2id** passwords via `argon2-cffi` (direct, env-tunable, capped per §A1) + server-side **pepper** (`SHIELD_PASSWORD_PEPPERS` list with rotation; lazy re-hash at login).
5. **5-role RBAC** (`org_owner`, `security_admin`, `integration_engineer`, `compliance_auditor`, `readonly_investigator`) enforced via `Depends(require_role(...))` on the existing `Ctx` seam at `routes:56`. Server is authoritative; console reflects.
6. **`SHIELD_AUTH_MODE = {open, enterprise, api_token_only}`.** `open` is the CI default → W3's 314 tests stay green unmodified, zero regression. `enterprise` is the production default. Production refuses to start in `open` mode without the explicit `--allow-open-auth` CLI flag (§A3).
7. **§4 contract UNCHANGED**; no ADR-0007 ritual. All new tables are ADDITIVE idempotent (`CREATE TABLE IF NOT EXISTS`); no FK back-refs into W3 tables (`agents`, `agent_keys`, `operations`, `receipts`, `epochs`, `exports`, `agent_sessions`, `intervention_log`, `governance_verdicts` are schema-unchanged and byte-identity-preserved).
8. **CSRF** = double-submit (`sessions.csrf_token` random 32 B returned only in the `GET /v1/auth/session` JSON body; required as `X-CSRF-Token` header on all state-changers; `hmac.compare_digest` constant-time, §A10).
9. **Rate-limit + brute-force protection** = `slowapi` (Redis sliding-window, IP-level) + DB account lockout (5/10/20/30 min exponential, `SELECT … FOR UPDATE` race-safe, audit emitted BEFORE lock).
10. **Account-enumeration safety** = sign-up / sign-in / forgot-password failure always returns `401 invalid_credentials`; the true reason is recorded only in `audit_log_auth`.
11. **Bootstrap** via CLI `shield-server seed-admin --email --org` (no first-request race for the first owner). Enterprise mode hides `/register`; only `/accept-invite?token=` is exposed.
12. **Email transport** `SHIELD_EMAIL_BACKEND = {console, file, smtp}`. `console` (stdout URLs) is dev/demo only and is REFUSED in `enterprise` mode (§A4). `file` is test; `smtp` is production. Mailhog runs as the 5th compose service for the `auth-integration` CI job.
13. **TOTP at rest** = `cryptography.fernet.MultiFernet` over `SHIELD_AUTH_FERNET_KEYS` list (rotation per §A6). KMS-backed TOTP is v1.x for cloud SKUs.

## Decision — User-signed (8 items, 2026-05-20)

**D1.** Tri-mode api-keys schema `api_keys(org_id NOT NULL, agent_id NULLABLE, agent_id_allowlist TEXT[])`. UI default = org-wide; one-click tighten. Server cross-checks `record.agent_id ∈ effective_scope` at ingest (§A8); SDK cannot enforce.
**D2.** 2FA forced for `org_owner` and `security_admin` at first sign-in AND at role-upgrade (§A9); other roles opt-in via `/settings/account`. v1.x adds the per-org all-hands toggle.
**D3.** NO JWT in v1. Sessions are server-side cookies; SDK uses opaque Bearer api-key.
**D4.** WebAuthn / passkeys → v1.1 (separate ADR; schema name `webauthn_credentials` reserved). SCIM / SAML SSO → v2.
**D5.** Bootstrap = CLI `shield-server seed-admin` (no auto-org_owner on first request).
**D6.** Magic-link / passwordless and OAuth provider login (Google, GitHub, …) → v2.
**D7.** PII / GDPR retention policy memo → W4 compliance. Reserve `audit_log_auth.created_at` index for future purge.
**D8.** Branch-protection required checks 7 → 10 (`+python-auth (3.11)`, `+python-auth (3.12)`, `+auth-integration`).

## Addendum (post-design-§5b)

### §A1 — argon2id parameter caps (closes RC#1)

| Env var | Default | Hardcoded cap (not env-tunable) | Rationale |
|---|---|---|---|
| `SHIELD_ARGON2_MEMORY_COST_KIB` | 65536 (64 MiB) | **262144 (256 MiB)** | Per-request memory budget |
| `SHIELD_ARGON2_TIME_COST` | 3 | **8** | Per-hash latency budget |
| `SHIELD_ARGON2_PARALLELISM` | 4 | **8** | Per-hash CPU budget |

Values exceeding any cap cause `RuntimeError` and refuse-to-start. Misconfigured `m=4 GiB t=100 p=64` becomes a fail-loud startup error, not a one-request DoS.

### §A2 — `SHIELD_AUTH_MODE=open` dep-layer contract + CI assertion (closes RC#2)

In `open` mode the `Ctx` / `require_role(...)` dep **auto-injects a synthetic `dev_principal`** populated with `org_id="demo-org"`, `user_id="dev-principal"`, `roles={org_owner, security_admin, integration_engineer, compliance_auditor, readonly_investigator}`, `auth_kind="open"`. The dep ALWAYS executes; routes uniformly receive a populated `Ctx.principal`. No "naked" handlers without `Ctx` or `require_role(...)` are permitted.

CI assertion (runs under both `python-auth` and `auth-integration` jobs):

```python
def test_every_route_declares_auth_dep(app):
    """No route may bypass auth deps; open mode permits-everyone via synthetic
    dev_principal, enterprise enforces real auth; naked routes leak through both."""
    for route in app.routes:
        deps = collect_dependencies(route)
        assert any(d.dependency in {auth_context, require_role} for d in deps), \
            f"{route.path} {route.methods} missing auth dep — would bypass both modes"
```

### §A3 — `--allow-open-auth` is CLI-only + loud startup audit (closes RC#3)

The flag is **argparse-only** in the `shield-server` entrypoint. **NOT** read from any env var, Docker-env default, or config file. Startup:

```python
if mode == "open":
    if not args.allow_open_auth:
        sys.exit("REFUSED: SHIELD_AUTH_MODE=open requires explicit --allow-open-auth CLI flag")
    sys.stderr.write(
        "WARNING: shield-server starting in SHIELD_AUTH_MODE=open — all requests "
        "resolve to a synthetic dev_principal with all roles. NEVER USE IN PROD.\n"
    )
    await audit_log_auth.insert(event="STARTED_IN_OPEN_MODE",
        detail={"hostname": ..., "pid": ..., "argv": redacted_argv()})
```

### §A4 — `SHIELD_EMAIL_BACKEND=console` is dev-only (closes RC#4)

```python
if mode == "enterprise" and email_backend == "console":
    sys.exit("REFUSED: SHIELD_EMAIL_BACKEND=console (stdout printer) is not permitted "
             "under SHIELD_AUTH_MODE=enterprise — set 'file' (test) or 'smtp' (prod); "
             "stdout email leakage to log aggregators would expose password-reset "
             "and email-verification tokens.")
```

### §A5 — Down migrations are CI-fire-drill-only (closes RC#5)

`migrate.py` runner has NO public `down` subcommand. Down is invoked only by the test harness via internal `_apply_down(rev)`. The runbook forbids running down in production.

CI fire-drill comparison invariant (W3 byte-identity, not just count):

```python
W3_PROTECTED_TABLES = ("agents", "agent_keys", "operations", "receipts", "epochs",
                       "exports", "agent_sessions", "intervention_log", "governance_verdicts")

for t in W3_PROTECTED_TABLES:
    assert post_down.row_count(t) == pre_up.row_count(t), f"row count drift in {t}"
    assert post_down.row_checksum(t) == pre_up.row_checksum(t), f"row checksum drift in {t}"
# row_checksum(t) = SHA-256 of sorted serialization of all rows.
# Count alone is insufficient — a silent UPDATE on existing rows would slip through.
```

### §A6 — Fernet key rotation via MultiFernet list (closes RC#6)

`SHIELD_AUTH_FERNET_KEYS` is a list in the same shape as `SHIELD_SESSION_SECRETS` / `SHIELD_PASSWORD_PEPPERS`: `k1:<base64url(32B)>,k2:…`. Implementation uses `cryptography.fernet.MultiFernet`:

- `MultiFernet([Fernet(decode_b64url(k)) for k in keys])`.
- Encryption always uses the FIRST (active) key.
- Decryption is tried against all keys in order.
- On successful decryption with a non-active key, the TOTP credential row is lazily re-encrypted with the active key and persisted (next TOTP setup-or-verify cycle).
- Rotation procedure: prepend new key → redeploy → wait ≥ 90 days (longest TOTP-active period) → remove the old key → redeploy.

### §A7 — "v1 IS / v1 IS NOT" honesty scope (closes RC#7; HG#6-anchored)

Console copy, documentation, README, marketing material MUST conform. Deviation is an HG#6 violation. The ADR-anchored scope is authoritative; product / console / docs derive from it.

**v1 IS** (genuine, shipped):

- Email + password authentication (argon2id + server-side pepper, capped per §A1).
- TOTP-based 2FA (TOTP + 10 recovery codes; per-user opt-in; **forced for `org_owner` and `security_admin` at first sign-in AND at role-upgrade** per §A9).
- Server-authoritative opaque sessions in PostgreSQL (instant revocation; HttpOnly Secure SameSite=Lax cookie; CSRF double-submit `X-CSRF-Token` header constant-time-compared, §A10).
- SDK programmatic auth via long-lived opaque Bearer api-key (`as_live_*` / `as_test_*` prefixes; SHA-256 stored; tri-mode scoping per §A8).
- 5-role RBAC, server-authoritative.
- Account lockout (exponential 5/10/20/30 min, `SELECT … FOR UPDATE` race-safe, audit-before-lock).
- Account-enumeration safety (uniform 401, true reason only in `audit_log_auth`).
- Email-driven password reset + email verification + invite-only signup (enterprise mode hides `/register`; only `/accept-invite?token=`).
- CLI `shield-server seed-admin` bootstrap.
- Audit log of every auth event (`audit_log_auth`, mirrors `intervention_log:110` SINK pattern).

**v1 IS NOT** (deferred — MUST NOT be claimed in any copy / UI / marketing):

- SSO (SAML / OIDC) → **v2** (separate ADR).
- SCIM provisioning → **v2**.
- WebAuthn / passkeys → **v1.1** (separate ADR; `webauthn_credentials` schema name reserved).
- Per-org all-hands 2FA mandate (admin-only forced in v1) → **v1.x**.
- Magic-link / passwordless login → **v2**.
- OAuth provider login (Google, GitHub, …) → **v2**.
- KMS-backed TOTP secret (Fernet list rotation in v1) → **v1.x** (cloud SKU).
- Multi-org-per-user UI switcher (schema supports; UI single-org) → **v1.x**.

The CONSOLE-W3 "Pre-release" notice template is the visual reference for future "coming soon" disclosures.

**§A7.1 addendum (brand-cleanup follow-up):** the `console/src/components/ui/Sidebar.tsx` `Home` and `Docs` external links use the placeholder URLs `https://agent-shield.com` and `https://docs.agent-shield.com` — these domains are **not yet registered/live**. Status mirrors the unpublished SDK packages: in scope of the "v1 IS NOT" public-distribution surface. A `TODO(pre-release)` comment marks the swap point; switch to live URLs when distribution ships.

### §A8 — D1/O7 cross-check predicate + mandated security test (additional flag)

Server `/v1/governance/decide` + `/record` ingest evaluates fail-closed in order BEFORE accepting the §4 record:

```python
def authorize_ingest(principal: ApiKeyPrincipal, record: ShieldActionRecord) -> AuthzResult:
    # Clause 1: org match — NON-NEGOTIABLE
    if principal.org_id != record.org_id:
        return Deny(reason="record_org_mismatch", http=403)
    # Clauses 2-4: tri-mode scoping per D1
    key = principal.api_key
    if key.agent_id is None and key.agent_id_allowlist is None:
        # org-wide: any agent within principal's org
        if record.agent_id not in storage.agents_in_org(principal.org_id):
            return Deny(reason="agent_outside_org", http=403)
        return Allow()
    if key.agent_id is not None:
        # single-agent scope
        if record.agent_id != key.agent_id:
            return Deny(reason="agent_outside_key_scope", http=403)
        return Allow()
    # key.agent_id_allowlist set
    if record.agent_id not in key.agent_id_allowlist:
        return Deny(reason="agent_outside_allowlist", http=403)
    return Allow()
```

Mandated security tests at `tests/integration/auth/test_api_key_scope.py`:

- (a) Issue an org-wide key for org A; ingest a record claiming `agent_id` from org B → 403 `record_org_mismatch`.
- (b) Issue an `agent_id_allowlist=[agent_x, agent_y]` key; ingest a record with `agent_id=agent_z` (same org) → 403 `agent_outside_allowlist`.
- (c) Issue an `agent_id=agent_x` key; ingest a record with `agent_id=agent_y` → 403 `agent_outside_key_scope`.
- (d) Issue an org-wide key; ingest a valid record → 200 verdict.
- (e) Orthogonality cross-check: the record's Ed25519 signature still verifies via `canonical.verify_record` independently of the api-key (proves D1 + sdk-builder S5 Ed25519 orthogonality).

### §A9 — D2 2FA enforcement keyed on current admin role (additional flag)

2FA is enforced based on the **current admin role at request time**, not the first-sign-in moment.

```python
def require_2fa_if_admin(ctx: Ctx = Depends(...)) -> Ctx:
    if ctx.principal.role in {"org_owner", "security_admin"} and not ctx.principal.user.totp_enabled:
        raise HTTPException(403, detail={"code": "totp_setup_required",
                                         "redirect": "/settings/2fa-setup?force=admin_role"})
    return ctx
```

On role-upgrade via `POST /v1/auth/admin/users/{id}/role`, the upgraded user's NEXT request hits the dep and is forced into TOTP setup. The console catches the 403 + `totp_setup_required` and redirects accordingly. A user demoted out of admin retains the TOTP credential but is no longer forced (and may disable via `/v1/auth/totp/disable` requiring current password + code).

### §A10 — CSRF double-submit transport separation (additional flag)

- `session_id` (opaque random 48 B URL-safe) is the value of the `shield_session` cookie. Attributes: `HttpOnly; Secure (enterprise mode); SameSite=Lax; Path=/; Max-Age=sliding 7d`. **Not readable by JS.**
- `sessions.csrf_token` (independent random 32 B) is returned **only in the JSON response body of `GET /v1/auth/session`**. Readable by JS.
- All state-changing requests (POST / PATCH / PUT / DELETE) MUST echo `csrf_token` in the `X-CSRF-Token` header.
- Server validates via `hmac.compare_digest` (constant-time).
- The cookie body NEVER contains `csrf_token` — that would collapse double-submit into single-submit.

### §A11 — `api_token_only` mode isolation (additional flag)

`SHIELD_AUTH_MODE=api_token_only` preserves the legacy `SHIELD_API_TOKEN` bearer flow for back-compat with pre-tri-mode-api-key deployments. This mode:

- Only accepts `Authorization: Bearer <SHIELD_API_TOKEN>`.
- Resolves all requests to a synthetic principal `(org_id="demo-org", role=org_owner, auth_kind="api_token_only")`.
- Does NOT mount session-cookie routes (`/v1/auth/sign-in`, `/v1/auth/session`, etc. return 404). The console cannot operate.
- Marked for removal at v2; the migration guide instructs operators to switch to `enterprise` and provision a real tri-mode api-key.

## Consequences

- New deps in `shield-server`: `argon2-cffi`, `pyotp`, `slowapi`, `aiosmtplib`, `cryptography`, `qrcode`.
- New deps in `console`: `vitest`, `@testing-library/{react,jest-dom,user-event}`, `jsdom`, `msw`, `@playwright/test`, `qrcode`. Removed dep: `better-auth` (whole plugin chain).
- New PostgreSQL tables (`schema_versions` 4–5): `users`, `sessions`, `memberships`, `password_reset_tokens`, `email_verification_tokens`, `totp_credentials`, `invites`, `api_keys`, `audit_log_auth`.
- Console: 13 UI surfaces (login + `/login/2fa` + `/accept-invite` + `/forgot-password` + `/password-reset` + `/verify-email` + `/settings/account` + `/settings/2fa-setup` + `/settings/team` + session-expired modal + sign-out + governance/incidents RBAC gate + Sidebar nav RBAC). Test stack (Vitest + RTL + MSW + Playwright) closes the W3 G3-NOTE no-console-tests tracked-debt.
- SDK: one optional `ShieldClient.api_key` ctor kwarg + one persistent httpx header. ZERO §4 contract change; ZERO `ShieldElementConfig` change.
- CI: branch-protection 7 → 10 required checks.

## Alternatives considered

- **Better-Auth (Node library)** — REJECTED: cross-runtime mismatch (Node lib, Python server). Either a Node sidecar (operational complexity) or reimplementing the better-auth wire protocol in Python — which is "writing our own" with extra constraints, no value.
- **JWT sessions** — REJECTED: revocation cost (revocation list or token introspection); `alg=none` and key-confusion class of bugs; refresh-on-hot-path conflicts with the /decide 500 ms budget.
- **OAuth client-credentials for SDK** — REJECTED: token-fetch round-trip per refresh adds latency; daemon services do not need session semantics.
- **Authlib / Authentik / Ory Kratos** — out-of-process; deployment complexity; wire-shape we do not control.
- **Passlib facade over argon2** — `argon2-cffi` direct is one fewer indirection.

## References

- W1 ADR-0007 — §4 v1.1 freeze ritual.
- master_design §2.3 — /decide 500 ms latency budget.
- ADR-0004 — Channel-1 governance gate.
- CONSOLE-W3 Flag-1 — pre-release-honesty discipline (carried forward into §A7).
- OWASP Password Storage Cheat Sheet 2024 — argon2id m=64 MiB t=3 p=4.
- RFC 6750 — Bearer Token Usage.
- W3 [reviewer G3-GATE] verdict (integrated `main` `48a9707`).
