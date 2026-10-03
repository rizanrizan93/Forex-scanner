from fx_scanner.xau_yield_regime_view_v372 import (
    classify_daily_us10y,
    classify_intraday_us10y,
    yield_regime_summary,
)


def test_v372_daily_fred_down_is_bullish_xau_regime():
    macro = {
        "components": {
            "US10Y": {
                "current": 5.24,
                "previous": 5.29,
                "delta": -5.0,
                "freshness": "FRESH",
                "provider": "FEDERAL_RESERVE_FRED",
            }
        }
    }
    result = classify_daily_us10y(macro)
    assert result["state"] == "YIELD_DAILY_DOWN"
    assert result["gold_bias"] == "BULLISH_XAU"


def test_v372_intraday_reversal_up_is_bearish_xau_timing():
    macro = {
        "intraday_yield_context": {
            "available": True,
            "state": "YIELD_REVERSAL_UP_STRONG",
            "current": 5.26,
            "rebound_from_low_bps": 10.1,
            "gold_implication": "GOLD_HEADWIND_CONFIRMED",
        }
    }
    result = classify_intraday_us10y(macro)
    assert result["gold_bias"] == "BEARISH_XAU"
    assert result["rebound_from_low_bps"] == 10.1


def test_v372_divergence_keeps_regime_and_timing_separate():
    macro = {
        "components": {
            "US10Y": {
                "current": 5.24,
                "previous": 5.29,
                "delta": -5.0,
                "freshness": "FRESH",
            }
        },
        "intraday_yield_context": {
            "available": True,
            "state": "YIELD_REVERSAL_UP_STRONG",
            "current": 5.26,
            "gold_implication": "GOLD_HEADWIND_CONFIRMED",
        },
    }
    result = yield_regime_summary(macro)
    assert result["daily"]["gold_bias"] == "BULLISH_XAU"
    assert result["intraday"]["gold_bias"] == "BEARISH_XAU"
    assert result["alignment"] == "DIVERGENT"


def test_v372_unavailable_intraday_does_not_overwrite_daily_regime():
    macro = {
        "components": {
            "US10Y": {
                "current": 5.24,
                "previous": 5.29,
                "delta": -5.0,
                "freshness": "FRESH",
            }
        },
        "intraday_yield_context": {
            "available": False,
            "state": "NO_POST_RELEASE_EVENT_ANCHOR",
            "gold_implication": "UNAVAILABLE",
        },
    }
    result = yield_regime_summary(macro)
    assert result["daily"]["gold_bias"] == "BULLISH_XAU"
    assert result["intraday"]["gold_bias"] == "UNAVAILABLE"
    assert result["alignment"] == "INTRADAY_UNAVAILABLE"
