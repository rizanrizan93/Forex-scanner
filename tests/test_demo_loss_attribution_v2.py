from fx_scanner.demo_loss_attribution_v2 import build_loss_attribution_v2


def _row(**payload):
    base = {
        "symbol": "SOLUSD",
        "setup_type": "TREND_CONTINUATION",
        "direction": "LONG",
        "regime": "RANGE",
        "entry_mode": "HL_PULLBACK",
        "confirmation": "BOS",
        "exit_type": "SL_HIT",
    }
    base.update(payload)
    return {"payload": base}


def test_one_or_two_losses_never_create_policy_grade_attribution():
    findings = build_loss_attribution_v2((_row(), _row()))
    assert findings == ()


def test_repeated_regime_mismatch_requires_threshold_and_is_correlation_only():
    rows = tuple(_row() for _ in range(3))
    findings = build_loss_attribution_v2(rows)
    target = [item for item in findings if item.code == "REGIME_SETUP_MISMATCH_PROBABLE"]
    assert len(target) == 1
    assert target[0].scope == "SOLUSD|TREND_CONTINUATION|LONG|RANGE"
    assert target[0].evidence_count == 3
    assert target[0].eligible_losses == 3
    assert target[0].rate == 1.0
    assert "not causal proof" in target[0].detail


def test_stop_too_tight_requires_mae_and_mfe_r_not_currency_pnl():
    currency_only = tuple(
        _row(
            regime="TREND_STRONG",
            sampled_mae_pnl=-2.0,
            sampled_mfe_pnl=3.0,
        )
        for _ in range(4)
    )
    findings = build_loss_attribution_v2(currency_only)
    assert not any(item.code == "STOP_TOO_TIGHT_PROBABLE" for item in findings)

    r_ready = tuple(
        _row(
            regime="TREND_STRONG",
            mae_r=-0.95,
            mfe_r=1.20,
        )
        for _ in range(3)
    )
    findings = build_loss_attribution_v2(r_ready)
    assert any(item.code == "STOP_TOO_TIGHT_PROBABLE" for item in findings)


def test_good_setup_bad_execution_needs_strong_structure_plus_execution_weakness():
    rows = tuple(
        _row(
            regime="TREND_STRONG",
            confirmation="UNKNOWN",
            evidence_scores={"structure": 78.0},
        )
        for _ in range(3)
    )
    findings = build_loss_attribution_v2(rows)
    assert any(item.code == "GOOD_SETUP_BAD_EXECUTION_PROBABLE" for item in findings)


def test_winning_rows_do_not_inflate_loss_attribution_denominator():
    losses = tuple(_row() for _ in range(3))
    wins = tuple(_row(exit_type="TP_HIT") for _ in range(20))
    findings = build_loss_attribution_v2(losses + wins)
    target = next(item for item in findings if item.code == "REGIME_SETUP_MISMATCH_PROBABLE")
    assert target.eligible_losses == 3
    assert target.rate == 1.0
