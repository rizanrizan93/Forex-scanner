from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_reacceleration_router_v42 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    build_transition_outcome_context,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _bars(days: int = 620):
    start = datetime(2022, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 1800.0
    for i in range(days * 96):
        day = i // 96
        stamp = start + timedelta(minutes=15 * i)
        if day < 260:
            drift = 0.018
        elif day < 285:
            drift = -0.001
        elif day < 430:
            drift = 0.025
        elif day < 455:
            drift = -0.002
        else:
            drift = -0.022
        open_px = price
        close_px = price + drift
        high = max(open_px, close_px) + 0.08
        low = min(open_px, close_px) - 0.08
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


def test_v42_is_research_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v42_route_matrix_is_bounded():
    assert len(ROUTES) == 6
    assert "REACCEL_PHASED_20D_NORMAL" in ROUTES
    assert "REACCEL_L12_L20_20D_NORMAL" in ROUTES
    assert "REACCEL_PHASED_20D_STRICT" in ROUTES
    assert "REVERSAL_PHASED_20D_NORMAL_REFERENCE" in ROUTES


def test_transition_outcome_context_is_causal_and_bounded():
    ctx = build_transition_outcome_context(_bars())
    assert {
        "transition_outcome",
        "post_transition_age_days",
        "episode_transition_days",
    }.issubset(set(ctx.columns))
    assert set(ctx["transition_outcome"].unique()).issubset(
        {"NONE", "REACCELERATION", "REVERSAL"}
    )
    starts = ctx[ctx["post_transition_age_days"] == 1]
    if len(starts):
        assert (starts["episode_transition_days"] >= 1).all()


def test_v42_does_not_change_entry_rules_or_execution_authority():
    src = (ROOT / "src/fx_scanner/research_xau_reacceleration_router_v42.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_reacceleration_router_v42_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"m15_entries": "FROZEN_V20_L12_L20"' in src
    assert '"m15_off_during_transition": True' in src
    assert '"countertrend_m15_allowed": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
