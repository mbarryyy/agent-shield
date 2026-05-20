"""ADR-0013 §A4 — Email transport (console / file / smtp).

Three backends behind one ``EmailSender`` protocol:

  * ``console`` — prints text-first emails to stdout. Dev/demo only;
    REFUSED in ``enterprise`` mode (§A4) because stdout in production
    routes to log aggregators where reset/verification tokens would leak.
  * ``file`` — writes one ``.eml`` per message to ``email_file_dir``.
    Used by the integration suite + ``make integration-auth`` Mailhog-
    less fallback.
  * ``smtp`` — production transport via ``aiosmtplib`` (env-configured
    host / port / STARTTLS / auth).

Templates are text-first and contain NO marketing copy (HG#6 / §A7). Each
template renders to plaintext only; HTML alt-parts are out of v1 scope.

Import-cycle-free: depends on stdlib + aiosmtplib + the typed ``Settings``.
The ``EmailSender`` protocol is structural so tests can substitute a fake
without subclass plumbing.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Settings
from .utils import now_ms, uuidv7


@dataclass(frozen=True, slots=True)
class Message:
    """One outgoing email — fully rendered."""

    to: str
    subject: str
    body: str  # plaintext only (v1 scope per §A7)
    from_addr: str


class EmailSender(Protocol):
    async def send(self, message: Message) -> None: ...


# --- backends ----------------------------------------------------------- #


class ConsoleEmailSender:
    """stdout-printing sender (dev/demo only; REFUSED under enterprise §A4)."""

    async def send(self, message: Message) -> None:
        # Single-line preamble + body block; the integration tests grep on
        # `Subject:` so the canonical RFC-ish header is preserved here.
        print(  # noqa: T201 - intentional dev stdout
            f"\n----- shield-server[email/console] @ {now_ms()} -----\n"
            f"From: {message.from_addr}\n"
            f"To: {message.to}\n"
            f"Subject: {message.subject}\n"
            f"\n{message.body}\n"
            "----- end ----------------------------------------------\n",
            flush=True,
        )


class FileEmailSender:
    """``.eml`` file-writing sender — used by tests + Mailhog-less demos."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)

    async def send(self, message: Message) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        # RFC-822-ish canonical headers; one file per message; uuidv7 keeps
        # the directory listing chronologically ordered.
        path = self._dir / f"{uuidv7()}.eml"
        path.write_text(
            f"From: {message.from_addr}\n"
            f"To: {message.to}\n"
            f"Subject: {message.subject}\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            f"{message.body}\n",
            encoding="utf-8",
        )


class SmtpEmailSender:
    """``aiosmtplib`` sender — production transport."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool = False,
        start_tls: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._start_tls = start_tls
        self._timeout = timeout

    async def send(self, message: Message) -> None:
        # Imported lazily so non-SMTP backends don't pay the dep cost at
        # import time (the workspace pins aiosmtplib so this is harmless,
        # but keeps the module load graph clean).
        import aiosmtplib

        rfc = (
            f"From: {message.from_addr}\r\n"
            f"To: {message.to}\r\n"
            f"Subject: {message.subject}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            f"{message.body}\r\n"
        )
        await aiosmtplib.send(
            rfc,
            sender=message.from_addr,
            recipients=[message.to],
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._use_tls,
            start_tls=self._start_tls,
            timeout=self._timeout,
        )


# --- factory ------------------------------------------------------------ #


def build_email_sender(settings: Settings) -> EmailSender:
    """Resolve the configured backend; refuses ``console`` under enterprise (§A4).

    Refusal is also enforced at the app startup level (``app.create_app``);
    this factory keeps the rule honoured at construction time so a test
    that monkeypatches Settings outside the startup path still benefits.
    """
    if settings.is_enterprise and settings.email_backend == "console":
        raise RuntimeError(
            "REFUSED: SHIELD_EMAIL_BACKEND=console (stdout printer) is not "
            "permitted under SHIELD_AUTH_MODE=enterprise — set 'file' (test) "
            "or 'smtp' (prod); stdout email leakage to log aggregators would "
            "expose password-reset and email-verification tokens. (§A4)"
        )
    if settings.email_backend == "console":
        return ConsoleEmailSender()
    if settings.email_backend == "file":
        return FileEmailSender(settings.email_file_dir)
    if settings.email_backend == "smtp":
        # STARTTLS is the canonical localhost-Mailhog and most-prod path; if
        # the SMTP server uses implicit TLS the operator sets SMTP_USE_TLS=1.
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=os.environ.get("SMTP_USE_TLS", "0") == "1",
            start_tls=os.environ.get("SMTP_START_TLS", "0") == "1",
        )
    raise RuntimeError(f"unknown email backend: {settings.email_backend!r}")


# --- text-first templates (HG#6 / §A7 — no marketing copy) -------------- #


def render_password_reset(*, recipient: str, reset_url: str, ttl_minutes: int) -> Message:
    body = (
        f"A password reset was requested for {recipient}.\n\n"
        f"Open the following link within {ttl_minutes} minutes:\n\n"
        f"  {reset_url}\n\n"
        "If you did not request this, ignore this message. "
        "The link is single-use and will be invalidated upon use."
    )
    return Message(
        to=recipient,
        subject="Agent Shield — password reset",
        body=body,
        from_addr="",  # filled by build_message_for
    )


def render_email_verify(*, recipient: str, verify_url: str, ttl_minutes: int) -> Message:
    body = (
        f"Confirm the email address {recipient} for your Agent Shield account.\n\n"
        f"Open the following link within {ttl_minutes} minutes:\n\n"
        f"  {verify_url}\n\n"
        "If you did not register, ignore this message."
    )
    return Message(
        to=recipient,
        subject="Agent Shield — confirm email address",
        body=body,
        from_addr="",
    )


def render_invite(
    *, recipient: str, accept_url: str, org_name: str, role: str, ttl_minutes: int
) -> Message:
    body = (
        f"You have been invited to join the organization {org_name!r} "
        f"on Agent Shield with the role {role!r}.\n\n"
        f"Accept the invitation by opening the following link within "
        f"{ttl_minutes} minutes:\n\n"
        f"  {accept_url}\n\n"
        "If you did not expect this invitation, ignore this message."
    )
    return Message(
        to=recipient,
        subject="Agent Shield — invitation",
        body=body,
        from_addr="",
    )


def with_sender_from(message: Message, settings: Settings) -> Message:
    """Stamp the From: header with ``settings.smtp_from``."""
    from dataclasses import replace

    return replace(message, from_addr=settings.smtp_from)


# --- spawn-and-forget helper -------------------------------------------- #


def schedule_send(sender: EmailSender, message: Message) -> Awaitable[None] | asyncio.Task[None]:
    """Send synchronously inside an already-running loop, else best-effort.

    Routes call this from within a request handler so we just ``await``
    the underlying coroutine inline. Provided as a helper to keep the
    call sites tidy and centralise any future change to fire-and-forget
    semantics (which would happen if we added a background queue).
    """
    return sender.send(message)


# Suppress "Callable import unused" — re-exported for downstream typing.
_CallableMarker = Callable[..., None]
