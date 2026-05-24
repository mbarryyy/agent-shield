"""ShieldModelRouter — the one-YAML-swap zero-egress moat seam (W1-final)."""

from __future__ import annotations

import re

import pytest
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_sdk.schema import ServedVia


def test_cloud_profile_resolves_per_role() -> None:
    r = ShieldModelRouter.from_profile("cloud")
    assert r.profile == "cloud"
    assert r.for_role("defender").provider == "local"  # hot path never cloud
    assert r.for_role("defender").served_via is ServedVia.LOCAL
    ev = r.for_role("evaluator")
    assert ev.provider == "anthropic" and ev.model == "claude-sonnet-4-20250514"
    assert ev.served_via is ServedVia.CLOUD
    assert r.for_role("supervisor").model == "claude-opus-4-20250514"
    assert r.for_role("auditor").model == "claude-haiku-4-5-20251001"


def test_cloud_guardian_anthropic_models_are_dated_api_ids() -> None:
    """Cloud guardian model IDs must be real dated Anthropic API IDs.

    Do not commit placeholder aliases like ``claude-sonnet-4`` or
    ``claude-opus-4`` into the cloud profile; they can pass config parsing but
    fail only at live provider time.
    """

    r = ShieldModelRouter.from_profile("cloud")
    model_re = re.compile(r"^claude-[a-z]+-\d+(-\d+)?(-\d{8})?$")
    for role in ("evaluator", "supervisor", "auditor"):
        model = r.for_role(role).model
        assert model_re.fullmatch(model)
        assert re.search(r"-\d{8}$", model), f"{role} uses placeholder model {model!r}"


def test_local_profile_is_zero_egress_in_vpc() -> None:
    r = ShieldModelRouter.from_profile("local")
    assert r.profile == "local"
    ev = r.for_role("evaluator")
    assert ev.provider == "openai_compat"
    assert ev.model == "Qwen2.5-32B-Instruct"
    assert ev.base_url == "http://vllm.shield.svc:8000/v1"
    assert ev.served_via is ServedVia.LOCAL
    assert r.for_role("supervisor").model == "Llama-3.3-70B-Instruct"
    assert r.for_role("auditor").model == "Qwen2.5-7B-Instruct"
    # Every local LLM role points at an in-VPC base_url (no egress).
    for role in r.roles:
        rm = r.for_role(role)
        if rm.enabled and rm.provider == "openai_compat":
            assert rm.base_url is not None and rm.base_url.startswith("http://")


def test_one_yaml_swap_invariant() -> None:
    """The moat: identical role surface across profiles -> the guardian code is
    byte-identical, only the YAML differs (C5 RESOLVED / moat #7)."""
    cloud = ShieldModelRouter.from_profile("cloud")
    local = ShieldModelRouter.from_profile("local")
    assert set(cloud.roles) == set(local.roles)
    assert set(GUARDIAN_ROLES).issubset(set(cloud.roles))


def test_alignmentcheck_disabled_in_cloud_routed_in_local() -> None:
    cloud = ShieldModelRouter.from_profile("cloud")
    assert cloud.for_role("defender_llm_scanner").enabled is False
    with pytest.raises(ValueError, match="disabled"):
        cloud.model_factory("defender_llm_scanner")

    local = ShieldModelRouter.from_profile("local")
    acs = local.for_role("defender_llm_scanner")
    # Air-gap action #1: AlignmentCheck repointed off the Together default.
    assert acs.enabled is True
    assert acs.provider == "openai_compat"
    assert acs.base_url == "http://vllm.shield.svc:8000/v1"


def test_cost_hooks_served_via_and_model_id() -> None:
    cloud = ShieldModelRouter.from_profile("cloud")
    assert cloud.served_via("evaluator") is ServedVia.CLOUD
    assert cloud.model_id("evaluator") == "claude-sonnet-4-20250514"
    local = ShieldModelRouter.from_profile("local")
    assert local.served_via("evaluator") is ServedVia.LOCAL
    assert local.model_id("supervisor") == "Llama-3.3-70B-Instruct"


def test_model_factory_is_the_create_react_agent_seam() -> None:
    built: list[tuple[str, str, str | None]] = []

    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:
        built.append((resolved.provider, resolved.model, api_key))
        return {"provider": resolved.provider, "model": resolved.model}

    r = ShieldModelRouter.from_profile(
        "cloud",
        client_builders={"anthropic": fake_builder},
        environ={"ANTHROPIC_API_KEY": "test-key"},
    )
    factory = r.model_factory("evaluator")
    assert callable(factory)
    # (state, runtime) -> BaseChatModel — the verified create_react_agent shape.
    assert factory({}, object()) == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
    }
    # Lazy construction is cached per role.
    assert factory({}, object()) == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
    }
    assert built == [("anthropic", "claude-sonnet-4-20250514", "test-key")]


def test_anthropic_uses_anthropic_api_key_by_default() -> None:
    r = ShieldModelRouter(_g(evaluator={"provider": "anthropic", "model": "claude"}))
    assert r.for_role("evaluator").api_key_env == "ANTHROPIC_API_KEY"


def test_openai_compat_factory_uses_base_url_and_local_key() -> None:
    built: list[tuple[str, str, str | None, str | None]] = []

    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:
        built.append((resolved.provider, resolved.model, resolved.base_url, api_key))
        return resolved

    r = ShieldModelRouter(
        _g(
            evaluator={
                "provider": "openai_compat",
                "model": "local-model",
                "base_url": "http://127.0.0.1:8000/v1",
                "api_key_env": "SHIELD_LLM_KEY",
            }
        ),
        client_builders={"openai_compat": fake_builder},
        environ={"SHIELD_LLM_KEY": "local-key"},
    )
    client = r.model_factory("evaluator")({}, object())
    assert isinstance(client, ResolvedModel)
    assert built == [("openai_compat", "local-model", "http://127.0.0.1:8000/v1", "local-key")]


def test_unknown_role_raises() -> None:
    r = ShieldModelRouter.from_profile("cloud")
    with pytest.raises(KeyError, match="unknown role"):
        r.for_role("nope")


def test_openai_compat_requires_base_url() -> None:
    cfg = {
        "profile": "x",
        "guardians": {
            "defender": {"provider": "local", "model": "m", "served_via": "local"},
            "evaluator": {"provider": "openai_compat", "model": "m"},  # no base_url
            "supervisor": {"provider": "local", "model": "m", "served_via": "local"},
            "auditor": {"provider": "local", "model": "m", "served_via": "local"},
        },
    }
    with pytest.raises(ValueError, match="requires 'base_url'"):
        ShieldModelRouter(cfg)


def test_guardian_key_set_is_frozen() -> None:
    bad = {"profile": "x", "guardians": {"defender": {"provider": "local", "model": "m"}}}
    with pytest.raises(ValueError, match="exactly"):
        ShieldModelRouter(bad)


def test_aux_roles_cannot_redeclare_guardians() -> None:
    cfg = {
        "profile": "x",
        "guardians": {
            "defender": {"provider": "local", "model": "m", "served_via": "local"},
            "evaluator": {"provider": "local", "model": "m", "served_via": "local"},
            "supervisor": {"provider": "local", "model": "m", "served_via": "local"},
            "auditor": {"provider": "local", "model": "m", "served_via": "local"},
        },
        "aux_roles": {"defender": {"provider": "local", "model": "m"}},
    }
    with pytest.raises(ValueError, match="must not redeclare"):
        ShieldModelRouter(cfg)


def test_missing_profile_path_raises() -> None:
    with pytest.raises(FileNotFoundError):
        ShieldModelRouter.from_profile("does-not-exist")


def _g(**roles: object) -> dict[str, object]:
    base = {r: {"provider": "local", "model": "m", "served_via": "local"} for r in GUARDIAN_ROLES}
    base.update(roles)
    return {"profile": "x", "guardians": base}


def test_router_validation_edges() -> None:
    with pytest.raises(ValueError, match="'profile' is required"):
        ShieldModelRouter({"guardians": {}})
    with pytest.raises(ValueError, match="must be a mapping"):
        ShieldModelRouter(_g(defender="not-a-dict"))
    with pytest.raises(ValueError, match="provider must be one of"):
        ShieldModelRouter(_g(defender={"provider": "bogus", "model": "m"}))
    with pytest.raises(ValueError, match="'model' is required"):
        ShieldModelRouter(_g(defender={"provider": "local"}))
    with pytest.raises(ValueError, match="'aux_roles' must be a mapping"):
        ShieldModelRouter({**_g(), "aux_roles": ["nope"]})


def test_served_via_default_inferred_from_provider() -> None:
    r = ShieldModelRouter(_g(defender={"provider": "local", "model": "m"}))
    assert r.for_role("defender").served_via is ServedVia.LOCAL  # no explicit served_via


def test_from_path_and_max_tokens() -> None:
    from pathlib import Path

    cfg_dir = Path(__file__).parents[1] / "src" / "shield_governance" / "config"
    r = ShieldModelRouter.from_path(cfg_dir / "models.cloud.yaml")
    assert r.profile == "cloud"
    r2 = ShieldModelRouter(_g(evaluator={"provider": "local", "model": "m", "max_tokens": 256}))
    assert r2.for_role("evaluator").max_tokens == 256
