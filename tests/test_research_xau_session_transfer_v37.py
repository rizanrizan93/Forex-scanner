from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_session_transfer_v37 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    VARIANTS,
    extract_transfer_signals,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _bars(days: int = 300):
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 2000.0
    for i in range(days * 96):
        stamp = start + timedelta(minutes=15 * i)
        drift = 0.05
        if 22 <= stamp.hour or stamp.hour < 7:
            drift = 0.08
        elif 7 <= stamp.hour < 12:
            drift = 0.06
        elif 12 <= stamp.hour < 21:
            drift = 0.04
        price += drift
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=stamp,
                open=price - 0.03,
                high=price + 0.10,
                low=price - 0.10,
                close=price,
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def test_v37_is_research_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v37_matrix_is_bounded_and_contains_transfer_and_d1_context_controls():
    assert len(VARIANTS) == 8
    ids = {x.variant_id for x in VARIANTS}
    assert "V37_EU_FROM_ASIA_MOM" in ids
    assert "V37_EU_FROM_ASIA_REV" in ids
    assert "V37_US_FROM_EU_MOM" in ids
    assert "V37_US_FROM_EU_REV" in ids
    assert "V37_EU_FROM_ASIA_MOM_D1" in ids
    assert "V37_US_FROM_EU_REV_D1" in ids


def test_v37_signal_generation_uses_prior_session_and_target_open_only():
    bars = _bars()
    variant = next(x for x in VARIANTS if x.variant_id == "V37_EU_FROM_ASIA_MOM")
    signals = extract_transfer_signals(bars, variant=variant)
    assert len(signals) > 0
    first = signals[0]
    assert first.target_session == "EUROPE"
    assert first.source_session == "ASIA"
    assert first.target_last_index > first.signal_index


def test_v37_source_has_no_breakout_sweep_or_order_execution_path():
    src = (ROOT / "src/fx_scanner/research_xau_session_transfer_v37.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_session_transfer_v37_runtime.py").read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"uses_session_high_low_as_trigger": False' in src
    assert '"uses_breakout_retest": False' in src
    assert '"uses_liquidity_sweep": False' in src
    assert "selection_uses_future_outcomes" in src
