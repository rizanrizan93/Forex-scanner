from fx_scanner.demo_adaptive_gate_v2 import (
    CompositeAdaptiveScorePolicy,
    build_adaptive_gate_v2_policy,
)


class LegacyPolicy:
    def required_score(self, row):
        return 55.01


def _closed_loss():
    return {
        "payload": {
            "symbol": "SOLUSD",
            "setup_type": "TREND_CONTINUATION",
            "direction": "LONG",
            "regime": "RANGE",
            "entry_mode": "HL_PULLBACK",
            "confirmation": "BOS",
            "exit_type": "SL_HIT",
            "v2_feature_snapshot_complete": True,
        }
    }


def test_composite_uses_legacy_floor_when_v2_ready_but_current_snapshot_missing():
    v2 = build_adaptive_gate_v2_policy(
        tuple(_closed_loss() for _ in range(10)),
        signal_context={},
        base_floor=50.01,
        enabled=True,
    )
    assert v2.enabled is True
    composite = CompositeAdaptiveScorePolicy(LegacyPolicy(), v2)
    assert composite.required_score({"id": "new-signal-without-snapshot"}) == 55.01
    assert composite.details()["missing_current_snapshot_policy"] == "LEGACY_FALLBACK"
