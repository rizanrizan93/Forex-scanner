from fx_scanner.demo_xau_m15_canonical_policy import (
    CANONICAL_POLICY_CONTRACT,
    EntryMode,
    MarketRegime,
    PositionStage,
    evaluate_canonical_xau_decision,
    evaluate_position_management,
)


def _bullish_evidence():
    return {
        "adx14": 31.0,
        "plus_di14": 30.0,
        "minus_di14": 11.0,
        "directional_di": True,
        "price": 4360.0,
        "ema20": 4345.0,
        "ema50": 4328.0,
        "ema200": 4315.0,
        "full_ema_alignment": True,
        "momentum_alignment": True,
        "transition_reclaim": False,
        "m15_trend": "BULLISH",
        "h1_trend": "BULLISH",
        "m15_bos": "BULLISH",
        "recent_smc_sequence": {
            "ordered": True,
            "retracement_ok": True,
            "fvg_retrace": True,
        },
    }


def _ict_ready():
    return {
        "execution_ready": True,
        "confluence_count": 3,
        "anti_chase_ok": True,
        "fvg_retest": True,
        "order_block_retest": True,
        "ote_retest": False,
    }


def test_canonical_policy_accepts_bullish_trend_pullback():
    decision = evaluate_canonical_xau_decision(
        direction="LONG",
        score=82.0,
        evidence=_bullish_evidence(),
        ict_evidence=_ict_ready(),
    )
    assert decision.contract == CANONICAL_POLICY_CONTRACT
    assert decision.regime == MarketRegime.BULLISH
    assert decision.entry_mode == EntryMode.CONTINUATION_PULLBACK
    assert decision.countertrend is False
    assert decision.execution_ready is True
    assert decision.reasons == ()


def test_canonical_policy_blocks_countertrend_short_even_with_high_score():
    evidence = _bullish_evidence()
    evidence["directional_di"] = False
    decision = evaluate_canonical_xau_decision(
        direction="SHORT",
        score=95.0,
        evidence=evidence,
        ict_evidence=_ict_ready(),
    )
    assert decision.regime == MarketRegime.BULLISH
    assert decision.entry_mode == EntryMode.COUNTERTREND_SCALP
    assert decision.countertrend is True
    assert decision.execution_ready is False
    assert "COUNTERTREND_RESEARCH_ONLY" in decision.reasons


def test_canonical_policy_blocks_impulse_without_retracement():
    evidence = _bullish_evidence()
    evidence["recent_smc_sequence"] = {
        "ordered": True,
        "retracement_ok": False,
        "fvg_retrace": False,
    }
    decision = evaluate_canonical_xau_decision(
        direction="LONG",
        score=90.0,
        evidence=evidence,
        ict_evidence=_ict_ready(),
    )
    assert decision.execution_ready is False
    assert "POST_IMPULSE_RETRACEMENT_MISSING" in decision.reasons


def test_position_state_machine_preserves_room_before_tp1_and_protects_runner_after():
    early = evaluate_position_management(
        current_r=0.6,
        profitable=True,
        adverse_structure_confirmed=False,
    )
    tp1 = evaluate_position_management(
        current_r=1.6,
        profitable=True,
        adverse_structure_confirmed=False,
    )
    runner = evaluate_position_management(
        current_r=2.4,
        profitable=True,
        adverse_structure_confirmed=False,
    )
    exit_decision = evaluate_position_management(
        current_r=1.2,
        profitable=True,
        adverse_structure_confirmed=True,
    )

    assert early.stage == PositionStage.HOLD_INITIAL
    assert early.protect_stop is False
    assert tp1.stage == PositionStage.PROTECT_RUNNER
    assert tp1.protect_stop is True
    assert runner.stage == PositionStage.TRAIL_RUNNER
    assert runner.protect_stop is True
    assert exit_decision.stage == PositionStage.EXIT_ADVERSE_STRUCTURE
    assert exit_decision.exit_position is True
