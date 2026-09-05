from fx_scanner.demo_adaptive_calibration_v2_runtime import _enrich_rows, _regime_proxy


def test_geometry_context_is_preferred_without_overwriting_closed_trade_values():
    rows = (
        {
            "signal_key": "sig-1",
            "payload": {
                "signal_id": "sig-1",
                "exit_type": "SL_HIT",
                "symbol": "BTCUSD",
                "pullback_atr": 0.40,
            },
        },
    )
    signals = {
        "sig-1": {
            "id": "sig-1",
            "symbol": "BTCUSD",
            "direction": "LONG",
            "setup_type": "TREND_CONTINUATION",
            "final_score": 62.0,
            "h1_bias": "BULLISH",
            "h4_bias": "BULLISH",
            "entry_low": 100.0,
            "entry_high": 101.0,
            "sl": 98.0,
            "tp1": 104.0,
            "tp2": 106.0,
            "rr1": 1.5,
            "rr2": 2.5,
        }
    }
    geometries = {
        "sig-1": {
            "entry_mode": "HL_PULLBACK",
            "confirmation": "BOS",
            "pullback_atr": 0.25,
            "zone_distance_atr": 0.18,
            "fvg_status": "OPEN",
            "fvg_age_minutes": 12.0,
            "planned_sl": 98.5,
        }
    }

    enriched = _enrich_rows(rows, signals, geometries)[0]["payload"]
    assert enriched["pullback_atr"] == 0.40
    assert enriched["zone_distance_atr"] == 0.18
    assert enriched["entry_mode"] == "HL_PULLBACK"
    assert enriched["confirmation"] == "BOS"
    assert enriched["planned_sl"] == 98.5
    assert enriched["regime"] == "TREND"
    assert enriched["v2_context_source"] == "DEMO_TRADE_CLOSED+DEMO_SIGNAL_GEOMETRY+SIGNALS"


def test_signal_fallback_fills_geometry_absence_but_does_not_invent_entry_mode():
    rows = ({"signal_key": "sig-2", "payload": {"exit_type": "TP_HIT"}},)
    signals = {
        "sig-2": {
            "id": "sig-2",
            "symbol": "SOLUSD",
            "direction": "LONG",
            "setup_type": "TREND_CONTINUATION",
            "final_score": 58.0,
            "h1_bias": "RANGE",
            "h4_bias": "RANGE",
            "entry_low": 20.0,
            "entry_high": 20.2,
            "sl": 19.5,
            "tp1": 21.0,
            "tp2": 22.0,
            "rr1": 1.2,
            "rr2": 2.2,
        }
    }
    enriched = _enrich_rows(rows, signals, {})[0]["payload"]
    assert enriched["symbol"] == "SOLUSD"
    assert enriched["planned_sl"] == 19.5
    assert enriched["regime"] == "RANGE"
    assert "entry_mode" not in enriched
    assert enriched["v2_context_source"] == "DEMO_TRADE_CLOSED+SIGNALS"


def test_immutable_feature_snapshot_outranks_geometry_and_signal_fallbacks():
    rows = (
        {
            "signal_key": "sig-v2",
            "payload": {
                "exit_type": "SL_HIT",
                "regime": "CLOSED_TRUTH_REGIME",
                "final_score": 63.0,
            },
        },
    )
    signals = {
        "sig-v2": {
            "id": "sig-v2",
            "symbol": "EURUSD",
            "direction": "LONG",
            "setup_type": "TREND_CONTINUATION",
            "final_score": 55.0,
            "h1_bias": "BULLISH",
            "h4_bias": "BULLISH",
        }
    }
    geometry = {
        "sig-v2": {
            "entry_mode": "MOMENTUM",
            "confirmation": "FVG",
            "pullback_atr": 0.10,
        }
    }
    snapshot = {
        "sig-v2": {
            "snapshot_version": 2,
            "snapshot_complete_for_regime": True,
            "regime": "TREND_STRONG",
            "entry_mode": "HL_PULLBACK",
            "confirmation": "BOS",
            "pullback_atr": 0.35,
            "atr_m5": 0.0008,
            "evidence_scores": {"structure": 74.0},
            "spread_pips_at_entry": None,
            "live_entry_drift_r": None,
        }
    }
    enriched = _enrich_rows(rows, signals, geometry, {}, snapshot)[0]["payload"]

    assert enriched["regime"] == "CLOSED_TRUTH_REGIME"
    assert enriched["final_score"] == 63.0
    assert enriched["entry_mode"] == "HL_PULLBACK"
    assert enriched["confirmation"] == "BOS"
    assert enriched["pullback_atr"] == 0.35
    assert enriched["atr_m5"] == 0.0008
    assert enriched["evidence_scores"]["structure"] == 74.0
    # Missing execution-time observations remain absent; None is not evidence.
    assert "spread_pips_at_entry" not in enriched
    assert "live_entry_drift_r" not in enriched
    assert enriched["v2_feature_snapshot_complete"] is True
    assert enriched["v2_context_source"].startswith(
        "DEMO_TRADE_CLOSED+DEMO_SIGNAL_FEATURE_SNAPSHOT_V2"
    )


def test_feature_snapshot_regime_replaces_signal_proxy_when_closed_trade_has_no_regime():
    rows = ({"signal_key": "sig-regime", "payload": {"exit_type": "TP_HIT"}},)
    signals = {
        "sig-regime": {
            "id": "sig-regime",
            "symbol": "EURUSD",
            "direction": "LONG",
            "setup_type": "TREND_CONTINUATION",
            "h1_bias": "BEARISH",
            "h4_bias": "BEARISH",
        }
    }
    snapshot = {
        "sig-regime": {
            "snapshot_version": 2,
            "snapshot_complete_for_regime": True,
            "regime": "TRANSITION",
            "entry_mode": "HL_PULLBACK",
            "confirmation": "BOS",
        }
    }
    enriched = _enrich_rows(rows, signals, {}, {}, snapshot)[0]["payload"]
    assert enriched["regime"] == "TRANSITION"
    assert enriched["v2_regime_source"] == "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2"


def test_trajectory_account_currency_extrema_are_attribution_only_not_r():
    rows = ({"signal_key": "sig-3", "payload": {"exit_type": "SL_HIT"}},)
    trajectory = {
        "sig-3": {
            "position_id": "123",
            "sample_count": 8,
            "sampled_mae_pnl": -2.4,
            "sampled_mfe_pnl": 1.7,
            "metric": "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY",
            "r_normalization": "DEFERRED_UNTIL_EXACT_BROKER_RISK_DENOMINATOR",
            "mae_r": None,
            "mfe_r": None,
        }
    }
    enriched = _enrich_rows(rows, {}, {}, trajectory)[0]["payload"]
    assert enriched["sampled_mae_pnl"] == -2.4
    assert enriched["sampled_mfe_pnl"] == 1.7
    assert "mae_r" not in enriched
    assert "mfe_r" not in enriched
    assert enriched["trajectory_attribution_only"] is True
    assert enriched["trajectory_r_normalization"] == "DEFERRED_UNTIL_EXACT_BROKER_RISK_DENOMINATOR"
    assert enriched["v2_context_source"] == "DEMO_TRADE_CLOSED+DEMO_TRADE_TRAJECTORY_FINAL"


def test_explicit_r_normalized_trajectory_can_be_consumed_when_available():
    rows = ({"signal_key": "sig-4", "payload": {"exit_type": "TP_HIT"}},)
    trajectory = {
        "sig-4": {
            "sample_count": 12,
            "sampled_mae_pnl": -0.6,
            "sampled_mfe_pnl": 2.2,
            "mae_r": -0.35,
            "mfe_r": 1.65,
            "metric": "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY",
            "r_normalization": "EXACT_INITIAL_BROKER_RISK",
        }
    }
    enriched = _enrich_rows(rows, {}, {}, trajectory)[0]["payload"]
    assert enriched["mae_r"] == -0.35
    assert enriched["mfe_r"] == 1.65
    assert enriched["trajectory_attribution_only"] is False


def test_regime_proxy_keeps_conflicting_context_mixed():
    assert _regime_proxy({"direction": "LONG", "h1_bias": "BULLISH", "h4_bias": "BEARISH"}) == "MIXED"
    assert _regime_proxy({"direction": "SHORT", "h1_bias": "BEARISH", "h4_bias": "BEARISH"}) == "TREND"
    assert _regime_proxy({"direction": "LONG", "h1_bias": "RANGE", "h4_bias": "RANGE"}) == "RANGE"
