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
    assert enriched["pullback_atr"] == 0.40  # closed-trade payload stays authoritative
    assert enriched["zone_distance_atr"] == 0.18
    assert enriched["entry_mode"] == "HL_PULLBACK"
    assert enriched["confirmation"] == "BOS"
    assert enriched["planned_sl"] == 98.5  # immutable geometry beats later signal fallback
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


def test_regime_proxy_keeps_conflicting_context_mixed():
    assert _regime_proxy({"direction": "LONG", "h1_bias": "BULLISH", "h4_bias": "BEARISH"}) == "MIXED"
    assert _regime_proxy({"direction": "SHORT", "h1_bias": "BEARISH", "h4_bias": "BEARISH"}) == "TREND"
    assert _regime_proxy({"direction": "LONG", "h1_bias": "RANGE", "h4_bias": "RANGE"}) == "RANGE"
