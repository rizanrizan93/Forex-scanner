from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES,
    _ALLOWED_SYMBOL,
)
from fx_scanner.demo_five_core_router import PAIR_STRATEGY_IDS
from fx_scanner.demo_xau_expansion_v42 import STRATEGY_ID as XAU_EXPANSION_V42_STRATEGY_ID


def test_shared_demo_handoff_allows_only_exact_promoted_xau_strategies():
    assert _ALLOWED_SYMBOL == "XAUUSD"
    assert _ALLOWED_STRATEGIES == frozenset(
        {
            PAIR_STRATEGY_IDS["XAUUSD"],
            XAU_EXPANSION_V42_STRATEGY_ID,
        }
    )
    assert PAIR_STRATEGY_IDS["USDJPY"] not in _ALLOWED_STRATEGIES
