"""Shared timestamp-validated XAU macro evaluation (read-only)."""
from __future__ import annotations
from datetime import UTC, datetime
import streamlit as st
from .dashboard_independent_feeds import macro_input
from .pre_news_transport import fetch_pre_news_snapshot
from .xau_decision_checklist_v1 import obj, stamp
from .usd_lead_bund_2y_v1 import fetch_bundesbank_2y, pair_with_treasury_2y


def _fresh(value, now, seconds=900):
    at = stamp(value)
    return at is not None and 0 <= (now - at).total_seconds() <= seconds


@st.cache_data(ttl=120, show_spinner=False)
def _secondary_quotes(symbol):
    from .xau_intraday_macro_v398 import fetch_yahoo_chart
    urls = {
        "ZQ": "https://query1.finance.yahoo.com/v8/finance/chart/ZQ=F",
        "DXY": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
    }
    return list(fetch_yahoo_chart(
        base_url=urls[symbol], allowed_host="query1.finance.yahoo.com",
        timeout_seconds=5., interval="5m", range_name="1d"
    ))


@st.cache_data(ttl=1800, show_spinner=False)
def _bund():
    return fetch_bundesbank_2y(now=datetime.now(UTC), timeout_seconds=7.)


def macro_and_notes(now):
    notes = {}
    try:
        evaluation = obj(macro_input(
            fetch_pre_news_snapshot(now=now, timeout_seconds=7.), now=now
        ).get("evaluation"))
        notes["macro"] = "V400 snapshot diperiksa; yield resmi harian hanya konteks"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        evaluation = {}
        notes["macro"] = "WAIT DATA: " + type(exc).__name__

    for key, symbol in (("fed_funds_futures", "ZQ"), ("dxy_intraday", "DXY")):
        candidate = obj(evaluation.get(key))
        if candidate.get("available") is True and _fresh(candidate.get("current_at"), now):
            continue
        try:
            from .xau_intraday_macro_v398 import (
                evaluate_dxy_pressure, evaluate_fed_funds_futures_pressure,
            )
            points = _secondary_quotes(symbol)
            fn = evaluate_dxy_pressure if symbol == "DXY" else evaluate_fed_funds_futures_pressure
            evaluation[key] = fn(points, now=now, max_age_seconds=900)
            notes[key] = "Yahoo Finance proxy · timestamp asli"
        except Exception as exc:
            notes[key] = "UNKNOWN: " + type(exc).__name__
    try:
        spread = pair_with_treasury_2y(
            _bund(), obj(obj(evaluation.get("components")).get("US2Y")), now=now,
        )
        notes["spread"] = ("Treasury + Bundesbank tanggal cocok"
                           if spread else "UNKNOWN: tanggal tidak cocok")
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        spread = None
        notes["spread"] = "UNKNOWN: " + type(exc).__name__
    return evaluation, spread, notes
