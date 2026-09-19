from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_transition_regime_router_v41 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    build_transition_context,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _bars(days: int = 520):
    start = datetime(2022, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 2000.0
    for i in range(days * 96):
        stamp = start + timedelta(minutes=15 * i)
        day = i // 96
        # Long bearish phase, transition/chop, then long bullish phase.
        if day < 240:
            drift = -0.015
        elif day < 265:
            drift = 0.002
        else:
            drift = 0.025
        open_px = price
        close_px = price + drift
        high = max(open_px, close_px) + 0.10
        low = min(open_px, close_px) - 0.10
        price = close_px
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=stamp,
                open=open_px,
                high=high,
                low=low,
                close=close_px,
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def test_v41_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v41_route_matrix_is_bounded_and_phase_based():
    assert len(ROUTES) == 6
    assert "POSTFLIP_PHASED_20D_NORMAL" in ROUTES
    assert "POSTFLIP_PHASED_20D_STRICT" in ROUTES
    assert "POSTFLIP_3OF5_PHASED_20D_NORMAL" in ROUTES
    assert "POSTFLIP_4OF5_PHASED_20D_NORMAL" in ROUTES
    assert "POSTFLIP_3OF5_L12_5D_NORMAL" in ROUTES


def test_transition_context_has_causal_feature_columns():
    ctx = build_transition_context(_bars())
    expected = {
        "bull_ema_reclaim",
        "bear_ema_loss",
        "bull_momentum_flip",
        "bear_momentum_flip",
        "bull_slope_flip",
        "bear_slope_flip",
        "bull_displacement",
        "bear_displacement",
        "vol_expansion",
        "post_flip_age_days",
        "transition_confirmation_score",
    }
    assert expected.issubset(set(ctx.columns))
    assert ctx["transition_confirmation_score"].between(0, 5).all()


def test_transition_requires_nonzero_transition_gap_before_flip():
    ctx = build_transition_context(_bars())
    episodes = ctx[ctx["post_flip_age_days"] == 1]
    # Synthetic data may or may not satisfy all EMA/momentum conditions, but
    # any confirmed episode must have spent at least one D1 in transition.
    if len(episodes):
        assert (episodes["confirmation_transition_days"] >= 1).all()


def test_v41_does_not_change_entry_family_or_add_execution_path():
    src = (ROOT / "src/fx_scanner/research_xau_transition_regime_router_v41.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_transition_regime_router_v41_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"m15_entries": "FROZEN_V20_L12_L20"' in src
    assert '"m15_off_during_transition": True' in src
    assert '"countertrend_m15_allowed": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
