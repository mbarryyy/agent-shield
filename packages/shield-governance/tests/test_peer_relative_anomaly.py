"""Wave-2 chunk #3b: deterministic ``peer_relative_anomaly`` (no LLM, no key).

governance_design §3.2: XG-Guard adaptive-prototype idea re-done training-free —
cosine distance of the record embedding to the session's running-mean (centroid)
embedding; flag when the distance exceeds a deterministic threshold. Reuses the
existing ``_cosine`` / ``_centroid`` / ``_record_text`` helpers + the local
``DeterministicHashEmbedder`` (so it is fully offline and deterministic).
"""

from __future__ import annotations

from shield_governance.evaluator import (
    PeerRelativeAnomaly,
    peer_relative_anomaly,
)
from shield_sdk.schema import ActionPayload, Phase, ShieldActionRecord


def _record(
    tool: str, *, recipient: str, amount: float, run_id: str = "peer-run"
) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id=run_id,
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name=tool,
            tool_args={"recipient": recipient, "amount": amount},
        ),
    )


def test_peer_relative_anomaly_empty_session_not_anomalous() -> None:
    result = peer_relative_anomaly(_record("send_money", recipient="a", amount=100.0), [])
    assert isinstance(result, PeerRelativeAnomaly)
    assert result.anomalous is False
    assert result.baseline_count == 0
    assert result.distance == 0.0


def test_peer_relative_anomaly_single_record_session_handles_gracefully() -> None:
    session = [_record("send_money", recipient="a", amount=100.0)]
    result = peer_relative_anomaly(_record("send_money", recipient="a", amount=100.0), session)
    assert result.baseline_count == 1
    # Same content as the only baseline → near-zero distance, not anomalous.
    assert result.anomalous is False
    assert 0.0 <= result.distance <= 1.0


def test_peer_relative_anomaly_close_record_not_anomalous() -> None:
    session = [
        _record("send_money", recipient="a", amount=100.0),
        _record("send_money", recipient="a", amount=100.0),
        _record("send_money", recipient="a", amount=100.0),
    ]
    current = _record("send_money", recipient="a", amount=100.0)
    result = peer_relative_anomaly(current, session)
    assert result.anomalous is False
    assert result.distance < result.threshold


def test_peer_relative_anomaly_divergent_record_is_anomalous() -> None:
    # Session is all small same-recipient transfers; current is a totally
    # different tool + recipient + args → far from the session centroid.
    session = [
        _record("send_money", recipient="alice", amount=10.0),
        _record("send_money", recipient="alice", amount=12.0),
        _record("send_money", recipient="alice", amount=11.0),
    ]
    current = _record("update_password", recipient="zzz-attacker", amount=999999.0)
    result = peer_relative_anomaly(current, session)
    assert result.anomalous is True
    assert result.distance >= result.threshold
    assert result.baseline_count == 3


def test_peer_relative_anomaly_respects_configured_threshold() -> None:
    session = [
        _record("send_money", recipient="alice", amount=10.0),
        _record("send_money", recipient="bob", amount=5000.0),
    ]
    current = _record("read_file", recipient="x", amount=1.0)
    strict = peer_relative_anomaly(current, session, threshold=0.0)
    lax = peer_relative_anomaly(current, session, threshold=1.0)
    # threshold=0.0 → any positive distance is anomalous; threshold=1.0 → never.
    assert strict.anomalous is True
    assert lax.anomalous is False


def test_peer_relative_anomaly_score_is_bounded() -> None:
    session = [_record("send_money", recipient="a", amount=1.0)]
    result = peer_relative_anomaly(_record("send_money", recipient="b", amount=2.0), session)
    assert 0.0 <= result.distance <= 1.0
    assert 0.0 <= result.score <= 1.0
