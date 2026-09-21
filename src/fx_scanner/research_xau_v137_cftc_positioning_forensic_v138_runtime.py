from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch
from .research_xau_v135_macro_regime_v136_runtime import _load_macro
from .research_xau_v137_cftc_positioning_forensic_v138 import (
    GOLD_CFTC_CONTRACT_MARKET_CODE,
    evaluate_v138,
)

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}
CFTC_YEARS = tuple(range(2011, 2027))
CFTC_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


def _normalize_code(value) -> str:
    text = str(value).replace('"', "").strip()
    return text[:-2] if text.endswith(".0") else text


def _download_year(session: requests.Session, year: int):
    url = CFTC_URL.format(year=year)
    response = session.get(url, timeout=45)
    response.raise_for_status()
    payload = response.content
    digest = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith((".txt", ".csv"))]
        if not names:
            raise RuntimeError(f"CFTC_NO_TEXT_FILE:{year}")
        with archive.open(names[0]) as fh:
            frame = pd.read_csv(fh, low_memory=False)
    return frame, {
        "year": year,
        "url": url,
        "sha256": digest,
        "archive_member": names[0],
        "archive_bytes": len(payload),
        "rows": len(frame),
    }


def _load_cftc():
    required = {
        "As_of_Date_Form_YYYY-MM-DD",
        "CFTC_Contract_Market_Code",
        "Open_Interest_All",
        "Prod_Merc_Positions_Long_All",
        "Prod_Merc_Positions_Short_All",
        "Swap_Positions_Long_All",
        "Swap__Positions_Short_All",
        "M_Money_Positions_Long_All",
        "M_Money_Positions_Short_All",
    }
    raw_rows = []
    sources = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Forex-scanner-research/1.0"})
        for year in CFTC_YEARS:
            frame, meta = _download_year(session, year)
            missing = sorted(required - set(frame.columns))
            if missing:
                raise RuntimeError(f"CFTC_SCHEMA_MISSING:{year}:{missing}")
            codes = frame["CFTC_Contract_Market_Code"].map(_normalize_code)
            gold = frame.loc[codes == GOLD_CFTC_CONTRACT_MARKET_CODE].copy()
            if gold.empty:
                raise RuntimeError(f"CFTC_GOLD_MISSING:{year}")
            sources.append({**meta, "gold_rows": len(gold)})
            for _, row in gold.iterrows():
                raw_rows.append(
                    {
                        "report_date": pd.to_datetime(
                            row["As_of_Date_Form_YYYY-MM-DD"], errors="raise"
                        ).date(),
                        "open_interest": float(row["Open_Interest_All"]),
                        "managed_money_long": float(row["M_Money_Positions_Long_All"]),
                        "managed_money_short": float(row["M_Money_Positions_Short_All"]),
                        "producer_long": float(row["Prod_Merc_Positions_Long_All"]),
                        "producer_short": float(row["Prod_Merc_Positions_Short_All"]),
                        "swap_long": float(row["Swap_Positions_Long_All"]),
                        "swap_short": float(row["Swap__Positions_Short_All"]),
                    }
                )
    # Some annual archives can overlap at the year boundary; keep one report per date.
    dedup = {row["report_date"]: row for row in raw_rows}
    rows = tuple(dedup[d] for d in sorted(dedup))
    return rows, sources


def _compact(metrics):
    return {
        "n": metrics["completed_trades"],
        "pf": metrics["profit_factor"],
        "exp": metrics["expectancy_r"],
        "dd_r": metrics["max_drawdown_r"],
        "wr": metrics["win_rate"],
    }


def _print_period(label, block):
    print(
        "V138_PERIOD "
        + json.dumps(
            {
                "period": label,
                "n": block["count"],
                "coverage": block["cot_coverage"],
                "all": _compact(block["metrics"]),
                "states": {
                    k: _compact(v) for k, v in block["by_cot_state"].items()
                },
                "extended_strong": {
                    "n": block["extended_strong_bull"]["count"],
                    "all": _compact(block["extended_strong_bull"]["metrics"]),
                    "states": {
                        k: _compact(v)
                        for k, v in block["extended_strong_bull"]["by_cot_state"].items()
                    },
                    "state_x_oi": {
                        k: _compact(v)
                        for k, v in block["extended_strong_bull"]["cot_state_x_oi"].items()
                    },
                },
            },
            sort_keys=True,
        )
    )


def run():
    bars = _fetch(CONT)
    macro, macro_meta = _load_macro()
    cot_rows, cot_sources = _load_cftc()
    data = evaluate_v138(
        bars,
        macro_series=macro,
        cot_raw_rows=cot_rows,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    data["macro_source_metadata"] = macro_meta
    data["cftc_source_metadata"] = cot_sources

    path = Path(
        os.getenv(
            "V138_EVIDENCE_OUTPUT",
            "artifacts/xau-v137-cftc-positioning-forensic-v138.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    print(
        "V138_CFTC "
        + json.dumps(
            {
                "rows": data["cot_rows"],
                "first": data["cot_first_report"],
                "last": data["cot_last_report"],
                "years": len(cot_sources),
                "gold_rows_downloaded": sum(x["gold_rows"] for x in cot_sources),
            },
            sort_keys=True,
        )
    )
    _print_period("FULL", data["full"])
    _print_period("PRE2025", data["pre2025"])
    _print_period("RECENT", data["recent"])
    print("V138_DECISION " + json.dumps({"diagnostic_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
