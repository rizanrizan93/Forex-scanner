from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.pre_news_expectation import EVENT_WORKER, MACRO_WORKER, evaluate_pre_news

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)


def snapshot(tilt=1, category="CPI"):
    event = {"title": "Test " + category, "category": category,
             "scheduled_at": (NOW + timedelta(hours=1)).isoformat(),
             "forecast": 3 + tilt, "previous": 3, "actual": 999}
    daily = {name: {"observed_at": (NOW - timedelta(days=1)).isoformat(),
                    "freshness": "FRESH", "delta": 4 * tilt, "provider": "FRED"}
             for name in ("US2Y", "US10Y", "REAL_YIELD_10Y")}
    macro = {"components": daily, "dxy_intraday": {"current_at": NOW.isoformat(),
              "freshness": "FRESH", "net_pct": .1 * tilt, "source": "DXY_PROXY"}}
    return {"heartbeats": [
        {"worker_name": EVENT_WORKER, "observed_at": NOW.isoformat(), "healthy": True,
         "details": {"risk": {"focal_event": event, "upcoming_events": [event], "state": "PRE_EVENT_BLOCK"}}},
        {"worker_name": MACRO_WORKER, "observed_at": NOW.isoformat(), "healthy": True,
         "details": {"evaluation": macro}},
    ]}


@pytest.mark.parametrize("tilt,expected,bias", [(1,"HOT-RISK","BEARISH_XAU"),(-1,"COOL","BULLISH_XAU"),(0,"INLINE","NEUTRAL_MIXED")])
def test_expectation_is_consensus_change_not_actual_surprise(tilt, expected, bias):
    data = snapshot(tilt)
    before = deepcopy(data)
    view = evaluate_pre_news(data, now=NOW)
    assert view["state"] == "PRE_NEWS"
    assert view["expectation"] == expected
    assert view["xau_bias"] == bias
    assert data == before
    assert view["probability"] is None
    assert not view["execution_authority"] and not view["execution_influence"]


@pytest.mark.parametrize("category",["CPI","PPI","NFP","EMPLOYMENT","WAGES","ECI","JOLTS"])
def test_supported_categories(category):
    assert evaluate_pre_news(snapshot(category=category), now=NOW)["state"] == "PRE_NEWS"


def test_inverse_unemployment_and_conflicting_macro():
    data = snapshot(-1, "UNEMPLOYMENT_RATE")
    view = evaluate_pre_news(data, now=NOW)
    assert view["expectation"] == "HOT-RISK"
    assert view["xau_bias"] == "NEUTRAL_MIXED"
    assert "CONSENSUS_MACRO_DIVERGENCE" in view["reasons"]
    assert view["scenarios"][0]["Implikasi awal XAU"] == "Cenderung mendukung"


@pytest.mark.parametrize("index",[0,1])
@pytest.mark.parametrize("issue",["stale","future","naive","unhealthy"])
def test_invalid_worker_cannot_issue_bias(index, issue):
    data = snapshot()
    hb = data["heartbeats"][index]
    if issue == "unhealthy":
        hb["healthy"] = False
    else:
        hb["observed_at"] = {"stale": NOW-timedelta(minutes=11), "future": NOW+timedelta(seconds=1), "naive": NOW.replace(tzinfo=None)}[issue].isoformat()
    view = evaluate_pre_news(data, now=NOW)
    assert view["state"] == "DATA INCOMPLETE"
    assert view["xau_bias"] == "UNAVAILABLE"


@pytest.mark.parametrize("bad",[None,"BELUM ADA KONSENSUS",float("nan"),float("inf"),True])
def test_missing_or_invalid_consensus(bad):
    data = snapshot()
    data["heartbeats"][0]["details"]["risk"]["focal_event"]["forecast"] = bad
    assert evaluate_pre_news(data, now=NOW)["state"] == "DATA INCOMPLETE"


def test_republication_does_not_refresh_components():
    data = snapshot()
    macro = data["heartbeats"][1]["details"]["evaluation"]
    macro["dxy_intraday"]["current_at"] = (NOW-timedelta(hours=1)).isoformat()
    macro["components"]["US2Y"]["observed_at"] = (NOW-timedelta(days=8)).isoformat()
    view = evaluate_pre_news(data, now=NOW)
    assert view["xau_bias"] == "UNAVAILABLE"
    assert "DXY_STALE_OR_MISSING" in view["reasons"]
    assert "US2Y_STALE_OR_MISSING" in view["reasons"]


def test_simultaneous_core_headline_conflict():
    data = snapshot()
    risk = data["heartbeats"][0]["details"]["risk"]
    other = dict(risk["focal_event"], title="Core CPI", forecast=2)
    risk["upcoming_events"].append(other)
    view = evaluate_pre_news(data, now=NOW)
    assert len(view["event_cluster"]) == 2
    assert view["expectation"] == "MIXED"
    assert view["xau_bias"] == "NEUTRAL_MIXED"


def test_past_release_excluded_and_closest_future_selected():
    data = snapshot()
    risk = data["heartbeats"][0]["details"]["risk"]
    risk["focal_event"] = dict(risk["focal_event"], scheduled_at=(NOW-timedelta(minutes=1)).isoformat())
    view = evaluate_pre_news(data, now=NOW)
    assert view["minutes_to_event"] == 60
    assert view["event_time_wib"].endswith("+07:00")
    assert len(view["event_cluster"]) == 1


def test_fomc_not_inferred_from_rate_alone():
    view = evaluate_pre_news(snapshot(0,"FOMC"), now=NOW)
    assert view["state"] == "DATA INCOMPLETE"
    assert "FOMC_LANGUAGE_AND_RATE_PATH_UNMODELED" in view["reasons"]


def test_compact_payload_and_out_of_order_heartbeat():
    data = snapshot()
    for row in data["heartbeats"]:
        row["details"]["dashboard_projection"] = next(iter(row["details"].values()))
        row["details"].pop("risk" if row["worker_name"] == EVENT_WORKER else "evaluation")
    old = deepcopy(data["heartbeats"][0])
    old["observed_at"] = (NOW-timedelta(hours=1)).isoformat()
    data["heartbeats"].append(old)
    assert evaluate_pre_news(data, now=NOW)["state"] == "PRE_NEWS"


def test_missing_snapshot_and_naive_clock():
    assert evaluate_pre_news({}, now=NOW)["state"] == "DATA INCOMPLETE"
    with pytest.raises(ValueError):
        evaluate_pre_news({}, now=NOW.replace(tzinfo=None))


def test_new_tab_uses_existing_snapshot_and_renders_incomplete():
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    root = Path(__file__).resolve().parents[1]
    with patch("fx_scanner.xau_turso_hot_snapshot_v407.fetch_public_hot_snapshot", return_value={"heartbeats": []}):
        app = AppTest.from_file(str(root / "main.py"))
        app.session_state["rizan_xau_detail"] = "Pre-News"
        app.run()
        assert not app.exception
        assert any(tab.label == "Pre-News" for tab in app.tabs)
        assert any(metric.value == "DATA INCOMPLETE" for metric in app.metric)


def test_panel_shows_complete_fixture_without_orders():
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    root = Path(__file__).resolve().parents[1]
    with patch("fx_scanner.xau_turso_hot_snapshot_v407.fetch_public_hot_snapshot", return_value=snapshot()), patch("fx_scanner.pre_news_dashboard.datetime") as time:
        time.now.return_value = NOW
        app = AppTest.from_file(str(root / "pages/3_Pre_News_Expectation.py"))
        app.run()
        assert not app.exception
        assert any(metric.value == "BEARISH_XAU" for metric in app.metric)
