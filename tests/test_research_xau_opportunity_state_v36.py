from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_opportunity_state_v36 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    build_opportunity_d1,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _bars(days=520):
    start = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    out = []
    price = 1500.0
    for i in range(days):
        step = 0.5 if i < 300 else 1.5
        price += step
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=start + timedelta(days=i),
                open=price - 0.2,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def test_v36_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v36_has_bounded_preregistered_routes():
    assert set(ROUTES) == {
        "MATURE_L12_NORMAL",
        "EXPANSION_ALL_BOTH_NORMAL",
        "EXPANSION_EXTENDED_BOTH_NORMAL",
        "EXPANSION_TRANSITION_EARLY_L12_NORMAL",
        "EXPANSION_HIGH_EFF_ESTABLISHED_L20_NORMAL",
        "OPPORTUNITY_ROUTER_NORMAL",
    }


def test_v36_prior_only_atr_baseline_exists_after_warmup():
    frame = build_opportunity_d1(_bars())
    values = frame["atr_ratio_prior252_median"].dropna()
    assert len(values) > 0


def test_v36_source_contains_no_order_path_and_freezes_entry_families():
    src = (ROOT / "src/fx_scanner/research_xau_opportunity_state_v36.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_opportunity_state_v36_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert "M15_VARIANTS" in src
    assert "shift(1).rolling" in src
    assert "selection_uses_future_outcomes" in src
