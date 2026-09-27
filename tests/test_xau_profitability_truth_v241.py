from fx_scanner.xau_profitability_truth_v241 import build_xau_profitability_truth


def _reaction(status: str, *, primary: bool = False) -> dict:
    return {
        "strategy_id": "XAU_SUPPLY_DEMAND_PROSPECTIVE_V184",
        "episode_type": "SUPPLY_DEMAND_V184_REACTION",
        "status": status,
        "execution_authority": "NONE",
        "metadata": {"primary_candidate_match": primary},
    }


def test_v241_separates_reaction_from_trading_performance() -> None:
    outcomes = (
        [_reaction("HOLD") for _ in range(25)]
        + [_reaction("BREAK") for _ in range(10)]
        + [_reaction("BREAK_TOUCH_BAR") for _ in range(10)]
        + [_reaction("STALL") for _ in range(5)]
    )
    truth = build_xau_profitability_truth(outcomes=outcomes, performance=[])
    sd = truth["supply_demand_reaction"]
    assert sd["resolved"] == 50
    assert sd["holds"] == 25
    assert sd["precision_hold"] == 0.5
    assert truth["reaction_is_not_win_rate"] is True
    assert truth["validation_state"] == "PROFITABILITY_NOT_YET_VALIDATED"
    assert truth["performance"]["available"] is False


def test_v241_primary_candidate_needs_sample_not_just_perfect_precision() -> None:
    outcomes = [
        _reaction("HOLD", primary=True),
        _reaction("HOLD", primary=True),
    ]
    truth = build_xau_profitability_truth(outcomes=outcomes, performance=[])
    sd = truth["supply_demand_reaction"]
    assert sd["primary_n"] == 2
    assert sd["primary_holds"] == 2
    assert sd["primary_precision"] == 1.0
    assert sd["replication_gate_met"] is False
    assert sd["minimum_n"] == 50


def test_v241_uses_persisted_xau_oos_row_for_profitability_metrics() -> None:
    performance = [
        {
            "as_of": "2026-09-27T00:00:00+00:00",
            "setup_type": "TEST_XAU",
            "symbol": "XAUUSD",
            "sample_scope": "OOS",
            "trades": 120,
            "win_rate": 0.55,
            "expectancy_r": 0.12,
            "profit_factor": 1.35,
            "max_drawdown_r": 8.0,
        }
    ]
    truth = build_xau_profitability_truth(outcomes=[], performance=performance)
    perf = truth["performance"]
    assert truth["validation_state"] == "PERSISTED_PERFORMANCE_AVAILABLE"
    assert perf["available"] is True
    assert perf["trades"] == 120
    assert perf["win_rate"] == 0.55
    assert perf["profit_factor"] == 1.35
    assert perf["expectancy_r"] == 0.12


def test_v241_authorized_forward_sample_is_counted_separately() -> None:
    outcomes = [
        {
            "strategy_id": "V24_D1",
            "episode_type": "SIGNAL",
            "status": "EXECUTION_READY",
            "execution_authority": "XAU_V24_CHAMPION_DEMO_V1",
            "outcome_at": None,
            "tp1_hit": False,
            "tp2_hit": False,
            "stop_hit": False,
            "metadata": {},
        },
        {
            "strategy_id": "V24_D1",
            "episode_type": "SIGNAL",
            "status": "STOPPED",
            "execution_authority": "XAU_V24_CHAMPION_DEMO_V1",
            "outcome_at": "2026-09-27T01:00:00+00:00",
            "tp1_hit": False,
            "tp2_hit": False,
            "stop_hit": True,
            "metadata": {},
        },
    ]
    truth = build_xau_profitability_truth(outcomes=outcomes, performance=[])
    sample = truth["authorized_execution"]
    assert sample["authorized_rows"] == 2
    assert sample["terminal_rows"] == 1
    assert sample["stop_hits"] == 1
    assert truth["validation_state"] == "FORWARD_EXECUTION_SAMPLE_ONLY"
