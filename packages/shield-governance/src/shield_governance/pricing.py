"""Per-model token pricing for REAL guardian cost attribution.

Guardian evidence (``GuardianEvidence.cost_usd``) must carry the *actual*
dollar cost of a model call, not a hardcoded ``0.0``. This module owns the
small, in-repo, public price table the router-backed guardians use to turn
measured ``prompt_tokens`` / ``completion_tokens`` into ``cost_usd``.

Prices are public list prices in USD per million tokens (MTok), keyed by the
exact ``model_id`` the :class:`~shield_governance.model_router.ShieldModelRouter`
resolves per role. They are **not secrets**. The Haiku row is the rate the
release-readiness budget guard documents (input ``$1`` / output ``$5`` per
MTok); the Sonnet / Opus rows are the corresponding public Anthropic list
prices for the pinned guardian snapshots.

``served_via == ServedVia.LOCAL`` means the model runs in-VPC on the customer's
own hardware (the air-gapped SKU); there is no per-token provider charge, so the
marginal ``cost_usd`` is ``0.0`` regardless of token count. That ``0.0`` is a
*real* measured economic fact (the local-serving moat), not a placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass

from shield_sdk.schema import ServedVia

#: Provenance for the rates below — surfaced so reports can label cost ESTIMATED
#: vs MEASURED with a citable basis (release-readiness budget guard + public
#: Anthropic list prices for the pinned guardian model snapshots).
PRICE_BASIS = "anthropic-public-list-usd-per-mtok-2026-05"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Public list price for one model, in USD per million tokens."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float


#: Cloud (Anthropic) per-MTok list prices keyed by the exact ``model_id`` the
#: router resolves for each guardian role (see ``config/models.cloud.yaml``):
#: evaluator=claude-sonnet-4-6, supervisor=claude-opus-4-7,
#: auditor=claude-haiku-4-5-20251001. Public prices, not secrets.
CLOUD_PRICE_TABLE_USD_PER_MTOK: dict[str, ModelPrice] = {
    "claude-haiku-4-5-20251001": ModelPrice(1.0, 5.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-opus-4-7": ModelPrice(15.0, 75.0),
}


def cost_usd(
    *,
    model_id: str | None,
    served_via: ServedVia | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return the REAL USD cost of a guardian model call.

    * ``served_via == ServedVia.LOCAL`` → ``0.0`` (in-VPC open-weight serving
      has no per-token provider charge; the local-moat marginal cost IS zero).
    * Cloud models priced from :data:`CLOUD_PRICE_TABLE_USD_PER_MTOK`.

    An unknown cloud ``model_id`` raises :class:`UnknownModelPriceError` rather
    than silently returning ``0.0`` — a missing price is a real gap to fix, not
    a free call to fabricate (charter R1: no silent fallbacks).
    """
    if served_via is ServedVia.LOCAL:
        return 0.0
    if model_id is None:
        raise UnknownModelPriceError(model_id)
    try:
        price = CLOUD_PRICE_TABLE_USD_PER_MTOK[model_id]
    except KeyError:
        raise UnknownModelPriceError(model_id) from None
    return (prompt_tokens / 1_000_000.0) * price.input_usd_per_mtok + (
        completion_tokens / 1_000_000.0
    ) * price.output_usd_per_mtok


class UnknownModelPriceError(KeyError):
    """Raised when a cloud ``model_id`` has no entry in the price table."""

    def __init__(self, model_id: str | None) -> None:
        self.model_id = model_id
        super().__init__(
            f"no price-table entry for cloud model_id {model_id!r}; "
            "add it to CLOUD_PRICE_TABLE_USD_PER_MTOK (public list price)"
        )
