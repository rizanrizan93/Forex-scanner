from pathlib import Path

from fx_scanner.research_xau_100usd_margin_buffer_v24 import (
    ACCOUNT_LEVERAGES,
    DIAGNOSTIC_ONLY,
    MARGIN_FLOORS_PCT,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v24_preregisters_margin_health_matrix():
    assert ACCOUNT_LEVERAGES == (50.0, 100.0, 200.0, 500.0)
    assert MARGIN_FLOORS_PCT == (50.0, 80.0, 100.0, 150.0)
    assert DIAGNOSTIC_ONLY is True


def test_v24_keeps_fixed_001_and_no_risk_percentage():
    source = (ROOT / "src/fx_scanner/research_xau_100usd_margin_buffer_v24.py").read_text()
    assert '"fixed_lot": 0.01' in source
    assert '"risk_pct_filter": None' in source
    assert "broker-operability test, not a risk-per-trade rule" in source


def test_v24_is_read_only_demo_research():
    runtime = (ROOT / "src/fx_scanner/research_xau_100usd_margin_buffer_v24_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-100usd-margin-buffer-v24.yml").read_text()
    assert "V24_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "new_order_message" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
