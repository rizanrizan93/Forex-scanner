from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_crossasset_leadlag_v39 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    VARIANTS,
    _source_events,
    extract_signals,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _xau(days: int = 340):
    start = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 1800.0
    for i in range(days * 96):
        stamp = start + timedelta(minutes=15 * i)
        price += 0.02
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=stamp,
                open=price - 0.01,
                high=price + 0.08,
                low=price - 0.08,
                close=price,
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def _source(symbol: str, days: int = 340, sign: float = 1.0):
    start = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
    out = []
    price = 20.0 if symbol == "XAGUSD" else 1.05
    scale = 0.20 if symbol == "XAGUSD" else 0.0020
    for i in range(days * 24):
        stamp = start + timedelta(hours=i)
        open_px = price
        # Every sixth bar is deliberately large enough to exceed 0.75 prior ATR.
        move = sign * (scale * 1.20 if i % 6 == 0 else scale * 0.15)
        close_px = open_px + move
        high = max(open_px, close_px) + scale * 0.10
        low = min(open_px, close_px) - scale * 0.10
        price = close_px
        out.append(
            Bar(
                symbol=symbol,
                timeframe="H1",
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


def test_v39_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v39_preregistered_matrix_is_bounded():
    assert len(VARIANTS) == 6
    ids = {x.variant_id for x in VARIANTS}
    assert "V39_XAG_LEAD" in ids
    assert "V39_EURUSD_WEAKUSD_LEAD" in ids
    assert "V39_XAG_EUR_AGREE" in ids
    assert "V39_XAG_EUR_AGREE_D1" in ids


def test_source_event_is_available_only_after_h1_completion():
    rows = _source("XAGUSD")
    events = _source_events(rows, symbol="XAGUSD")
    assert events
    first_stamp = min(events)
    matching = [row for row in rows if row.timestamp + timedelta(hours=1) == first_stamp]
    assert matching


def test_agreement_requires_same_direction_and_can_generate_signals():
    xau = _xau()
    xag = _source("XAGUSD", sign=1.0)
    eur = _source("EURUSD", sign=1.0)
    variant = next(x for x in VARIANTS if x.variant_id == "V39_XAG_EUR_AGREE_D1")
    signals = extract_signals(xau, xag_h1=xag, eur_h1=eur, variant=variant)
    assert signals
    assert all(x.direction == "LONG" for x in signals[-20:])


def test_opposite_sources_do_not_create_agreement():
    xau = _xau()
    xag = _source("XAGUSD", sign=1.0)
    eur = _source("EURUSD", sign=-1.0)
    variant = next(x for x in VARIANTS if x.variant_id == "V39_XAG_EUR_AGREE")
    signals = extract_signals(xau, xag_h1=xag, eur_h1=eur, variant=variant)
    assert len(signals) == 0


def test_v39_source_has_no_order_or_xau_trigger_path():
    src = (ROOT / "src/fx_scanner/research_xau_crossasset_leadlag_v39.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_crossasset_leadlag_v39_runtime.py").read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"uses_xau_breakout_trigger": False' in src
    assert '"uses_liquidity_sweep": False' in src
    assert '"uses_l12_l20": False' in src
    assert "source_h1_must_be_completed" in src
    assert "source_atr_baseline_prior_only" in src
    assert "selection_uses_future_outcomes" in src
