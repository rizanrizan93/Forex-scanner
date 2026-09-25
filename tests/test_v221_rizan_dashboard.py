from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_supply_demand_atlas_v182 import (
    CHART_BAR_LIMIT,
    _chart_bar_payload,
)
from fx_scanner.models import Bar

ROOT = Path(__file__).resolve().parents[1]


def _bar(index: int) -> Bar:
    price = 4200.0 + index * 0.1
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 20, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=price,
        high=price + 1.0,
        low=price - 1.0,
        close=price + 0.3,
        tick_count=100,
        spread_avg=0.20,
        spread_max=0.30,
    )


def test_v221_chart_payload_is_bounded_and_completed_bar_friendly() -> None:
    rows = tuple(_bar(index) for index in range(CHART_BAR_LIMIT + 25))
    payload = _chart_bar_payload(rows)
    assert len(payload) == CHART_BAR_LIMIT
    assert payload[0]["time"] == rows[-CHART_BAR_LIMIT].timestamp.isoformat()
    assert payload[-1]["close"] == rows[-1].close
    assert set(payload[-1]) == {"time", "open", "high", "low", "close"}


def test_v221_dashboard_uses_rizan_style_user_branding_and_real_candles() -> None:
    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "Peta Harga & Supply/Demand — RIZAN-style" in dashboard
    assert "RIZAN XAU Scanner" in dashboard
    assert "Download chart RIZAN-style (PNG)" in dashboard
    assert "_rizan_chart_png" in dashboard
    assert "chart_bars_m15" in dashboard
    assert "Timeframe chart" in dashboard
    assert "AFIC-style" not in dashboard


def test_v221_keeps_legacy_internal_contract_ids_for_runtime_compatibility() -> None:
    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "XAU_AFIC_PATH_EXECUTION_V1" in dashboard
