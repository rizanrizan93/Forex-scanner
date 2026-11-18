"""R9 research-only: strict causal join of Dukascopy dollaridxusd H1 with R6 M5 events.
No trading, no model fitting, no claims about direction accuracy.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

def load_dollaridx_h1(path: str | Path, *, lag_minutes: int = 2) -> tuple[pd.DataFrame, str]:
    if lag_minutes < 0:
        raise ValueError("negative availability lag")
    raw = Path(path).read_bytes()
    d = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(d.columns):
        raise ValueError("missing H1 OHLC/timestamp")
    t = pd.to_datetime(pd.to_numeric(d.timestamp, errors="raise"), unit="ms", utc=True)
    if len(t) < 3 or t.isna().any() or t.duplicated().any() or not t.is_monotonic_increasing:
        raise ValueError("invalid source chronology")
    if (t.astype("int64") % (3600 * 10**9) != 0).any():
        raise ValueError("H1 timestamps must be UTC hour opens")
    p = d[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(p.to_numpy()).all() or (p <= 0).any().any():
        raise ValueError("invalid prices")
    if ((p.high < p[["open", "close", "low"]].max(axis=1)) |
        (p.low > p[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("invalid OHLC envelope")
    z = pd.DataFrame({"source_open_utc": t, "source_close_utc": t + pd.Timedelta(hours=1),
                      "available_utc": t + pd.Timedelta(hours=1, minutes=lag_minutes),
                      "close": p.close.to_numpy()})
    for h in (1, 3, 6):
        prior = z.close.shift(h)
        # Prevent return across weekend, holiday, missing bars; no forward filling.
        continuous = (z.source_open_utc - z.source_open_utc.shift(h) == pd.Timedelta(hours=h))
        z[f"ret_{h}h"] = ((z.close / prior) - 1).where(continuous)
    return z, hashlib.sha256(raw).hexdigest()

def join_r6_events(events: pd.DataFrame, dollar: pd.DataFrame, *, max_age_minutes: int = 120) -> pd.DataFrame:
    """events.entry_ns = R6 confirmed M5 right-edge ns, NOT future outcome timestamp."""
    if max_age_minutes <= 0:
        raise ValueError("invalid quote age")
    if not {"entry_ns", "side"}.issubset(events.columns):
        raise ValueError("R6 events missing required columns")
    e = events.copy()
    e["decision_utc"] = pd.to_datetime(e.entry_ns.astype("int64"), unit="ns", utc=True)
    if not e.decision_utc.is_monotonic_increasing:
        raise ValueError("events not chronological")
    if not dollar.available_utc.is_monotonic_increasing or dollar.available_utc.duplicated().any():
        raise ValueError("macro chronology invalid")
    out = pd.merge_asof(e, dollar, left_on="decision_utc", right_on="available_utc",
                        direction="backward", allow_exact_matches=True)
    age = (out.decision_utc - out.available_utc).dt.total_seconds() / 60
    out["macro_age_minutes"] = age
    out["macro_valid"] = age.ge(0) & age.le(max_age_minutes) & out.ret_1h.notna()
    for col in ("ret_1h", "ret_3h", "ret_6h"):
        out.loc[~out.macro_valid, col] = np.nan
    if (out.available_utc.dropna() > out.loc[out.available_utc.notna(), "decision_utc"]).any():
        raise AssertionError("future macro leak")
    return out

def conditional_gate(joined: pd.DataFrame, *, window: str = "ret_1h", mode: str = "contrarian") -> pd.DataFrame:
    if window not in {"ret_1h", "ret_3h", "ret_6h"} or mode not in {"contrarian", "aligned"}:
        raise ValueError("unregistered policy")
    # XAU BUY with USD proxy falling = aligned; opposite = contrarian.
    macro_direction = np.sign(joined[window])
    favorable = (joined.side * macro_direction < 0)
    keep = favorable if mode == "aligned" else ~favorable
    return joined.loc[joined.macro_valid & macro_direction.ne(0) & keep].copy()
