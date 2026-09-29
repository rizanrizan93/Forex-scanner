from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_supply_demand_atlas_v182 import (
    M30_SHADOW_RULE,
    MIN_DEPARTURE_BODY_FRACTION,
    MIN_DEPARTURE_RANGE_ATR,
)
from fx_scanner.demo_xau_v229_child_executor import (
    _composite_calibration_pressure_allowed,
)
from fx_scanner.models import Bar
from fx_scanner.xau_composite_pressure_v272 import (
    CONTRACT,
    evaluate_xau_composite_pressure_v272,
)


def _bars(
    timeframe: str,
    count: int,
    *,
    step_minutes: int,
    direction: int,
) -> tuple[Bar, ...]:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    rows: list[Bar] = []
    previous = 4100.0
    for index in range(count):
        drift = 0.55 * float(direction)
        pulse = (0.25 if index % 5 in {0, 1, 2} else -0.10) * float(direction)
        open_price = previous
        close = previous + drift + pulse
        high = max(open_price, close) + 0.30
        low = min(open_price, close) - 0.30
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=step_minutes * index),
                open=open_price,
                high=high,
                low=low,
                close=close,
                tick_count=200 + index,
                spread_avg=0.2,
                spread_max=0.3,
            )
        )
        previous = close
    return tuple(rows)


def test_v272_composite_pressure_is_directional_and_includes_adxr() -> None:
    m5 = _bars("M5", 180, step_minutes=5, direction=1)
    m15 = _bars("M15", 180, step_minutes=15, direction=1)
    as_of = m15[-1].timestamp + timedelta(minutes=16)
    bullish = evaluate_xau_composite_pressure_v272(
        m5_bars=m5,
        m15_bars=m15,
        as_of=as_of,
    )
    assert bullish["contract"] == CONTRACT
    assert bullish["available"] is True
    assert bullish["buyer_index"] > 50.0
    assert bullish["m5"]["adxr14"] is not None
    assert bullish["m15"]["adxr14"] is not None
    assert bullish["execution_authority"] is False

    m5_bear = _bars("M5", 180, step_minutes=5, direction=-1)
    m15_bear = _bars("M15", 180, step_minutes=15, direction=-1)
    bearish = evaluate_xau_composite_pressure_v272(
        m5_bars=m5_bear,
        m15_bars=m15_bear,
        as_of=as_of,
    )
    assert bearish["available"] is True
    assert bearish["buyer_index"] < 50.0
    assert bearish["seller_index"] > 50.0


def test_v272_composite_fallback_only_supports_demo_calibration() -> None:
    allowed, reason = _composite_calibration_pressure_allowed(
        direction="SHORT",
        composite_pressure={
            "available": True,
            "short_calibration_allowed": True,
        },
    )
    assert allowed is True
    assert reason == "COMPOSITE_PRICE_PRESSURE_NOT_MATERIALLY_OPPOSING"

    blocked, reason = _composite_calibration_pressure_allowed(
        direction="LONG",
        composite_pressure={
            "available": True,
            "long_calibration_allowed": False,
        },
    )
    assert blocked is False
    assert reason == "COMPOSITE_PRICE_PRESSURE_OPPOSING"


def test_v272_m30_is_shadow_only_and_not_canonical_timeframe() -> None:
    assert M30_SHADOW_RULE == "30min"
    assert MIN_DEPARTURE_RANGE_ATR["M30"] == 1.00
    assert MIN_DEPARTURE_BODY_FRACTION["M30"] == 0.50

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_supply_demand_atlas_v182.py"
    ).read_text()
    assert '"M30": "30min"' not in source
    assert '"afiq_style_role": "M30_PARENT_ZONE_SHADOW"' in source
    assert '"execution_authority": False' in source


def test_v272_dashboard_surfaces_composite_pressure_and_m30_shadow() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "streamlit_app.py"
    ).read_text()
    assert "RIZAN Composite Pressure" in source
    assert "M5 ADX / ADXR" in source
    assert "M15 ADX / ADXR" in source
    assert "M30 Parent Zone Shadow — kalibrasi gaya Afiq" in source
    assert "M30 adalah shadow parent-zone saja" in source
