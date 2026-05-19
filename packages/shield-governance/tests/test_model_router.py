"""ShieldModelRouter — the one-YAML-swap zero-egress moat seam (W1-final)."""

from __future__ import annotations

import pytest
from shield_governance.model_router import GUARDIAN_ROLES, ShieldModelRouter
from shield_sdk.schema import ServedVia


def test_cloud_profile_resolves_per_role() -> None:
    r = ShieldModelRouter.from_profile("cloud")
    assert r.profile == "cloud"
    assert r.for_role("defender").provider == "local"  # hot path never cloud
    assert r.for_role("defender").served_via is ServedVia.LOCAL
    ev = r.for_role("evaluator")
    assert ev.provider == "anthropic" and ev.model == "claude-sonnet-4"
    assert ev.served_via is ServedVia.CLOUD
    assert r.for_role("supervisor").model == "claude-opus-4"
    assert r.for_role("auditor").model == "claude-haiku-4"


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
    assert cloud.model_id("evaluator") == "claude-sonnet-4"
    local = ShieldModelRouter.from_profile("local")
    assert local.served_via("evaluator") is ServedVia.LOCAL
    assert local.model_id("supervisor") == "Llama-3.3-70B-Instruct"


def test_model_factory_is_the_create_react_agent_seam() -> None:
    r = ShieldModelRouter.from_profile("cloud")
    factory = r.model_factory("evaluator")
    assert callable(factory)
    # (state, runtime) -> BaseChatModel — the verified create_react_agent shape.
    with pytest.raises(NotImplementedError, match="W2/W3"):
        factory({}, object())


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
