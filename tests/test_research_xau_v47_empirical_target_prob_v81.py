from pathlib import Path

from fx_scanner.research_xau_v47_empirical_target_prob_v81 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    LOOKBACK_DAYS,
    POLICY_EFFECT,
    PROBABILITY_BUCKETS,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    _probability_bucket,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v81_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v81_uses_frozen_60_day_empirical_buckets():
    assert LOOKBACK_DAYS == 60
    assert PROBABILITY_BUCKETS == (
        "LE_0_10",
        "GT_0_10_LE_0_25",
        "GT_0_25_LE_0_50",
        "GT_0_50",
        "UNAVAILABLE",
    )
    assert _probability_bucket(0.10) == "LE_0_10"
    assert _probability_bucket(0.25) == "GT_0_10_LE_0_25"
    assert _probability_bucket(0.50) == "GT_0_25_LE_0_50"
    assert _probability_bucket(0.75) == "GT_0_50"


def test_v81_does_not_modify_trade_or_execute():
    src=(ROOT / "src/fx_scanner/research_xau_v47_empirical_target_prob_v81.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_empirical_target_prob_v81_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert '"entry_changed": False' in src
    assert '"stop_changed": False' in src
    assert '"target_changed": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"probability_bucket_selected_as_winner": False' in src
    assert '"selection_uses_future_outcomes": False' in src
