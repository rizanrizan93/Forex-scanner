"""Audits only the public retrospective R28.1 records, never execution."""
import numpy as np

from r281_live_shadow_parity import CONTRACT, record, resolved, classifier


def test_each_frozen_policy_is_from_archived_2025_and_two_sided():
    for tf in ("1h", "4h", "1D", "1W"):
        report, annual, family, policy = record(tf)
        assert report["tf"] == tf
        assert annual["year"] == 2025 and annual["status"] == "EVALUATED"
        assert family in ("price", "fx", "price_fx")
        for side in ("BUY", "SELL"):
            cfg = policy[side + "_config"]
            assert cfg is not None
            assert cfg["C"] in (0.025, 0.3)
            assert 0.5 <= cfg["threshold"] <= 0.8


def test_conflicts_never_become_directional_successes():
    y = np.array([1, 0, 1, 0], dtype=np.int8)
    buy = np.array([True, True, True, False])
    sell = np.array([False, True, True, True])
    out = resolved(y, buy, sell)
    assert out == {"BUY": {"n": 1, "correct": 1}, "SELL": {"n": 1, "correct": 1}}
    assert CONTRACT == "RIZAN_R281_SHADOW_PARITY_V1"


def test_frozen_classifier_contract():
    m = classifier(0.3)
    x = np.array([[-2.], [-1.], [1.], [2.]])
    m.fit(x, [0, 0, 1, 1])
    p = m.predict_proba(x)
    assert p.shape == (4, 2)
    assert np.isfinite(p).all()
