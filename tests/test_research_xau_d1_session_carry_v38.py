from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_d1_session_carry_v38 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    VARIANTS,
    extract_carry_signals,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _bars(days: int = 340):
    start = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 1800.0
    for i in range(days * 96):
        stamp = start + timedelta(minutes=15 * i)
        price += 0.04
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=stamp,
                open=price - 0.02,
                high=price + 0.08,
                low=price - 0.08,
                close=price,
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def test_v38_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v38_has_bounded_session_matrix():
    assert len(VARIANTS) == 6
    ids = {x.variant_id for x in VARIANTS}
    assert "V38_ASIA_D1_CARRY" in ids
    assert "V38_EUROPE_D1_CARRY" in ids
    assert "V38_US_D1_CARRY" in ids
    assert "V38_US_STRONG_D1_CARRY" in ids


def test_v38_carry_uses_d1_direction_and_session_open():
    bars = _bars()
    variant = next(x for x in VARIANTS if x.variant_id == "V38_US_D1_CARRY")
    signals = extract_carry_signals(bars, variant=variant)
    assert len(signals) > 0
    assert all(x.session == "US" for x in signals[:10])
    assert all(x.direction == "LONG" for x in signals[-10:])


def test_v38_contains_no_order_or_old_entry_family_path():
    src = (ROOT / "src/fx_scanner/research_xau_d1_session_carry_v38.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_d1_session_carry_v38_runtime.py").read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"uses_previous_session_direction": False' in src
    assert '"uses_breakout_retest": False' in src
    assert '"uses_liquidity_sweep": False' in src
    assert '"uses_l12_l20": False' in src
    assert "selection_uses_future_outcomes" in src
