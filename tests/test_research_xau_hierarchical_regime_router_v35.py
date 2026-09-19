from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_hierarchical_regime_router_v35 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PRIMARY_VARIANTS,
    PROMOTION_ELIGIBLE,
    _Asof,
    build_d1_context,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _daily_like_bars(days: int = 340):
    start = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    out = []
    price = 1500.0
    for i in range(days):
        price += 1.0
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


def test_v35_is_shadow_only_and_never_promotion_eligible():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v35_primary_matrix_contains_requested_hierarchy_variants():
    expected = {
        "D1_CLASSIC_ONLY",
        "D1_CLASSIC_PLUS_UNRESTRICTED_L20",
        "D1_CLASSIC_PLUS_UNRESTRICTED_L12_L20",
        "D1_CLASSIC_PLUS_D1_GATE_L20",
        "D1_CLASSIC_PLUS_D1_GATE_L12_L20",
        "D1_CLASSIC_PLUS_D1_H1_SOFT",
        "D1_CLASSIC_PLUS_D1_H1_NORMAL",
        "D1_CLASSIC_PLUS_D1_H1_STRICT",
        "D1_CLASSIC_PLUS_MATURITY_ROUTED_NORMAL",
        "D1_CLASSIC_PLUS_TRANSITION_EARLY_L12",
    }
    assert expected.issubset(set(PRIMARY_VARIANTS))


def test_d1_classifier_can_identify_strong_bull_without_future_data():
    bars = _daily_like_bars()
    frame = build_d1_context(bars)
    latest = frame.iloc[-1]
    assert latest["regime"] == "STRONG_BULL"
    assert int(latest["regime_side"]) == 1


def test_completed_bar_lookup_does_not_use_unfinished_current_day():
    bars = _daily_like_bars()
    frame = build_d1_context(bars)
    lookup = _Asof(frame)
    signal_at = bars[-1].timestamp
    row = lookup.row(signal_at)
    assert row is not None
    # Completed D1 buckets are right-labelled at midnight; a noon signal
    # must resolve to the prior completed day, not the current unfinished day.
    assert row["time"].to_pydatetime() <= signal_at
    assert row["time"].to_pydatetime().date() == signal_at.date()


def test_v35_runtime_and_research_have_no_order_path():
    research = (
        ROOT / "src/fx_scanner/research_xau_hierarchical_regime_router_v35.py"
    ).read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_hierarchical_regime_router_v35_runtime.py"
    ).read_text()
    combined = research + "\n" + runtime
    assert "send_new_order" not in combined
    assert "LIVE-money" not in combined
    assert "label=\"right\"" in research
    assert 'closed="left"' in research
    assert "trade.signal_at" in research


def test_v35_cost_sensitivity_includes_old_and_current_friction_levels():
    runtime = (
        ROOT / "src/fx_scanner/research_xau_hierarchical_regime_router_v35_runtime.py"
    ).read_text()
    for cost_id in ("LOW_1700", "MID_3500", "V24_BASE_3740", "V24_STRESS_4675"):
        assert cost_id in runtime
