from pathlib import Path

from fx_scanner.demo_euraud_gbpaud_chandelier import (
    STRATEGY_BY_SYMBOL,
    TRAIL_ATR_BY_SYMBOL,
    _chandelier_target,
)
from fx_scanner.demo_euraud_gbpaud_execution import (
    REMOTE_SAFETY_TP_R,
    build_euraud_plan,
    build_gbpaud_plan,
)
from fx_scanner.demo_euraud_gbpaud_forward_evidence import (
    EURAUD_STRATEGY_ID,
    GBPAUD_STRATEGY_ID,
)
from fx_scanner.demo_execution_fresh_ready_handoff import _ALLOWED_STRATEGIES_BY_SYMBOL
from fx_scanner.demo_five_core_authority import EXECUTION_SYMBOLS, execution_authorized
from fx_scanner.demo_five_core_router import FiveCoreSignal
from fx_scanner.demo_five_core_time_exit import TIME_EXIT_CONTRACTS


ROOT = Path(__file__).resolve().parents[1]


def _signal(symbol: str, strategy_id: str, direction: str) -> FiveCoreSignal:
    return FiveCoreSignal(
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction,
        active=True,
        execution_eligible=True,
        atr=0.0100,
        reason="ENTRY_WINDOW_ACTIVE",
    )


def test_user_authorized_cross_pairs_are_demo_authorized_and_exact_identity_filtered():
    assert {"EURAUD", "GBPAUD"}.issubset(EXECUTION_SYMBOLS)
    assert execution_authorized("EURAUD")
    assert execution_authorized("GBPAUD")
    assert _ALLOWED_STRATEGIES_BY_SYMBOL["EURAUD"] == frozenset({EURAUD_STRATEGY_ID})
    assert _ALLOWED_STRATEGIES_BY_SYMBOL["GBPAUD"] == frozenset({GBPAUD_STRATEGY_ID})


def test_cross_pair_entry_plans_keep_two_atr_initial_stop_and_remote_nonbinding_tp():
    euraud = build_euraud_plan(
        _signal("EURAUD", EURAUD_STRATEGY_ID, "LONG"), current_price=1.6000
    )
    assert abs(euraud.stop_loss - 1.5800) < 1e-12
    assert euraud.rr2 == REMOTE_SAFETY_TP_R
    assert euraud.tp2 is not None and euraud.tp2 > 1.6000

    gbpaud = build_gbpaud_plan(
        _signal("GBPAUD", GBPAUD_STRATEGY_ID, "SHORT"), current_price=1.9000
    )
    assert abs(gbpaud.stop_loss - 1.9200) < 1e-12
    assert gbpaud.rr2 == REMOTE_SAFETY_TP_R
    assert gbpaud.tp2 is not None and gbpaud.tp2 < 1.9000


def test_chandelier_and_max_hold_contracts_match_frozen_research_rules():
    class Row:
        def __init__(self, high, low):
            self.high = high
            self.low = low

    rows = [Row(1.70, 1.55), Row(1.72, 1.58)]
    assert abs(
        _chandelier_target(
            side="BUY", since_open=rows, atr14=0.02, trail_atr=3.5
        )
        - 1.65
    ) < 1e-12
    assert abs(
        _chandelier_target(
            side="SELL", since_open=rows, atr14=0.02, trail_atr=3.0
        )
        - 1.61
    ) < 1e-12
    assert STRATEGY_BY_SYMBOL["EURAUD"] == EURAUD_STRATEGY_ID
    assert STRATEGY_BY_SYMBOL["GBPAUD"] == GBPAUD_STRATEGY_ID
    assert TRAIL_ATR_BY_SYMBOL == {"EURAUD": 3.5, "GBPAUD": 3.0}
    assert TIME_EXIT_CONTRACTS["EURAUD"][3] == 120
    assert TIME_EXIT_CONTRACTS["GBPAUD"][3] == 120


def test_auto_pipeline_runs_cross_candidates_and_chandelier_as_separate_processes():
    wrapper = (ROOT / "src/fx_scanner/demo_execution_fast_candidate_producer.py").read_text()
    pipeline = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "run_cross_candidates" not in wrapper
    assert "run_cross_chandelier" not in wrapper
    assert "python -m fx_scanner.demo_euraud_gbpaud_candidate_producer" in pipeline
    assert "python -m fx_scanner.demo_euraud_gbpaud_chandelier" in pipeline
    assert pipeline.index("demo_euraud_gbpaud_candidate_producer") < pipeline.index(
        "demo_execution_fresh_ready_handoff"
    )
    assert pipeline.index("demo_execution_fresh_ready_handoff") < pipeline.index(
        "demo_euraud_gbpaud_chandelier"
    )
    assert "FX_LIVE_TRADING_ENABLED" not in pipeline
    assert "I_UNDERSTAND_LIVE_ORDERS" not in pipeline


def test_cross_pair_worker_validates_global_spread_overrides_before_subsetting():
    producer = (
        ROOT / "src/fx_scanner/demo_euraud_gbpaud_candidate_producer.py"
    ).read_text()
    validate = "all_demo_spread_overrides = _demo_spread_limit_overrides(cfg)"
    subset = "cfg = _with_history_requirements(_subset_cfg(cfg, FETCH_SYMBOLS))"
    filtered = "for symbol, limit in all_demo_spread_overrides.items()"
    assert validate in producer
    assert filtered in producer
    assert producer.index(validate) < producer.index(subset) < producer.index(filtered)
