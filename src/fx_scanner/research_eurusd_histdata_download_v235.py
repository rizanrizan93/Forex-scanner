from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .research_xau_histdata_download_v193 import (
    FIXED_EST,
    PROVIDER_COMMIT,
    SOURCE_TIER,
    _date_window,
    _normalize_frame,
    _sha256,
)

PAIR = "EURUSD"
SOURCE = "HISTDATA_EURUSD_M1"


def _year() -> int:
    value = int(os.getenv("EURUSD_V235_YEAR", "0") or 0)
    if value < 2012 or value > datetime.now(tz=UTC).year:
        raise SystemExit(f"EURUSD_V235_YEAR_INVALID:{value}")
    return value


def _paths(year: int) -> tuple[Path, Path]:
    csv_raw = os.getenv(
        "EURUSD_V235_PRICE_CSV",
        f"/tmp/histdata/eurusd-v235-{year}.csv",
    ).strip()
    provenance_raw = os.getenv(
        "EURUSD_V235_PRICE_PROVENANCE",
        f"artifacts/eurusd-v235-price-provenance-{year}.json",
    ).strip()
    if not csv_raw or not provenance_raw:
        raise SystemExit("EURUSD_V235_HISTDATA_PATH_REQUIRED")
    return Path(csv_raw), Path(provenance_raw)


def run() -> int:
    try:
        from histdata_fetcher import fetch_data
    except ModuleNotFoundError as exc:
        raise SystemExit("HISTDATA_FETCHER_NOT_INSTALLED") from exc

    year = _year()
    csv_path, provenance_path = _paths(year)
    start, end = _date_window(year)

    result = fetch_data(
        pair=PAIR,
        start_date=start,
        end_date=end,
        timeframe="1min",
        output_format=None,
        max_workers=1,
    )
    if result.data.empty:
        raise SystemExit(f"EURUSD_V235_HISTDATA_EMPTY:{year}")

    normalized = _normalize_frame(result.data)
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
        raise SystemExit(f"EURUSD_V235_HISTDATA_WINDOW_EMPTY:{year}")

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
        "contract": "EURUSD_HISTDATA_M1_SHARD_V235_1",
        "year": year,
        "source": SOURCE,
        "source_tier": SOURCE_TIER,
        "provider_package": "histdata-fetcher",
        "provider_commit": PROVIDER_COMMIT,
        "source_site": "https://www.histdata.com/",
        "pair": PAIR,
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
        "EURUSD_HISTDATA_M1_V235 "
        f"year={year} rows={len(normalized)} "
        f"periods={len(result.fetched_periods)} failed={len(failed)} "
        f"sha256={checksum[:16]} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
