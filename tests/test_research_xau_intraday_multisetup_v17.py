from pathlib import Path

from fx_scanner.research_xau_intraday_multisetup_v17 import SETUPS, VARIANTS

ROOT = Path(__file__).resolve().parents[1]


def test_v17_preregisters_multisetup_and_frequency_contract():
    assert set(SETUPS) == {
        "LIQUIDITY_SWEEP",
        "MOMENTUM_BREAKOUT",
        "EMA_PULLBACK",
        "FVG_CONTINUATION",
    }
    assert len(VARIANTS) == 6
    assert len({v.variant_id for v in VARIANTS}) == 6
    assert max(v.max_daily_trades for v in VARIANTS) == 8
    source = (ROOT / "src/fx_scanner/research_xau_intraday_multisetup_v17.py").read_text()
    assert '"mean_trades_per_day_min": 5.0' in source
    assert '"days_ge_5_fraction_min": 0.50' in source
    assert "Five trades/day is measured as a research coverage target" in source


def test_v17_uses_completed_h1_and_previous_completed_d1_only():
    source = (ROOT / "src/fx_scanner/research_xau_intraday_multisetup_v17.py").read_text()
    assert "bisect_right(h1_closes, signal_close)" in source
    assert "completed_regime[daily[i + 1][\"date\"]] = direction" in source


def test_v17_is_demo_shadow_only_and_has_no_execution_handoff():
    source = (ROOT / "src/fx_scanner/research_xau_intraday_multisetup_v17.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_intraday_multisetup_v17_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-intraday-multisetup-v17.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert '"policy_effect": "SHADOW_ONLY"' in runtime
    assert "XAU_V17_DEMO_ONLY" in runtime
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
