from pathlib import Path

from fx_scanner.research_volatile_cfd_m15_router_v26 import (
    DIAGNOSTIC_ONLY,
    FREQUENCY_TARGET,
    SYMBOLS,
    VARIANTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v26_preregisters_volatile_cfd_universe_and_grid():
    assert SYMBOLS == ("XAUUSD", "XTIUSD", "BTCUSD", "ETHUSD", "SOLUSD")
    assert len(VARIANTS) == 6
    assert len({v.variant_id for v in VARIANTS}) == 6
    assert FREQUENCY_TARGET["mean_trades_per_day_min"] == 5.0


def test_v26_selection_is_development_only():
    source = (ROOT / "src/fx_scanner/research_volatile_cfd_m15_router_v26.py").read_text()
    assert '"development_only": True' in source
    assert "_select(rows)" in source
    assert DIAGNOSTIC_ONLY is True
    assert '"promotion_eligible": False' in source


def test_v26_is_demo_shadow_only():
    runtime = (ROOT / "src/fx_scanner/research_volatile_cfd_m15_router_v26_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-volatile-cfd-m15-router-v26.yml").read_text()
    assert "V26_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
