from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .research_xau_histdata_download_v193 import FIXED_EST, PROVIDER_COMMIT, SOURCE_TIER, _normalize_frame
from .research_xau_slr_v390 import (
    ARTIFACT_CONTRACT,
    BASE_COST_PRICE,
    RESEARCH_VERSION,
    STRESS_COST_PRICE,
    SYMBOL,
    config_grid,
    prepare_m5,
    simulate_config,
    summarize_trades,
)

SOURCE = "HISTDATA_XAUUSD_M1"


def _year() -> int:
    value = int(os.getenv("XAU_SLR_V390_YEAR", "0") or 0)
    current = datetime.now(tz=UTC).year
    if value < 2012 or value > current:
        raise SystemExit(f"XAU_SLR_V390_YEAR_INVALID:{value}")
    return value


def _window(year: int) -> tuple[date, date]:
    start = date(year - 1, 10, 1)
    if year == datetime.now(tz=UTC).year:
        end = datetime.now(tz=UTC).date()
    else:
        end = date(year + 1, 1, 2)
    return start, end


def _paths(year: int) -> tuple[Path, Path, Path]:
    csv_path = Path(os.getenv("XAU_SLR_V390_PRICE_CSV", f"/tmp/histdata/xau-slr-v390-{year}.csv"))
    provenance = Path(
        os.getenv(
            "XAU_SLR_V390_PROVENANCE",
            f"artifacts/xau-slr-v390-provenance-{year}.json",
        )
    )
    output = Path(
        os.getenv(
            "XAU_SLR_V390_OUTPUT",
            f"artifacts/xau-slr-v390-{year}.json",
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
        pair=SYMBOL,
        start_date=start,
        end_date=end,
        timeframe="1min",
        output_format=None,
        max_workers=1,
    )
    if result.data.empty:
        raise SystemExit(f"XAU_SLR_V390_HISTDATA_EMPTY:{year}")

    normalized = _normalize_frame(result.data)
    start_utc = datetime.combine(start, datetime.min.time(), tzinfo=FIXED_EST).astimezone(UTC)
    end_exclusive = (
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=FIXED_EST).astimezone(UTC)
    )
    normalized = normalized[
        (normalized["timestamp"] >= start_utc) & (normalized["timestamp"] < end_exclusive)
    ].reset_index(drop=True)
    if normalized.empty:
        raise SystemExit(f"XAU_SLR_V390_NORMALIZED_EMPTY:{year}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(csv_path, index=False)
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
        "contract": "XAU_SLR_HISTDATA_M1_V390_1",
        "source": SOURCE,
        "source_tier": SOURCE_TIER,
        "provider_package": "histdata-fetcher",
        "provider_commit": PROVIDER_COMMIT,
        "pair": SYMBOL,
        "timeframe": "M1",
        "source_timestamp_contract": "FIXED_EST_UTC_MINUS5_NO_DST",
        "normalized_timestamp_contract": "UTC",
        "year": year,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "partial_current_year": year == datetime.now(tz=UTC).year,
        "rows": len(normalized),
        "first_timestamp_utc": normalized["timestamp"].iloc[0].isoformat(),
        "last_timestamp_utc": normalized["timestamp"].iloc[-1].isoformat(),
        "sha256": _sha256(csv_path),
        "failed_periods": failed,
        "data_integrity_ok": len(failed) == 0,
        "execution_influence": False,
        "execution_authority": False,
    }
    provenance_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return payload


def run() -> int:
    year = _year()
    csv_path, provenance_path, output_path = _paths(year)
    provenance = _download(year, csv_path, provenance_path)

    price = pd.read_csv(csv_path)
    price["timestamp"] = pd.to_datetime(price["timestamp"], utc=True)
    for column in ("open", "high", "low", "close"):
        price[column] = pd.to_numeric(price[column], errors="raise")

    m5 = prepare_m5(price)
    configs: dict[str, Any] = {}
    total_trades = 0
    for config in config_grid():
        trades = simulate_config(m5, config, target_year=year)
        total_trades += len(trades)
        configs[config.config_id] = {
            "config": config.payload(),
            "trades": trades,
            "base": summarize_trades(trades, cost_price=BASE_COST_PRICE),
            "stress": summarize_trades(trades, cost_price=STRESS_COST_PRICE),
        }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "year": year,
        "partial_current_year": bool(provenance["partial_current_year"]),
        "price_provenance": provenance,
        "price_rows": len(price),
        "m5_rows": len(m5),
        "config_count": len(configs),
        "method": {
            "execution_timeframe": "M5_RESAMPLED_FROM_RAW_M1",
            "context_timeframes": ["H1", "H4"],
            "trigger": "COMPRESSION_PLUS_STRUCTURAL_BREAK_DISPLACEMENT",
            "entry": "FUTURE_SHALLOW_RETRACE_ONLY",
            "same_bar_policy": "STOP_FIRST",
            "one_trade_at_a_time_per_config": True,
            "base_cost_price_round_trip": BASE_COST_PRICE,
            "stress_cost_price_round_trip": STRESS_COST_PRICE,
            "cost_note": "Fixed adverse price-cost proxy; HistData M1 does not contain historical broker spread series.",
            "execution_authority": False,
        },
        "configs": configs,
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    best = max(
        configs.values(),
        key=lambda row: (
            float(row["base"]["expectancy_r"]),
            float(row["base"]["profit_factor_r"]),
        ),
    )
    print(
        "XAU_SLR_RAW_V390_YEAR "
        f"year={year} rows={len(price)} m5={len(m5)} configs={len(configs)} "
        f"trade_records={total_trades} best={best['config']['config_id']} "
        f"best_n={best['base']['completed']} best_pf={best['base']['profit_factor_r']:.4f} "
        f"best_exp={best['base']['expectancy_r']:.4f} partial={int(payload['partial_current_year'])} "
        f"failed_periods={len(provenance['failed_periods'])} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
