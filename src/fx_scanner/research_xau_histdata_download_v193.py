from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROVIDER_COMMIT = "4a3c11b67f97758f6e3f77a3e5905b6aa87367b8"
SOURCE = "HISTDATA_XAUUSD_M1"
SOURCE_TIER = "PUBLIC_SECONDARY_MARKET_DATA"
FIXED_EST = timezone(timedelta(hours=-5))


def _year() -> int:
    value = int(os.getenv("XAU_V193_YEAR", "0") or 0)
    if value < 2012 or value > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V193_YEAR_INVALID:{value}")
    return value


def _paths(year: int) -> tuple[Path, Path]:
    csv_raw = os.getenv(
        "XAU_V193_PRICE_CSV",
        f"/tmp/histdata/xau-v193-{year}.csv",
    ).strip()
    provenance_raw = os.getenv(
        "XAU_V193_PRICE_PROVENANCE",
        f"artifacts/xau-v193-price-provenance-{year}.json",
    ).strip()
    if not csv_raw or not provenance_raw:
        raise SystemExit("XAU_V193_HISTDATA_PATH_REQUIRED")
    return Path(csv_raw), Path(provenance_raw)


def _date_window(year: int) -> tuple[date, date]:
    # Supply/Demand conditioning uses up to 90 days pre-event. Oct 1 of the
    # previous year safely covers January events while keeping the download bounded.
    start = date(year - 1, 10, 1)
    if year == datetime.now(tz=UTC).year:
        end = datetime.now(tz=UTC).date()
    else:
        end = date(year + 1, 1, 2)
    return start, end


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"datetime", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"HistData frame missing columns: {sorted(missing)}")

    out = frame.loc[:, ["datetime", "open", "high", "low", "close"]].copy()
    ts = pd.to_datetime(out["datetime"], errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        raise RuntimeError("HistData timestamp unexpectedly timezone-aware")
    ts = ts.dt.tz_localize(FIXED_EST).dt.tz_convert("UTC")
    out["timestamp"] = ts

    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"])
    out = out.drop(columns=["datetime"])
    out = out.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    out = out.loc[:, ["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)
    if out.empty:
        raise RuntimeError("HistData normalized frame is empty")

    invalid = (
        (out["low"] > out[["open", "close"]].min(axis=1))
        | (out["high"] < out[["open", "close"]].max(axis=1))
        | (out["high"] < out["low"])
    )
    if bool(invalid.any()):
        raise RuntimeError("HistData normalized OHLC validation failed")
    return out


def run() -> int:
    try:
        from histdata_fetcher import fetch_data
    except ModuleNotFoundError as exc:
        raise SystemExit("HISTDATA_FETCHER_NOT_INSTALLED") from exc

    year = _year()
    csv_path, provenance_path = _paths(year)
    start, end = _date_window(year)

    result = fetch_data(
        pair="XAUUSD",
        start_date=start,
        end_date=end,
        timeframe="1min",
        output_format=None,
        max_workers=1,
    )
    if result.data.empty:
        raise SystemExit(f"XAU_V193_HISTDATA_EMPTY:{year}")

    normalized = _normalize_frame(result.data)

    # Keep only the explicit research window after converting fixed EST to UTC.
    start_utc = datetime.combine(start, datetime.min.time(), tzinfo=FIXED_EST).astimezone(UTC)
    end_exclusive_utc = (
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=FIXED_EST)
        .astimezone(UTC)
    )
    normalized = normalized[
        (normalized["timestamp"] >= start_utc)
        & (normalized["timestamp"] < end_exclusive_utc)
    ].reset_index(drop=True)
    if normalized.empty:
        raise SystemExit(f"XAU_V193_HISTDATA_WINDOW_EMPTY:{year}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(csv_path, index=False)
    checksum = _sha256(csv_path)

    failed = [
        {
            "period_label": item.period_label,
            "period_start": item.period_start.isoformat(),
            "period_end": item.period_end.isoformat(),
            "reason": item.reason,
        }
        for item in result.failed_periods
    ]
    payload: dict[str, Any] = {
        "contract": "XAU_HISTDATA_M1_SHARD_V193_1",
        "year": year,
        "source": SOURCE,
        "source_tier": SOURCE_TIER,
        "provider_package": "histdata-fetcher",
        "provider_commit": PROVIDER_COMMIT,
        "source_site": "https://www.histdata.com/",
        "pair": "XAUUSD",
        "timeframe": "M1",
        "source_timestamp_contract": "FIXED_EST_UTC_MINUS5_NO_DST",
        "normalized_timestamp_contract": "UTC",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "rows": len(normalized),
        "first_timestamp_utc": normalized["timestamp"].iloc[0].isoformat(),
        "last_timestamp_utc": normalized["timestamp"].iloc[-1].isoformat(),
        "fetched_periods": list(result.fetched_periods),
        "failed_periods": failed,
        "normalized_csv_sha256": checksum,
        "normalized_csv_path": str(csv_path),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    provenance_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    print(
        "XAU_HISTDATA_M1_V193 "
        f"year={year} rows={len(normalized)} "
        f"periods={len(result.fetched_periods)} failed={len(failed)} "
        f"sha256={checksum[:16]} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
