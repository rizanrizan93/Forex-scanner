from pathlib import Path

from fx_scanner.research_per_symbol_router_v19 import FAMILIES, SPECS, SYMBOLS

ROOT = Path(__file__).resolve().parents[1]


def test_v19_preregisters_symbol_router_without_holdout_selection():
    assert len(SYMBOLS) == 17
    assert len(FAMILIES) == 5
    assert len(SPECS) == 5
    source = (ROOT / "src/fx_scanner/research_per_symbol_router_v19.py").read_text()
    assert '"development_only": True' in source
    assert "Holdout is reported for audit only; it is never used in selection." in source
    assert "_select_family(candidates)" in source


def test_v19_frequency_target_is_account_wide_five_per_day():
    source = (ROOT / "src/fx_scanner/research_per_symbol_router_v19.py").read_text()
    assert '"mean_trades_per_day_min": 5.0' in source
    assert '"days_ge_5_fraction_min": 0.50' in source


def test_v19_is_demo_shadow_only():
    source = (ROOT / "src/fx_scanner/research_per_symbol_router_v19.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_per_symbol_router_v19_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-per-symbol-router-v19.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert '"promotion_eligible": False' in source
    assert "V19_DEMO_ONLY" in runtime
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
