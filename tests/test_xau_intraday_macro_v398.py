from datetime import UTC, datetime, timedelta
import json

from fx_scanner.xau_intraday_macro_v398 import (
    build_intraday_macro_confirmation,
    evaluate_dxy_pressure,
    evaluate_fed_funds_futures_pressure,
    parse_yahoo_chart,
)


NOW = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)


def _points(values, *, minutes=15):
    start = NOW - timedelta(minutes=minutes * (len(values) - 1))
    return [
        {"observed_at": start + timedelta(minutes=minutes * idx), "value": value}
        for idx, value in enumerate(values)
    ]


def test_parse_yahoo_chart_generic():
    body = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [
                            int((NOW - timedelta(minutes=5)).timestamp()),
                            int(NOW.timestamp()),
                        ],
                        "indicators": {"quote": [{"close": [102.0, 102.2]}]},
                    }
                ],
                "error": None,
            }
        }
    ).encode()
    rows = parse_yahoo_chart(body)
    assert len(rows) == 2
    assert rows[-1]["value"] == 102.2


def test_dxy_up_is_gold_headwind():
    out = evaluate_dxy_pressure(_points([102.00, 102.12]), now=NOW)
    assert out["available"] is True
    assert out["state"] == "DXY_UP"
    assert out["gold_implication"] == "GOLD_HEADWIND"
    assert out["freshness"] == "FRESH"


def test_fed_funds_price_down_is_hawkish_gold_headwind():
    out = evaluate_fed_funds_futures_pressure(_points([96.12, 96.08]), now=NOW)
    assert out["available"] is True
    assert out["state"] == "HAWKISH_REPRICING"
    assert out["gold_implication"] == "GOLD_HEADWIND"
    assert round(out["implied_rate_change_bps"], 6) == 4.0


def test_stale_inputs_fail_closed():
    stale_points = [{"observed_at": NOW - timedelta(hours=2), "value": 102.2}]
    dxy = evaluate_dxy_pressure(stale_points, now=NOW, max_age_seconds=1200)
    assert dxy["available"] is False
    assert dxy["freshness"] == "STALE"
    assert dxy["gold_implication"] == "UNAVAILABLE"


def test_confirmation_requires_two_fresh_directional_components():
    out = build_intraday_macro_confirmation(
        dxy={"available": True, "gold_implication": "GOLD_HEADWIND"},
        fed_funds={"available": True, "gold_implication": "GOLD_HEADWIND"},
        us10y={"available": False, "gold_implication": "UNAVAILABLE"},
        broader_macro_bias="BEARISH_XAU",
    )
    assert out["state"] == "INTRADAY_MACRO_BEARISH_CONFIRMED"
    assert out["intraday_macro_bias"] == "BEARISH_XAU"
    assert out["confirmation_eligible"] is True
    assert out["relationship_to_broader_macro"] == "ALIGNED_WITH_BROADER_MACRO"


def test_conflicting_intraday_components_do_not_confirm():
    out = build_intraday_macro_confirmation(
        dxy={"available": True, "gold_implication": "GOLD_HEADWIND"},
        fed_funds={"available": True, "gold_implication": "GOLD_SUPPORT"},
        us10y={"available": True, "gold_implication": "MIXED"},
        broader_macro_bias="BEARISH_XAU",
    )
    assert out["state"] == "INTRADAY_MACRO_DIVERGENT"
    assert out["confirmation_eligible"] is False
