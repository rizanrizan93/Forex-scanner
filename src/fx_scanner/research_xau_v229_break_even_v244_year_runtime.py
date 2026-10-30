from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .research_xau_v229_break_even_v244 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RESEARCH_VERSION,
    simulate_year,
)
from .research_xau_histdata_download_v193 import (
    FIXED_EST,
    PROVIDER_COMMIT,
    SOURCE_TIER,
    _normalize_frame,
)

SOURCE = "HISTDATA_XAUUSD_M1"


def _year() -> int:
    year = int(os.getenv("XAU_V244_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V244_YEAR_INVALID:{year}")
    return year


def _window(year: int) -> tuple[date, date]:
    start = date(year - 1, 10, 1)
    if year == datetime.now(tz=UTC).year:
        end = datetime.now(tz=UTC).date()
    else:
        end = date(year + 1, 2, 2)
    return start, end


def _paths(year: int) -> tuple[Path, Path, Path]:
    csv_path = Path(
        os.getenv(
            "XAU_V244_PRICE_CSV",
            f"/tmp/histdata/xau-v244-{year}.csv",
        )
    )
    provenance = Path(
        os.getenv(
            "XAU_V244_PROVENANCE",
            f"artifacts/xau-v244-provenance-{year}.json",
        )
    )
    output = Path(
        os.getenv(
            "XAU_V244_OUTPUT",
            f"artifacts/xau-v229-break-even-v244-{year}.json",
        )
    )
    return csv_path, provenance, output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download(year: int, csv_path: Path, provenance_path: Path) -> dict[str, Any]:
    try:
        from histdata_fetcher import fetch_data
    except ModuleNotFoundError as exc:
        raise SystemExit("HISTDATA_FETCHER_NOT_INSTALLED") from exc

    start, end = _window(year)
    result = fetch_data(
        pair="XAUUSD",
        start_date=start,
        end_date=end,
        timeframe="1min",
        output_format=None,
        max_workers=1,
    )
    if result.data.empty:
        raise SystemExit(f"XAU_V244_HISTDATA_EMPTY:{year}")
    normalized = _normalize_frame(result.data)

    start_utc = datetime.combine(start, datetime.min.time(), tzinfo=FIXED_EST).astimezone(UTC)
    end_exclusive = (
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=FIXED_EST)
        .astimezone(UTC)
    )
    normalized = normalized[
        (normalized["timestamp"] >= start_utc)
        & (normalized["timestamp"] < end_exclusive)
    ].reset_index(drop=True)
    if normalized.empty:
        raise SystemExit(f"XAU_V244_NORMALIZED_EMPTY:{year}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(csv_path, index=False)
    checksum = _sha256(csv_path)
    payload: dict[str, Any] = {
        "contract": "XAU_HISTDATA_M1_V244_1",
        "source": SOURCE,
        "source_tier": SOURCE_TIER,
        "provider_package": "histdata-fetcher",
        "provider_commit": PROVIDER_COMMIT,
        "pair": "XAUUSD",
        "timeframe": "M1",
        "year": year,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "partial_current_year": year == datetime.now(tz=UTC).year,
        "rows": len(normalized),
        "first_timestamp_utc": normalized["timestamp"].iloc[0].isoformat(),
        "last_timestamp_utc": normalized["timestamp"].iloc[-1].isoformat(),
        "sha256": checksum,
        "failed_periods": [
            {
                "period_label": row.period_label,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "reason": row.reason,
            }
            for row in result.failed_periods
        ],
        "execution_influence": False,
        "execution_authority": False,
        "management_variants": ["BASELINE", "BE_0_5R", "BE_1_0R"],
    }
    provenance_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    return payload


def run() -> int:
    year = _year()
    csv_path, provenance_path, output_path = _paths(year)
    provenance = _download(year, csv_path, provenance_path)

    import pandas as pd

    price = pd.read_csv(csv_path)
    price["timestamp"] = pd.to_datetime(price["timestamp"], utc=True)
    for column in ("open", "high", "low", "close"):
        price[column] = pd.to_numeric(price[column], errors="raise")

    result = simulate_year(price, target_year=year)
    payload = {
        **result,
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "price_provenance": provenance,
        "price_rows": len(price),
        "price_start": price["timestamp"].iloc[0].isoformat(),
        "price_end": price["timestamp"].iloc[-1].isoformat(),
        "partial_current_year": bool(provenance["partial_current_year"]),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    completed = sum(
        str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
        and str(row.get("cost_mode") or "") == "BASE"
        for row in list(payload.get("trades") or [])
    )
    print(
        "XAU_V229_BREAK_EVEN_V244_YEAR "
        f"year={year} parents={payload['parent_h4_first_touch_count']} "
        f"plans={payload['plan_count']} base_completed={completed} "
        f"partial={int(payload['partial_current_year'])} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
