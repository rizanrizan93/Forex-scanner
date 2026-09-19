from pathlib import Path

from fx_scanner.research_xau_100usd_stopout_v23 import (
    BROKER_FALLBACK_STOPOUT_PCT,
    DIAGNOSTIC_ONLY,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v23_uses_broker_stopout_not_risk_percent():
    assert BROKER_FALLBACK_STOPOUT_PCT == 50.0
    assert DIAGNOSTIC_ONLY is True
    source = (ROOT / "src/fx_scanner/research_xau_100usd_stopout_v23.py").read_text()
    assert '"risk_pct_filter": None' in source
    assert "planned_margin_level <= stopout_pct" in source
    assert "broker-survivability constraint" in source


def test_v23_reads_margin_call_thresholds_and_never_orders():
    runtime = (ROOT / "src/fx_scanner/research_xau_100usd_stopout_v23_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-100usd-stopout-v23.yml").read_text()
    assert "ProtoOAMarginCallListReq" in runtime
    assert "send_new_order" not in runtime
    assert "new_order_message" not in runtime
    assert "V23_DEMO_ONLY" in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
