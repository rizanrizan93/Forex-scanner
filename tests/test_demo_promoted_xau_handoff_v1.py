from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES,
    _ALLOWED_STRATEGIES_BY_SYMBOL,
    _ALLOWED_SYMBOL,
    _XAU_CANONICAL_STRATEGY,
    _XAU_D1_TSMOM_STRATEGY,
    _XAU_SHADOW_STRATEGIES,
)
from fx_scanner.demo_five_core_router import PAIR_STRATEGY_IDS
from fx_scanner.demo_xau_expansion_v42 import STRATEGY_ID as XAU_EXPANSION_V42_STRATEGY_ID
from fx_scanner.demo_xau_m15_ema_reversal_recovery import (
    STRATEGY_ID as XAU_M15_EMA_REVERSAL_STRATEGY_ID,
)
from fx_scanner.demo_xau_m15_ema_smc_reclaim import (
    STRATEGY_ID as XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID,
)
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import (
    STRATEGY_ID as XAU_M15_SWEEP_FADE_STRATEGY_ID,
)


def test_shared_demo_handoff_has_exact_promoted_xau_execution_strategies():
    assert set(_ALLOWED_STRATEGIES_BY_SYMBOL) == {"XAUUSD"}
    assert _ALLOWED_SYMBOL == "XAUUSD"
    assert _XAU_CANONICAL_STRATEGY == XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID
    assert _XAU_D1_TSMOM_STRATEGY == PAIR_STRATEGY_IDS["XAUUSD"]
    assert _ALLOWED_STRATEGIES == frozenset(
        {XAU_M15_EMA_SMC_RECLAIM_STRATEGY_ID, PAIR_STRATEGY_IDS["XAUUSD"]}
    )
    assert _XAU_SHADOW_STRATEGIES == frozenset(
        {
            XAU_EXPANSION_V42_STRATEGY_ID,
            XAU_M15_EMA_REVERSAL_STRATEGY_ID,
            XAU_M15_SWEEP_FADE_STRATEGY_ID,
        }
    )
    assert _ALLOWED_STRATEGIES.isdisjoint(_XAU_SHADOW_STRATEGIES)
    assert PAIR_STRATEGY_IDS["USDJPY"] not in _ALLOWED_STRATEGIES
