"""Display-only calibrated reversal geometry. No connection to cBot orders."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
import pandas as pd
from .reversal_zones import (CONTRACT, GRID, normalize_bars, closed_features,
                              base_events, thin_events, matches)

RESULT_PATH = Path(__file__).resolve().parents[2]/"calibration/reversal_10m_results.json"


def evaluate(raw, result, *, now=None):
    now = pd.Timestamp(now or datetime.now(UTC))
    if now.tzinfo is None:
        raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    now = now.tz_convert("UTC")
    out = {"contract":CONTRACT, "as_of":now.isoformat(), "symbol":"XAUUSD",
           "execution_authority":False, "execution_influence":False, "zones":[]}
    if result.get("contract") != CONTRACT or result.get("configurations_evaluated") != 10_000_000:
        return {**out,"state":"RESEARCH_PENDING"}
    m1 = normalize_bars(raw)
    m1 = m1.loc[m1.index+pd.Timedelta(minutes=1) <= now]
    if m1.empty or not 0 <= (now-(m1.index[-1]+pd.Timedelta(minutes=1))).total_seconds() <= 180:
        return {**out,"state":"STALE_DATA"}
    features = closed_features(m1)
    if features.empty:
        return {**out,"state":"INSUFFICIENT_HISTORY"}
    latest = features.iloc[-1]
    close_time = features.index[-1]
    if pd.isna(latest.atr) or pd.isna(latest.slope):
        return {**out,"state":"INSUFFICIENT_HISTORY"}
    if (now-close_time).total_seconds() > 360:
        return {**out,"state":"STALE_M5"}
    winners = result.get("selected_by_side") or [result.get("selected")]
    for winner in winners:
        if not winner:
            continue
        cfg=winner["config"]; side=cfg["side"]; lookback=cfg["lookback_h1"]
        level=latest[f"level_{side}_{lookback}"]; atr=latest.atr
        if pd.isna(level) or pd.isna(atr) or atr<=0:
            continue
        age=close_time.value/3.6e12-latest[f"formed_{side}_{lookback}"]
        if age > cfg["max_age_hours"]:
            continue
        invalid=level-side*cfg["invalidation_atr"]*atr
        if side*(m1.close.iloc[-1]-invalid)<=0:
            continue
        events=thin_events(base_events(features,side,lookback,cfg["half_width_atr"]))
        qualified=events.loc[matches(events,cfg)] if not events.empty else events
        confirmed=not qualified.empty and qualified.index[-1]==close_time
        validated=bool(winner.get("qualified"))
        start=cfg["session_utc"]
        out["zones"].append({"direction":"BUY" if side==1 else "SELL",
            "low":float(level-cfg["half_width_atr"]*atr), "high":float(level+cfg["half_width_atr"]*atr),
            "invalidation":float(invalid), "reference_price":float(latest.close),
            "reaction_distance":float(cfg["reaction_atr"]*atr), "reaction_atr":cfg["reaction_atr"],
            "horizon_minutes":cfg["horizon_minutes"], "session_wib":f"{(start+7)%24:02d}:00–{(start+13)%24:02d}:00 WIB",
            "session_active":start <= close_time.hour < start+6,
            "state":"CONFIRMED_REACTION" if confirmed and validated else "WAIT_M5_CONFIRMATION" if validated else "RESEARCH_ONLY",
            "probability":winner["holdout"]["probability"] if validated else None,
            "n_holdout":winner["holdout"]["n"], "validated":validated,
            "probability_condition":"after matching M5 confirmation, session and filters",
            "config":cfg})
    out.update(state="MAP_READY" if out["zones"] else "NO_ACTIVE_VALIDATED_ZONE",
               last_m1_utc=m1.index[-1].isoformat(), last_m5_close_utc=close_time.isoformat(),
               source="CTRADER_READ_ONLY_M1")
    return out


def load_result(path=RESULT_PATH):
    return json.loads(Path(path).read_text())
