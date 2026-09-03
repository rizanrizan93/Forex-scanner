from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_technical_strategy import DemoSetupType, _demo_setup_type
from fx_scanner.liquidity import FairValueGap, OrderBlock
from fx_scanner.strategy import SetupType

UTC = timezone.utc


def _structure(
    trend: str,
    *,
    bos: str | None = None,
    mss: str | None = None,
    displacement=None,
):
    return SimpleNamespace(
        trend=trend,
        bos=bos,
        mss=mss,
        displacement=displacement,
    )


def _base(
    *,
    now: datetime,
    setup_type=None,
    m15_bos: str | None = None,
    m5_bos: str | None = None,
    m5_mss: str | None = None,
    displacement=None,
    fvgs=(),
    order_blocks=(),
):
    return SimpleNamespace(
        direction="LONG",
        setup_type=setup_type,
        h1=_structure("BULLISH"),
        m15=_structure("BULLISH", bos=m15_bos),
        m5=_structure(
            "BULLISH",
            bos=m5_bos,
            mss=m5_mss,
            displacement=displacement,
        ),
        liquidity=SimpleNamespace(
            fvgs=tuple(fvgs),
            order_blocks=tuple(order_blocks),
        ),
    )


def test_canonical_setup_is_preserved():
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    base = _base(now=now, setup_type=SetupType.TREND_CONTINUATION)
    assert _demo_setup_type(base, as_of=now) is SetupType.TREND_CONTINUATION


def test_breakout_retest_fills_setup_none():
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    displacement = SimpleNamespace(valid=True, direction="BULLISH")
    base = _base(now=now, m15_bos="BULLISH", displacement=displacement)
    assert _demo_setup_type(base, as_of=now) is DemoSetupType.BREAKOUT_RETEST


def test_order_block_reclaim_fills_setup_none():
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    block = OrderBlock(
        "BULLISH",
        100.0,
        101.0,
        now - timedelta(minutes=30),
        now - timedelta(minutes=25),
        True,
        True,
        False,
    )
    base = _base(now=now, m5_mss="BULLISH", order_blocks=(block,))
    assert _demo_setup_type(base, as_of=now) is DemoSetupType.ORDER_BLOCK_RECLAIM


def test_fvg_pullback_continuation_fills_setup_none(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90")
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    gap = FairValueGap(
        "BULLISH",
        100.0,
        101.0,
        now - timedelta(minutes=20),
        "OPEN",
        0.0,
    )
    base = _base(now=now, fvgs=(gap,))
    assert _demo_setup_type(base, as_of=now) is DemoSetupType.FVG_PULLBACK_CONTINUATION


def test_invalid_structure_remains_none():
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    base = _base(now=now)
    base.h1.trend = "BEARISH"
    assert _demo_setup_type(base, as_of=now) is None


def test_demo_has_five_total_setup_labels_without_changing_canonical_enum():
    canonical = {item.value for item in SetupType}
    demo_extra = {item.value for item in DemoSetupType}
    assert canonical == {"LIQUIDITY_SWEEP_REVERSAL", "TREND_CONTINUATION"}
    assert demo_extra == {
        "BREAKOUT_RETEST",
        "FVG_PULLBACK_CONTINUATION",
        "ORDER_BLOCK_RECLAIM",
    }
    strategy_text = Path("src/fx_scanner/strategy.py").read_text()
    assert "BREAKOUT_RETEST" not in strategy_text
    assert "ORDER_BLOCK_RECLAIM" not in strategy_text
