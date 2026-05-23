"""ShieldModelRouter — the single source of truth for every Layer-2 LLM call.

One YAML swap (``models.cloud.yaml`` <-> ``models.local.yaml``) turns the
hardware-light cloud demo into the zero-egress, air-gapped enterprise SKU with
ZERO dependency replacement (commercial moat #7; conflict-register C5 RESOLVED).

Code-grounded seam (§5b — verified first-hand against the design-locked clones
under ``Related_Work/`` on 2026-05-19):

* **LangGraph 1.2.0** (MIT, ``langgraph/LICENSE:1``) — ``create_react_agent``'s
  ``model`` parameter accepts a
  ``Callable[[StateSchema, Runtime], BaseChatModel]`` factory
  (``langgraph/libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:278-307``).
  :meth:`ShieldModelRouter.model_factory` returns exactly that callable, so the
  guardian-node construction is byte-identical across the cloud and air-gapped
  profiles — no framework fork, no monkeypatch.
  (NOTE: in LangGraph 1.x ``create_react_agent`` is deprecated in favour of
  ``langchain.agents.create_agent``; the ``model``-factory seam is unchanged on
  both — see DRIFT note reported to team-lead.)
* **LlamaFirewall** (framework MIT, ``PurpleLlama/LlamaFirewall/LICENSE:1``) —
  ``CustomCheckScanner.api_base_url`` defaults to ``https://api.together.xyz/v1``
  (``PurpleLlama/LlamaFirewall/src/llamafirewall/scanners/custom_check_scanner.py:36``);
  the air-gap profile overrides it through this same router config (the only
  model-using scanner, AlignmentCheck — role ``defender_llm_scanner``).

W1 scope: config resolution + the cost-attribution surface (``served_via`` /
``model_id`` — master design §2.5 cost hook #2) are REAL and unit-tested. The
live ``BaseChatModel`` client is constructed lazily when the graph goes live
(W2/W3); doing so pulls langchain/langgraph (W2/W3-pinned) and is intentionally
deferred — there is no live graph at W1.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from shield_sdk.schema import ServedVia  # frozen §4 enum — imported, never redeclared

_CONFIG_DIR = Path(__file__).parent / "config"

#: The four guardian roles. Frozen as the YAML ``guardians:`` key set so the
#: one-YAML-swap invariant is mechanically checkable across both profiles.
GUARDIAN_ROLES: tuple[str, ...] = ("defender", "evaluator", "supervisor", "auditor")

_VALID_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai_compat", "local"})

#: Default transport per provider when a role omits ``served_via``.
_DEFAULT_SERVED_VIA: dict[str, ServedVia] = {
    "anthropic": ServedVia.CLOUD,
    "openai_compat": ServedVia.LOCAL,
    "local": ServedVia.LOCAL,
}


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """A fully resolved per-role model binding (one YAML row, validated)."""

    role: str
    provider: str
    model: str
    served_via: ServedVia
    base_url: str | None = None
    api_key_env: str = "SHIELD_LLM_KEY"
    temperature: float = 0.0
    max_tokens: int | None = None
    enabled: bool = True


ClientBuilder = Callable[[ResolvedModel, str | None], object]


@dataclass(frozen=True, slots=True)
class LocalModelReference:
    """Non-chat local role reference for model-free/local classifiers."""

    resolved: ResolvedModel


def _resolve(role: str, spec: object) -> ResolvedModel:
    if not isinstance(spec, dict):
        raise ValueError(f"router role {role!r}: spec must be a mapping, got {type(spec).__name__}")

    enabled = bool(spec.get("enabled", True))
    if not enabled:
        # A disabled role (e.g. AlignmentCheck off in the cloud demo) still
        # resolves so callers can introspect it; model_factory() will refuse it.
        return ResolvedModel(
            role=role,
            provider="local",
            model=str(spec.get("model", "<disabled>")),
            served_via=ServedVia.LOCAL,
            enabled=False,
        )

    provider = str(spec.get("provider", "")).strip()
    if provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"router role {role!r}: provider must be one of "
            f"{sorted(_VALID_PROVIDERS)}, got {provider!r}"
        )

    model = str(spec.get("model", "")).strip()
    if not model:
        raise ValueError(f"router role {role!r}: 'model' is required")

    raw_served = spec.get("served_via")
    served_via = (
        ServedVia(str(raw_served)) if raw_served is not None else _DEFAULT_SERVED_VIA[provider]
    )

    base_url_raw = spec.get("base_url")
    base_url = str(base_url_raw) if base_url_raw is not None else None
    if provider == "openai_compat" and not base_url:
        raise ValueError(f"router role {role!r}: provider 'openai_compat' requires 'base_url'")

    max_tokens_raw = spec.get("max_tokens")
    max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None

    default_key_env = "ANTHROPIC_API_KEY" if provider == "anthropic" else "SHIELD_LLM_KEY"

    return ResolvedModel(
        role=role,
        provider=provider,
        model=model,
        served_via=served_via,
        base_url=base_url,
        api_key_env=str(spec.get("api_key_env", default_key_env)),
        temperature=float(spec.get("temperature", 0.0)),
        max_tokens=max_tokens,
        enabled=True,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"ShieldModelRouter profile not found: {path}")
    parsed: object = yaml.safe_load(path.read_text())
    if not isinstance(parsed, dict):
        raise ValueError(f"ShieldModelRouter profile {path} must be a YAML mapping")
    return parsed


class ShieldModelRouter:
    """Resolve ``role -> ResolvedModel`` for the active deployment profile.

    Every Layer-2 LLM call (guardian nodes *and* the LlamaFirewall
    AlignmentCheck scanner) goes through this object — it is the single place
    where the cloud/air-gapped decision is made, and the single source for the
    ``model_id`` / ``served_via`` cost-attribution fields.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        client_builders: Mapping[str, ClientBuilder] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.profile: str = str(cfg.get("profile", "")).strip()
        if not self.profile:
            raise ValueError("ShieldModelRouter config: 'profile' is required")

        guardians = cfg.get("guardians")
        if not isinstance(guardians, dict) or set(guardians) != set(GUARDIAN_ROLES):
            raise ValueError(
                "ShieldModelRouter config: 'guardians' must contain exactly "
                f"{sorted(GUARDIAN_ROLES)} (got "
                f"{sorted(guardians) if isinstance(guardians, dict) else guardians!r})"
            )

        merged: dict[str, object] = dict(guardians)
        aux = cfg.get("aux_roles")
        if aux is not None:
            if not isinstance(aux, dict):
                raise ValueError("ShieldModelRouter config: 'aux_roles' must be a mapping")
            overlap = set(aux) & set(GUARDIAN_ROLES)
            if overlap:
                raise ValueError(
                    f"ShieldModelRouter config: 'aux_roles' must not redeclare "
                    f"guardian roles {sorted(overlap)}"
                )
            merged.update(aux)

        self._roles: dict[str, ResolvedModel] = {
            name: _resolve(name, spec) for name, spec in merged.items()
        }
        self._environ = environ if environ is not None else os.environ
        self._client_builders: dict[str, ClientBuilder] = {
            "anthropic": _build_anthropic_client,
            "openai_compat": _build_openai_compat_client,
            "local": _build_local_reference,
        }
        if client_builders:
            self._client_builders.update(client_builders)
        self._client_cache: dict[str, object] = {}

    # ----- constructors -------------------------------------------------- #

    @classmethod
    def from_profile(
        cls,
        profile: str,
        config_dir: Path | None = None,
        *,
        client_builders: Mapping[str, ClientBuilder] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ShieldModelRouter:
        """Load ``config/models.<profile>.yaml`` (``profile`` ∈ {cloud, local})."""
        cdir = config_dir if config_dir is not None else _CONFIG_DIR
        return cls(
            _load_yaml(cdir / f"models.{profile}.yaml"),
            client_builders=client_builders,
            environ=environ,
        )

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        client_builders: Mapping[str, ClientBuilder] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ShieldModelRouter:
        return cls(_load_yaml(path), client_builders=client_builders, environ=environ)

    # ----- resolution ---------------------------------------------------- #

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(self._roles)

    def for_role(self, role: str) -> ResolvedModel:
        try:
            return self._roles[role]
        except KeyError:
            raise KeyError(
                f"ShieldModelRouter: unknown role {role!r}; known roles: {sorted(self._roles)}"
            ) from None

    def served_via(self, role: str) -> ServedVia:
        """Cost hook #2 — ``GovernanceVerdict.reasons[].served_via``."""
        return self.for_role(role).served_via

    def model_id(self, role: str) -> str:
        """Cost hook #2 — ``GovernanceVerdict.reasons[].model_id``."""
        return self.for_role(role).model

    def model_factory(self, role: str) -> Callable[[object, object], object]:
        """Return the ``(state, runtime) -> BaseChatModel`` factory for ``role``.

        The factory returns a LangChain ``BaseChatModel`` —
        :class:`langchain_anthropic.ChatAnthropic` for the ``anthropic``
        provider, :class:`langchain_openai.ChatOpenAI` (with ``base_url``) for
        the ``openai_compat`` provider — so the result is the exact shape
        :func:`langchain.agents.create_agent` accepts as its ``model``
        argument (ADR-0009: the LangGraph 1.2.0 ``create_react_agent``
        deprecation maps to ``create_agent``). The client is built lazily on
        first invocation and cached per role, so config validation stays
        import-light. The router-backed single-prompt scaffold continues to
        invoke this same ``BaseChatModel`` via
        :class:`shield_governance.router_runtime.RouterTextClient`'s
        ``.invoke()`` / ``.ainvoke()`` shape.
        """
        resolved = self.for_role(role)
        if not resolved.enabled:
            raise ValueError(
                f"ShieldModelRouter: role {role!r} is disabled in profile "
                f"{self.profile!r}; do not construct a model for it"
            )

        def _factory(state: object, runtime: object) -> object:  # noqa: ARG001
            return self._client_for(resolved)

        return _factory

    def _client_for(self, resolved: ResolvedModel) -> object:
        cached = self._client_cache.get(resolved.role)
        if cached is not None:
            return cached
        try:
            builder = self._client_builders[resolved.provider]
        except KeyError:
            raise ValueError(
                f"ShieldModelRouter: no client builder for provider {resolved.provider!r}"
            ) from None
        api_key = self._api_key_for(resolved)
        client = builder(resolved, api_key)
        self._client_cache[resolved.role] = client
        return client

    def _api_key_for(self, resolved: ResolvedModel) -> str | None:
        value = self._environ.get(resolved.api_key_env)
        if resolved.provider == "anthropic" and not value:
            raise ValueError(
                f"ShieldModelRouter: environment variable {resolved.api_key_env!r} "
                f"is required for role {resolved.role!r}"
            )
        if resolved.provider == "openai_compat":
            return value or "local-no-key"
        return value


def _build_anthropic_client(resolved: ResolvedModel, api_key: str | None) -> object:
    """Return a ``langchain_anthropic.ChatAnthropic`` LLM (a ``BaseChatModel``).

    Phase B / ADR-0009 swap: the factory used to return the raw
    ``anthropic.Anthropic`` SDK client (incompatible with ``create_agent``);
    it now returns a LangChain chat model so the same router-backed seam can
    be consumed by either ``RouterTextClient.invoke()`` (single-prompt
    scaffold) or :func:`langchain.agents.create_agent` (real LLM agent).
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("langchain-anthropic is not installed") from exc
    kwargs: dict[str, object] = {
        "model": resolved.model,
        "api_key": api_key,
        "temperature": resolved.temperature,
    }
    if resolved.max_tokens is not None:
        kwargs["max_tokens"] = resolved.max_tokens
    return ChatAnthropic(**kwargs)


def _build_openai_compat_client(resolved: ResolvedModel, api_key: str | None) -> object:
    """Return a ``langchain_openai.ChatOpenAI`` LLM (a ``BaseChatModel``).

    The ``base_url`` channel keeps the vLLM / OpenAI-compatible local-SKU
    path intact (moat #7 air-gap deploys still work), only the wire layer
    moves from the raw ``openai.OpenAI`` SDK to the LangChain chat model.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("langchain-openai is not installed") from exc
    kwargs: dict[str, object] = {
        "model": resolved.model,
        "api_key": api_key or "local-no-key",
        "base_url": resolved.base_url,
        "temperature": resolved.temperature,
    }
    if resolved.max_tokens is not None:
        kwargs["max_tokens"] = resolved.max_tokens
    return ChatOpenAI(**kwargs)


def _build_local_reference(resolved: ResolvedModel, api_key: str | None) -> object:
    return LocalModelReference(resolved=resolved)
