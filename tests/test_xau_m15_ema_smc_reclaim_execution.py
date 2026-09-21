from pathlib import Path

from fx_scanner.demo_execution_fresh_ready_handoff import _ALLOWED_STRATEGIES_BY_SYMBOL
from fx_scanner.demo_xau_m15_ema_smc_reclaim import STRATEGY_ID
from fx_scanner.demo_xau_m15_ema_smc_reclaim_execution import (
    XauM15EmaSmcReclaimSignal,
    build_xau_m15_ema_smc_reclaim_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def test_xau_ema_smc_reclaim_is_authorized_for_demo_handoff():
    assert STRATEGY_ID in _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"]


def test_active_long_signal_builds_structural_protected_plan():
    signal = XauM15EmaSmcReclaimSignal(
        direction="LONG",
        score=82.0,
        active=True,
        execution_eligible=True,
        atr=10.0,
        ema20=4300.0,
        ema50=4295.0,
        ema200=4285.0,
        structural_stop=4310.0,
        liquidity_target=4360.0,
        projected_rr=2.0,
        reason="ENTRY_WINDOW_ACTIVE",
    )
    plan = build_xau_m15_ema_smc_reclaim_plan(signal, current_price=4330.0)
    assert plan.direction == "LONG"
    # Entry is a bounded structural zone, not a single exact tick:
    # default half-width = 0.05 ATR.
    assert plan.entry_low == 4329.5
    assert plan.entry_high == 4330.5
    assert plan.stop_loss == 4310.0
    assert plan.rr1 == 1.5
    assert plan.rr2 == 3.0
    assert plan.tp1 == 4360.0
    assert plan.tp2 == 4390.0


def test_auto_pipeline_runs_and_fail_closed_gates_ema_smc_producer():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "demo_xau_m15_ema_smc_reclaim_candidate_producer" in text
    assert "steps.produce_xau_m15_ema_smc_reclaim.outcome == 'success'" in text
    assert "XAU_M15_EMA_SMC_RECLAIM_OUTCOME" in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "20.0"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text
