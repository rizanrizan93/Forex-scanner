from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.usd_lead_decision_v1 import evaluate_usd_lead
from fx_scanner.xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure

NOW = datetime(2026, 11, 16, 1, 15, tzinfo=UTC)


def at(minutes=0):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def macro(side):
    up = side == "UP"
    u = 1 if up else -1
    return {
        "fed_funds_futures": {
            "source": "YAHOO_FINANCE_ZQ_FRONT_PROXY",
            "available": True, "reference": 96.80,
            "current": 96.80 - .02*u,
            "current_at": at(3), "reference_at": at(63),
            "implied_rate_change_bps": 2*u,
        },
        "dxy_intraday": {
            "source": "YAHOO_FINANCE_ICE_DXY_PROXY",
            "available": True, "reference": 103.0,
            "current": 103.0 + .10*u,
            "current_at": at(3), "reference_at": at(63),
            "net_pct": (.10*u/103.) * 100,
        },
        "components": {
            "US2Y": {
                "freshness": "FRESH", "release_state": "CURRENT_PUBLISHED",
                "current": 4.86+.04*u, "previous": 4.86, "delta": 4*u,
                "observed_at": "2026-11-13T00:00:00+00:00",
                "previous_observed_at": "2026-11-12T00:00:00+00:00",
            },
            "REAL_YIELD_10Y": {
                "freshness": "FRESH", "release_state": "CURRENT_PUBLISHED",
                "current": 2.65+.05*u, "previous": 2.65, "delta": 5*u,
                "observed_at": "2026-11-13T00:00:00+00:00",
                "previous_observed_at": "2026-11-12T00:00:00+00:00",
            },
        },
    }


def xau_both():
    items = [
        {"key": k, "state": "PASS"} for k in ("h1", "m15", "m5", "v404")
    ]
    return {"SELL": {"items": items}, "BUY": {"items": items}}


def nowcast(side, *, zq=None, change=None):
    u = 1 if side == "UP" else -1
    macro_data = macro(side)
    if zq is not None:
        macro_data["fed_funds_futures"] = zq
    return evaluate_yield_pressure(
        {
            "intraday_yield_context": {
                "contract": "XAU_TREASURY_SESSION_AWARE_V399",
                "execution_authority": False, "execution_influence": False,
                "available": True,
                "effective_source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
                "session_state": "GLOBEX_PROXY_ACTIVE",
                "futures_freshness": "FRESH",
                "futures_state": (
                    "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY"
                    if ((-.03125*u) if change is None else change) < 0
                    else "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY"
                ),
                "futures_price": 106.0,
                "futures_at": at(4),
                "futures_change_points": (-.03125*u) if change is None else change,
                "futures_yield_pressure": (
                    "YIELD_UP_PROXY" if ((-.03125*u) if change is None else change) < 0
                    else "YIELD_DOWN_PROXY"
                ),
            },
        }, fed_funds=macro_data["fed_funds_futures"], now=NOW,
    )


def test_bidirectional_buy_and_sell_watch_with_confirmed_yield():
    for usd_direction, expected_state in (
        ("UP", "XAU_SELL_SHADOW_WATCH"),
        ("DOWN", "XAU_BUY_SHADOW_WATCH"),
    ):
        result = evaluate_usd_lead(
            macro(usd_direction), now=NOW,
            xau_checklist=xau_both(),
            yield_nowcast=nowcast(usd_direction),
        )
        key = "usd_up" if usd_direction == "UP" else "usd_down"
        assert result[key]["status"] == expected_state
        assert result[key]["yield_confirmation_required"] is True
        assert result[key]["yield_confirmation_met"] is True
        assert result[key]["passed"] == 6  # 8 rows; news and spread unverified
        assert len(result[key]["rows"]) == 8
        assert result["execution_authority"] is False


def test_sell_xau_blocked_when_yield_projection_points_down():
    res = evaluate_usd_lead(
        macro("UP"), now=NOW, xau_checklist=xau_both(),
        yield_nowcast=nowcast("DOWN"),
    )
    assert res["usd_up"]["status"] == "USD_DIRECTION_WATCH_ONLY"
    y = next(r for r in res["usd_up"]["rows"] if r["key"] == "yield_nowcast")
    assert y["state"] == "FAIL"


def test_buy_xau_blocked_when_yield_projection_points_up():
    res = evaluate_usd_lead(
        macro("DOWN"), now=NOW, xau_checklist=xau_both(),
        yield_nowcast=nowcast("UP"),
    )
    assert res["usd_down"]["status"] == "USD_DIRECTION_WATCH_ONLY"
    y = next(r for r in res["usd_down"]["rows"] if r["key"] == "yield_nowcast")
    assert y["state"] == "FAIL"


def test_single_zn_proxy_is_insufficient_to_mark_yield_complete():
    projection = nowcast("UP", zq={})
    assert projection["state"] == "ZN_PROXY_ONLY"
    res = evaluate_usd_lead(
        macro("UP"), now=NOW, xau_checklist=xau_both(),
        yield_nowcast=projection,
    )
    yield_row = next(r for r in res["usd_up"]["rows"] if r["key"] == "yield_nowcast")
    assert yield_row["state"] == "UNKNOWN"
    assert res["usd_up"]["status"] != "XAU_SELL_SHADOW_WATCH"


def test_missing_nowcast_fail_closed_in_v2_ui_mode():
    res = evaluate_usd_lead(
        macro("UP"), now=NOW, xau_checklist=xau_both(),
        yield_nowcast={"contract": "RIZAN_US10Y_YIELD_PRESSURE_NOWCAST_V1_READONLY",
                       "state": "WAIT_SOURCE", "yield_direction": "WAIT",
                       "as_of_utc": NOW.isoformat(),
                       "execution_authority": False, "execution_influence": False},
    )
    assert res["usd_up"]["yield_confirmation_met"] is False
    assert res["usd_up"]["status"] == "USD_DIRECTION_WATCH_ONLY"


def test_legacy_v1_call_is_still_explicitly_nonexecuting():
    result = evaluate_usd_lead(macro("UP"), now=NOW, xau_checklist=xau_both())
    assert result["usd_up"]["yield_confirmation_required"] is False
    assert result["usd_up"]["xau_execution_permitted"] is False
    assert result["probability_calibrated"] is False
