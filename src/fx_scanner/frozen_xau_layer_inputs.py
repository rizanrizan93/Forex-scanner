"""Read archived frozen XAU signal streams; never generate substitute signals."""

from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

MIN = 60_000_000_000
DAY = 1440 * MIN


def load_frozen(directory):
    directory = Path(directory)
    frames = []
    for year in range(2016, 2026):
        f = pd.read_csv(directory / "data" / f"xau-{year}.csv")
        f.index = pd.DatetimeIndex(pd.to_datetime(f.timestamp, utc=True))
        if year > 2016:
            f = f[f.index.tz_convert("Asia/Jakarta").year == year]
        frames.append(f[["open", "high", "low", "close"]])
    raw = pd.concat(frames)
    if raw.index.duplicated().any() or not raw.index.is_monotonic_increasing:
        raise ValueError("INVALID_FROZEN_ARCHIVE_INDEX")
    ts = raw.index.asi8
    calendar = pd.read_csv(directory / "data" / "events_2016_2025.csv")
    et = np.sort(
        pd.to_datetime(calendar.timestamp_utc, utc=True).astype("int64").unique()
    )
    macro = pd.read_csv(
        directory / "data" / "macro_daily.csv", parse_dates=["observation_date"]
    )
    macro = macro[
        (macro.observation_date >= "2015-10-01")
        & (macro.observation_date <= "2025-12-31")
    ]
    bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    records = []
    # SELL first at the same timestamp, matching archived hybrid replay.
    for group, side, col in ((6, -1, "DGS10"), (274, 1, "DFII10")):
        signal = np.load(directory / f"g-{group:04d}.npz", allow_pickle=False)
        ev, sg, atr, anchor = [signal[k] for k in ("ev", "sg", "atr", "anchor")]
        q = macro[["observation_date", col]].dropna()
        available = (
            pd.DatetimeIndex(q.observation_date.map(lambda x: x + 2 * bd))
            .tz_localize("America/New_York")
            .tz_convert("UTC")
            .asi8
        )
        delta = q[col].diff().to_numpy()
        st = ts[ev]
        ix = np.searchsorted(available, st, side="right") - 1
        safe = np.maximum(ix, 0)
        known = (ix >= 0) & (st - available[safe] <= 7 * DAY)
        keep = (
            (sg == side) & known & np.isfinite(delta[safe]) & (side * delta[safe] <= 0)
        )
        k = np.searchsorted(et, st - 30 * MIN, side="left")
        keep &= (k == len(et)) | (et[np.minimum(k, len(et) - 1)] > st + 495 * MIN)
        for a, ar, an in zip(ev[keep], atr[keep], anchor[keep]):
            at = raw.index[a]
            if 12 <= at.hour < 20 and at.tz_convert("Asia/Jakarta").year >= 2016:
                records.append(
                    {
                        "at": at,
                        "side": side,
                        "atr": float(ar),
                        "anchor": float(an),
                        "source_index": int(a),
                    }
                )
    records.sort(key=lambda t: t["at"])
    # Original synthetic cautious-variable profile, causal range shocks.
    hour = (ts % DAY) / (60 * MIN)
    prior = (raw.high - raw.low).shift(1)
    normal = prior.rolling(48, min_periods=12).mean()
    shock = (prior > 4 * normal).fillna(False).to_numpy()
    spread = np.where(hour < 6, 0.35, np.where(hour >= 15, 0.40, 0.25)) + 0.10 * shock
    near = np.zeros(len(ts), dtype=bool)
    for event in et:
        near[
            np.searchsorted(ts, event - 5 * MIN) : np.searchsorted(ts, event + 30 * MIN)
        ] = True
    raw["spread"] = spread + 0.25 * near
    ny = raw.index.tz_convert("America/New_York")
    dates = ny.normalize()
    cal = pd.date_range(
        dates.min() - pd.Timedelta(days=1), dates.max() + pd.Timedelta(days=1), freq="D"
    )
    weights = np.where(cal.weekday == 2, 3, np.where(cal.weekday < 5, 1, 0))
    cum = np.cumsum(weights)
    raw["roll"] = np.where(
        ny.hour >= 17,
        dates.map(pd.Series(cum, index=cal)),
        dates.map(pd.Series(cum - weights, index=cal)),
    ).astype(np.int64)
    # Archive ledger provides an independent timestamp/quote alignment audit.
    ledger = np.load(directory / "hybrid-audit-0-1.npz", allow_pickle=False)["ledger"]
    np.testing.assert_allclose(
        raw.open.iloc[ledger[:, 0].astype(int)], ledger[:, 23], atol=1e-9, rtol=0
    )
    np.testing.assert_allclose(
        raw.open.iloc[ledger[:, 1].astype(int)], ledger[:, 24], atol=1e-9, rtol=0
    )
    return raw, records
