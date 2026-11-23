"""Read-only public R3 XAU market source for R28.1 shadow inference.

No credentials, account ids, order APIs or trading operations. Uses only
the existing public cTrader MARKET_DATA_READ_ONLY feed with strict time gates.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import json
from urllib.request import Request, urlopen

import pandas as pd

CONTRACT = "RIZAN_MANUAL_R3_MARKET_V1"
SOURCE = "CTRADER_MARKET_DATA_READ_ONLY"
URL = "https://rizan-bridge.duckdns.org:25345/bootstrap125/manual-r3.json"
MAX_BYTES = 5_000_000


def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("NAIVE_MARKET_TIMESTAMP")
    return t.tz_convert("UTC")


def read_m1(*, now, payload=None, opener=urlopen):
    now = utc(now)
    if payload is None:
        request = Request(URL + "?r281=" + str(now.value // 30_000_000_000),
                          headers={"User-Agent": "RIZAN-R281-shadow-readonly/1",
                                   "Cache-Control": "no-cache"})
        with opener(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("PUBLIC_M1_OVERSIZED")
        payload = json.loads(raw)
    if (not isinstance(payload, dict) or payload.get("contract") != CONTRACT
            or payload.get("symbol") != "XAUUSD" or payload.get("source") != SOURCE
            or payload.get("execution_authority") is not False
            or payload.get("execution_influence") is not False):
        raise ValueError("PUBLIC_M1_CONTRACT_INVALID")
    at = utc(payload["as_of"])
    if not -5 <= (now - at).total_seconds() <= 90:
        raise ValueError("PUBLIC_M1_STALE")
    rows = payload.get("m1")
    if not isinstance(rows, list) or not 2000 <= len(rows) <= 12000:
        raise ValueError("PUBLIC_M1_HISTORY_COUNT_INVALID")
    first, last = None, None
    data = []
    for row in rows:
        ts = utc(row["timestamp"])
        v = [row[k] for k in ("open", "high", "low", "close")]
        if (ts.second or ts.microsecond or ts + pd.Timedelta(minutes=1) > now
                or any(type(a) not in (int, float) or not isfinite(a) for a in v)
                or not 0 < v[2] <= min(v[0], v[3]) <= max(v[0], v[3]) <= v[1]
                or last is not None and ts <= last):
            raise ValueError("PUBLIC_M1_CANDLE_INVALID")
        last = ts
        if first is None:
            first = ts
        data.append((ts, *v))
    if not 0 <= (now - last - pd.Timedelta(minutes=1)).total_seconds() <= 120:
        raise ValueError("PUBLIC_M1_LAST_BAR_STALE")
    f = pd.DataFrame(data, columns=["time", "o", "h", "l", "c"]).set_index("time")
    return f, {"as_of": at.isoformat(), "last_closed_m1": (last + pd.Timedelta(minutes=1)).isoformat(),
               "source": SOURCE, "bars": len(f)}


def aggregate(f, tf, *, now):
    """Output closed candles at UTC *open*, matching the historical index."""
    if tf not in ("1h", "4h", "1D", "1W"):
        raise ValueError("UNSUPPORTED_TF")
    now = utc(now)
    if tf == "1W":
        week = f.index.floor("D") - pd.to_timedelta(f.index.dayofweek, unit="D")
        g = f.groupby(week).agg(
            o=("o", "first"), h=("h", "max"), l=("l", "min"),
            c=("c", "last"), minutes=("c", "size")
        )
        g = g.loc[(g.minutes >= 6000) & (g.index + pd.Timedelta(days=7) <= now)]
    else:
        frequency = {"1h": "1h", "4h": "4h", "1D": "1D"}[tf]
        minimum = {"1h": 60, "4h": 240, "1D": 1100}[tf]
        g = f.resample(frequency, label="left", closed="left").agg(
            o=("o", "first"), h=("h", "max"), l=("l", "min"),
            c=("c", "last"), minutes=("c", "size")
        )
        g = g.loc[(g.minutes >= minimum) &
                  (g.index + pd.Timedelta(frequency) <= now)]
    return g.drop(columns="minutes").dropna()


def combine_history(archive, broker, tf):
    """Causally replace any overlap; never join disconnected price regimes."""
    if broker is None or broker.empty:
        return None
    if not archive.index.tz or not broker.index.tz:
        return None
    # Price scale/units guard: a broker close should agree to within 2%.
    common = archive.index.intersection(broker.index)
    if len(common):
        diff = (archive.loc[common, "c"] / broker.loc[common, "c"] - 1).abs()
        if not (diff <= .02).all():
            return None
    else:
        gap = broker.index[0] - archive.index[-1]
        tolerance = {"1h": "72h", "4h": "96h", "1D": "7D", "1W": "14D"}[tf]
        if gap > pd.Timedelta(tolerance):
            # Do not fabricate intermediate bars across an unknown gap.
            return None
    prior = archive.loc[archive.index < broker.index[0]]
    assembled = pd.concat([prior, broker]).sort_index()
    if assembled.index.has_duplicates or not assembled.index.is_monotonic_increasing:
        return None
    return assembled


def live_frame(archive, tf, *, now, payload=None):
    f, meta = read_m1(now=now, payload=payload)
    broker = aggregate(f, tf, now=now)
    merged = combine_history(archive, broker, tf)
    if merged is None:
        return None, {**meta, "status": "LIVE_CONTEXT_NOT_JOINABLE",
                      "native_closed": int(len(broker))}
    return merged, {**meta, "status": "VALID_CTRADER_READONLY",
                    "native_closed": int(len(broker)),
                    "latest_tf_open": broker.index[-1].isoformat()}
