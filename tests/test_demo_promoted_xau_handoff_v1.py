from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES,
    _ALLOWED_SYMBOL,
)
from fx_scanner.demo_five_core_router import PAIR_STRATEGY_IDS
from fx_scanner.demo_xau_expansion_v42 import STRATEGY_ID as XAU_EXPANSION_V42_STRATEGY_ID
from fx_scanner.demo_xau_m15_ema_reversal_recovery import (
    STRATEGY_ID as XAU_M15_EMA_REVERSAL_STRATEGY_ID,
)
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import (
    STRATEGY_ID as XAU_M15_SWEEP_FADE_STRATEGY_ID,
)


def test_shared_demo_handoff_allows_all_exact_authorized_xau_strategies():
    assert _ALLOWED_SYMBOL == "XAUUSD"
    assert _ALLOWED_STRATEGIES == frozenset(
        {
            PAIR_STRATEGY_IDS["XAUUSD"],
            XAU_EXPANSION_V42_STRATEGY_ID,
            XAU_M15_EMA_REVERSAL_STRATEGY_ID,
            XAU_M15_SWEEP_FADE_STRATEGY_ID,
        }
    )
    assert PAIR_STRATEGY_IDS["USDJPY"] not in _ALLOWED_STRATEGIES
