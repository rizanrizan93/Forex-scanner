from pathlib import Path

from fx_scanner.demo_conviction_sizing import select_demo_conviction_sizing
from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES_BY_SYMBOL,
    _XAU_CANONICAL_STRATEGY,
    _XAU_CHAMPION_STRATEGY,
    _XAU_AFIC_EXECUTION_STRATEGY,
    _XAU_RIZAN_DEPTH_EXECUTION_STRATEGY,
    _XAU_D1_TSMOM_STRATEGY,
    _XAU_SHADOW_STRATEGIES,
)
from fx_scanner.demo_five_core_router import (
    EXECUTION_SYMBOLS,
    FIVE_CORE_SYMBOLS,
    NO_TRADE_SYMBOLS,
    PAIR_STRATEGY_IDS,
    SHADOW_SYMBOLS,
)
from fx_scanner.demo_xau_m15_ema_reversal_recovery import (
    STRATEGY_ID as XAU_M15_EMA_REVERSAL_STRATEGY_ID,
)
from fx_scanner.demo_xau_m15_ema_smc_reclaim import (
    STRATEGY_ID as XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID,
)
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import (
    STRATEGY_ID as XAU_M15_SWEEP_FADE_STRATEGY_ID,
)
from fx_scanner.demo_xau_v24_champion_candidate_producer import (
    STRATEGY_ID as XAU_V24_CHAMPION_STRATEGY_ID,
)


ROOT = Path(__file__).resolve().parents[1]


def test_five_core_execution_registry_is_exact_and_pair_specific():
    assert FIVE_CORE_SYMBOLS == ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    assert EXECUTION_SYMBOLS == frozenset({"XAUUSD", "USDJPY", "GBPUSD"})
    assert SHADOW_SYMBOLS == frozenset()
    assert NO_TRADE_SYMBOLS == frozenset({"EURUSD", "AUDUSD"})
    assert PAIR_STRATEGY_IDS["XAUUSD"] == "D1_TSMOM_60_200"
    assert PAIR_STRATEGY_IDS["USDJPY"] == "D1_DONCHIAN55_200"
    assert PAIR_STRATEGY_IDS["GBPUSD"] == "H4_MEAN_REVERT_Z2_TO_SMA20"
    assert PAIR_STRATEGY_IDS["EURUSD"] == "NO_TRADE_UNTIL_VALIDATED"
    assert set(_ALLOWED_STRATEGIES_BY_SYMBOL) == {"XAUUSD"}
    assert "USDJPY" not in _ALLOWED_STRATEGIES_BY_SYMBOL
    assert "GBPUSD" not in _ALLOWED_STRATEGIES_BY_SYMBOL

    # Broker handoff has an exact four-strategy XAU DEMO allowlist: canonical
    # M15, the aggregate V24 champion, AFIC execution, and fresh-first-touch
    # RIZAN depth execution. Standalone D1 and other challengers remain shadow-only.
    assert _XAU_CANONICAL_STRATEGY == XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID
    assert _XAU_CHAMPION_STRATEGY == XAU_V24_CHAMPION_STRATEGY_ID
    assert _XAU_D1_TSMOM_STRATEGY == PAIR_STRATEGY_IDS["XAUUSD"]
    assert _XAU_AFIC_EXECUTION_STRATEGY == "XAU_AFIC_PATH_EXECUTION_V1"
    assert _XAU_RIZAN_DEPTH_EXECUTION_STRATEGY == "XAU_RIZAN_DEPTH_EXECUTION_V1"
    assert _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"] == frozenset(
        {
            XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID,
            XAU_V24_CHAMPION_STRATEGY_ID,
            "XAU_AFIC_PATH_EXECUTION_V1",
            "XAU_RIZAN_DEPTH_EXECUTION_V1",
        }
    )
    assert PAIR_STRATEGY_IDS["XAUUSD"] in _XAU_SHADOW_STRATEGIES
    assert XAU_M15_EMA_REVERSAL_STRATEGY_ID in _XAU_SHADOW_STRATEGIES
    assert XAU_M15_SWEEP_FADE_STRATEGY_ID in _XAU_SHADOW_STRATEGIES
    assert _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"].isdisjoint(_XAU_SHADOW_STRATEGIES)


def test_forward_demo_score_keeps_pair_orders_at_conservative_floor():
    for symbol in ("XAUUSD", "USDJPY", "GBPUSD"):
        row = {"symbol": symbol, "final_score": 60.0, "data_coverage": 1.0, "rr2": 2.0}
        sizing = select_demo_conviction_sizing(row, max_order_lots=0.50, max_risk_pct=5.0)
        assert sizing.lots == 0.01
        assert sizing.risk_budget_pct <= 5.0


def test_active_workflows_use_all_valid_setup_handoff_and_bounded_demo_contract():
    auto = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    supervisor = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    fast_wrapper = (ROOT / "src/fx_scanner/demo_execution_fast_candidate_producer.py").read_text()
    handoff = (ROOT / "src/fx_scanner/demo_execution_fresh_ready_handoff.py").read_text()

    assert "demo_execution_fast_candidate_producer" not in auto
    assert "demo_xau_v24_champion_candidate_producer" in auto
    assert "demo_xau_m15_ema_smc_reclaim_candidate_producer" in auto
    assert "demo_execution_fresh_ready_handoff" in auto
    assert "demo_xau_canonical_position_manager" in auto
    assert "demo_five_core_time_exit" in auto
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "1"' in auto
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "20.0"' in auto
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in auto
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in auto
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "1"' in auto
    assert 'CTRADER_DEMO_STACK_MIN_SCORE: "50.01"' in auto
    assert 'CTRADER_DEMO_MAX_SAME_SYMBOL_POSITIONS: "10"' in auto
    assert 'CTRADER_DEMO_MIN_STACK_SPACING_SECONDS: "0"' in auto
    assert "demo_five_core_candidate_producer" in fast_wrapper
    assert "_ALLOWED_STRATEGIES_BY_SYMBOL" in handoff
    assert "_XAU_CANONICAL_STRATEGY" in handoff
    assert "_XAU_SHADOW_STRATEGIES" in handoff
    assert "PAIR_STRATEGY_IDS" in handoff
    assert "XAU_M15_EMA_REVERSAL_STRATEGY_ID" in handoff
    assert "XAU_M15_SWEEP_FADE_STRATEGY_ID" in handoff
    assert "demo_xau_technical_producer" in discovery
    assert "demo_execution_technical_producer" not in discovery
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "20.0"' in discovery
    assert "universe=XAUUSD" in supervisor
    assert "universe=XAUUSD,EURUSD" not in supervisor
    assert "strategies=XAU_V24_CHAMPION_DEMO_V1,XAU_M15_EMA_SMC_RECLAIM_V1,XAU_RIZAN_DEPTH_EXECUTION_V1" in supervisor
    assert "FX_LIVE_TRADING_ENABLED" not in auto
    assert "I_UNDERSTAND_LIVE_ORDERS" not in auto
