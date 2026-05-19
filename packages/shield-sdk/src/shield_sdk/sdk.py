"""Free SDK client: create -> sign -> submit, in-memory chain, two-phase API.

W0 STUB. Real client (sync POST /v1/governance/decide, 500 ms
concurrent.futures fail policy) is built at W2 by sdk-builder.
"""

from __future__ import annotations

from .schema import GovernanceVerdict, ShieldActionRecord


class ShieldClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def decide(self, record: ShieldActionRecord) -> GovernanceVerdict:
        raise NotImplementedError("W2: sync /v1/governance/decide round-trip")  # pragma: no cover
