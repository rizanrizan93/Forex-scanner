"""Public M1 corpus with hashes and atomic cache; no yield interpolation.

Install requirements-cross-asset-research.txt first. Fixed EST source OPEN
timestamps become UTC completed times in cross_asset_research.load_directory.
"""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from histdata_fetcher import fetch_data

SYMBOLS = (
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDCHF",
    "USDJPY",
    "XAGUSD",
    "EURGBP",
    "UDXUSD",
    "SPXUSD",
)


def fetch_symbol(symbol, directory, start, end):
    for year in range(start, end + 1):
        output = directory / f"{symbol}_{year}.parquet"
        if output.exists():
            continue
        result = fetch_data(
            pair=symbol,
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
            timeframe="1min",
            output_format=None,
            max_workers=1,
        )
        metadata = {
            "symbol": symbol,
            "year": year,
            "source": "HISTDATA_PUBLIC_SECONDARY",
            "provider_commit": "4a3c11b67f97758f6e3f77a3e5905b6aa87367b8",
            "timezone": "FIXED_EST_UTC_MINUS_5",
            "bar_timestamp": "OPEN",
            "rows": len(result.data),
            "failures": str(result.failed_periods),
        }
        if len(result.data):
            temporary = output.with_suffix(".part")
            result.data.to_parquet(temporary)
            metadata["sha256"] = hashlib.sha256(temporary.read_bytes()).hexdigest()
            temporary.replace(output)
        output.with_suffix(".provenance.json").write_text(
            json.dumps(metadata, indent=2)
        )
        print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(
            executor.map(
                lambda symbol: fetch_symbol(
                    symbol, args.directory, args.start_year, args.end_year
                ),
                SYMBOLS,
            )
        )
