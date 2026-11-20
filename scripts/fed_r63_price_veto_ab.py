"""R6.3 exact production price-direction VETO on historical as-of bars.

This is a PAIRED, point-in-time-PRICE-only research diagnostic.
Original Fed USMPD FOMC responses were compiled EX POST, hence the
historical 'macro BUY/SELL' is a RETROSPECTIVE ORACLE, NOT a
genuine as-of traded signal. Same event, same first entry time,
same source data, same risk labels. No reselection of later winners.

Inputs M1 index OPEN timestamp; bar considered closed at open+1min.
Output does NOT promote 'market_context' to a real dated quote.
No execution authorization.
"""
from __future__ import annotations
import pandas as pd
from fx_scanner.fed_r6_manual_entry_areas import _bias, _completed_tf
from fx_scanner.fed_r63_macro_price_divergence import evaluate_divergence

CONTRACT="FED_R63_REPLAY_FIXED_FIRST_SIGNAL_PRICE_VETO_AB_V1"
MAX_AGE={15:16,60:61,240:241}

def original_r63_price_veto(m1_prefix, *, at, historical_macro_side):
    if historical_macro_side not in ("BUY","SELL"):
        raise ValueError("BAD_EXPOST_MACRO_SIDE")
    now=pd.Timestamp(at)
    if now.tzinfo is None:
        raise ValueError("UTC_AT_REQUIRED")
    now=now.tz_convert("UTC")
    if not isinstance(m1_prefix.index,pd.DatetimeIndex) or m1_prefix.index.tz is None:
        raise ValueError("UTC_M1_REQUIRED")
    if not m1_prefix.index.is_monotonic_increasing or m1_prefix.index.has_duplicates:
        raise ValueError("UNTRUSTED_M1")
    if m1_prefix.index[-1]+pd.Timedelta(minutes=1)!=now:
        raise ValueError("ONLY_COMPLETE_LATEST_M1_AT_DECISION_TIME")
    if not (m1_prefix.index.to_series().diff().iloc[-16:]==
            pd.Timedelta(minutes=1)).all():
        raise ValueError("INTRADAY_M1_DATA_GAP")
    trends={}
    closed={}
    for interval,label in ((15,"bias_m15"),(60,"bias_h1"),(240,"bias_h4")):
        d=_completed_tf(m1_prefix,interval,now)
        closed[label] = d.index[-1].isoformat() if len(d) else None
        if not len(d) or (now-d.index[-1]).total_seconds()>MAX_AGE[interval]*60:
            trends[label]="UNKNOWN"
        else:
            trends[label]=_bias(d)
    # A deliberately labeled research placeholder, NOT a historical
    # real-time observed OIS/TIPS/DXY quote. Historical side is a
    # completed-window oracle and MUST remain non-executable.
    market={
        "contract":"RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1",
        "direction":historical_macro_side,
        "daily_direction":"WAIT",
        "historical_market_source":"USMPD_EVENT_WINDOW_EXPOST_NOT_PIT",
        "entry_permission":False,
        "validated_fed_r4":False,
    }
    price={
        "contract":"RIZAN_XAU_FED_R6_MANUAL_AREA_V1",
        "as_of":now.isoformat(),"quote_at":now.isoformat(),
        "last_closed_m1":now.isoformat(),
        "status":"WATCH",
        "price":float(m1_prefix.close.iloc[-1]),
        "entry_allowed":False,
        "authority_to_send_orders":False,
        **trends,
    }
    gate=evaluate_divergence(market,price)
    passed=(gate["state"]=="MACRO_AND_PRICE_ALIGNED_WATCH" and
            gate["display_direction"]==historical_macro_side)
    return {
        "contract":CONTRACT,
        "at_utc":now.isoformat(),
        "side":historical_macro_side,
        "signal_type":"ORIGINAL_FOMC_M1_CONTINUATION_FIRST_EVENT",
        "macro_source":"USMPD_EXPOST_ORACLE_NOT_POINT_IN_TIME",
        "price_source":"REAL_HISTDATA_M1_CLOSED_BARS_ONLY",
        "bid_ask_source":"SYNTHETIC_COINCIDENT_RESEARCH_CLOCK_NOT_REAL_BROKER",
        "timeframe_closed_at":closed,
        "price_trend":trends,
        "state":gate["state"],
        "pass_r63_price_veto":passed,
        "blocked_reason":None if passed else gate["reason"],
        "genuine_point_in_time_macro_signal":False,
        "validated_live_accuracy":False,
        "eligible_for_live":False,
        "authority_to_send_orders":False,
    }
