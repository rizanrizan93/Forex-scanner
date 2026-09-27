from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_histdata_download_v193 import FIXED_EST, _normalize_frame

RESEARCH_VERSION = "BRENT_CASH_PARITY_V238D_1"
HISTDATA_PAIR = "BCOUSD"
CASH_SYMBOL = "XBRUSD"
FUTURES_SYMBOL = "BRENT"
REFERENCE_SYMBOL = "XAUUSD"

FP_MARKETS_COMMODITIES_URL = "https://www.fpmarkets.com/id-id/commodities/"
FP_MARKETS_BRENT_FUTURES_ANNOUNCEMENT_URL = (
    "https://www.fpmarkets.com/blog/"
    "fp-markets-increases-its-commodity-offering-adding-brent-oil-cotton-and-sugar-futures/"
)
HISTDATA_REFERENCE_URL = "https://www.histdata.com/"

DEFAULT_START = date(2026, 8, 3)
DEFAULT_END = date(2026, 8, 28)


@dataclass(frozen=True, slots=True)
class ParityThresholds:
    min_overlap: int = 300
    min_return_corr: float = 0.98
    max_median_abs_pct: float = 0.03


def _parse_date_env(name: str, default: date) -> date:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return date.fromisoformat(raw)


def _output_path() -> Path:
    raw = os.getenv(
        "BRENT_V238D_OUTPUT",
        "artifacts/brent-cash-parity-v238d.json",
    ).strip()
    if not raw:
        raise SystemExit("BRENT_V238D_OUTPUT_REQUIRED")
    return Path(raw)


def _histdata_h1(start: date, end: date) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        from histdata_fetcher import fetch_data
    except ModuleNotFoundError as exc:
        raise SystemExit("HISTDATA_FETCHER_NOT_INSTALLED") from exc

    result = fetch_data(
        pair=HISTDATA_PAIR,
        start_date=start,
        end_date=end,
        timeframe="1min",
        output_format=None,
        max_workers=1,
    )
    if result.data.empty:
        raise SystemExit("BRENT_V238D_HISTDATA_EMPTY")

    normalized = _normalize_frame(result.data)
    start_utc = datetime.combine(start, time.min, tzinfo=FIXED_EST).astimezone(UTC)
    end_exclusive_utc = datetime.combine(
        end + timedelta(days=1), time.min, tzinfo=FIXED_EST
    ).astimezone(UTC)
    normalized = normalized[
        (normalized["timestamp"] >= start_utc)
        & (normalized["timestamp"] < end_exclusive_utc)
    ].reset_index(drop=True)
    if normalized.empty:
        raise SystemExit("BRENT_V238D_HISTDATA_WINDOW_EMPTY")

    hourly = (
        normalized.set_index("timestamp")
        .resample("1h", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )
    failed = [
        {
            "period_label": item.period_label,
            "period_start": item.period_start.isoformat(),
            "period_end": item.period_end.isoformat(),
            "reason": item.reason,
        }
        for item in result.failed_periods
    ]
    provenance = {
        "pair": HISTDATA_PAIR,
        "source": "HistData",
        "reference_url": HISTDATA_REFERENCE_URL,
        "source_timestamp_contract": "FIXED_EST_UTC_MINUS5_NO_DST",
        "normalized_timestamp_contract": "UTC",
        "m1_rows": len(normalized),
        "h1_rows": len(hourly),
        "failed_periods": failed,
    }
    return hourly, provenance


def _bars_frame(bars) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.Timestamp(bar.timestamp),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }
        for bar in bars
    ]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return (
        frame.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _broker_h1(feed, symbol: str, start: date, end: date) -> pd.DataFrame:
    start_utc = datetime.combine(start, time.min, tzinfo=UTC)
    end_utc = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    bars = feed.historical_bars(
        symbol,
        "H1",
        from_time=start_utc,
        to_time=end_utc,
        count=1000,
    )
    return _bars_frame(bars)


def _safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    if len(left) < 3 or len(right) < 3:
        return None
    value = left.corr(right)
    if pd.isna(value):
        return None
    return float(value)


def parity_metrics(reference: pd.DataFrame, broker: pd.DataFrame) -> dict[str, Any]:
    merged = reference[["timestamp", "close"]].rename(
        columns={"close": "reference_close"}
    ).merge(
        broker[["timestamp", "close"]].rename(columns={"close": "broker_close"}),
        on="timestamp",
        how="inner",
    )
    if merged.empty:
        return {
            "overlap": 0,
            "return_corr": None,
            "level_corr": None,
            "median_signed_basis_usd": None,
            "median_abs_basis_usd": None,
            "p95_abs_basis_usd": None,
            "median_abs_pct": None,
            "rmse_usd": None,
            "same_direction_share": None,
        }

    basis = merged["broker_close"] - merged["reference_close"]
    abs_basis = basis.abs()
    abs_pct = abs_basis / merged["reference_close"].abs().clip(lower=1e-12)
    ref_ret = merged["reference_close"].pct_change()
    broker_ret = merged["broker_close"].pct_change()
    valid_ret = ref_ret.notna() & broker_ret.notna()
    direction = (
        np.sign(ref_ret[valid_ret].to_numpy())
        == np.sign(broker_ret[valid_ret].to_numpy())
    )
    return {
        "overlap": int(len(merged)),
        "start": merged["timestamp"].iloc[0].isoformat(),
        "end": merged["timestamp"].iloc[-1].isoformat(),
        "return_corr": _safe_corr(ref_ret[valid_ret], broker_ret[valid_ret]),
        "level_corr": _safe_corr(
            merged["reference_close"], merged["broker_close"]
        ),
        "median_signed_basis_usd": float(np.median(basis.to_numpy(dtype=float))),
        "median_abs_basis_usd": float(np.median(abs_basis.to_numpy(dtype=float))),
        "p95_abs_basis_usd": float(np.quantile(abs_basis.to_numpy(dtype=float), 0.95)),
        "median_abs_pct": float(np.median(abs_pct.to_numpy(dtype=float))),
        "rmse_usd": float(
            sqrt(np.mean(np.square(basis.to_numpy(dtype=float))))
        ),
        "same_direction_share": (
            None if len(direction) == 0 else float(np.mean(direction))
        ),
    }


def cash_parity_pass(
    metrics: dict[str, Any],
    thresholds: ParityThresholds = ParityThresholds(),
) -> bool:
    corr = metrics.get("return_corr")
    median_abs_pct = metrics.get("median_abs_pct")
    return bool(
        int(metrics.get("overlap") or 0) >= thresholds.min_overlap
        and corr is not None
        and float(corr) >= thresholds.min_return_corr
        and median_abs_pct is not None
        and float(median_abs_pct) <= thresholds.max_median_abs_pct
    )


def run() -> int:
    policy = load_execution_policy(None)
    environment = str(policy.ctrader.get("environment", "")).upper()
    if environment != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("BRENT_V238D_DEMO_ONLY")

    start = _parse_date_env("BRENT_V238D_START", DEFAULT_START)
    end = _parse_date_env("BRENT_V238D_END", DEFAULT_END)
    if start >= end:
        raise SystemExit("BRENT_V238D_WINDOW_INVALID")

    histdata, histdata_provenance = _histdata_h1(start, end)
    feed = build_ctrader_research_feed(policy, (REFERENCE_SYMBOL,))
    try:
        feed.load_symbol_metadata((CASH_SYMBOL, FUTURES_SYMBOL))
        cash_contract = feed.symbol_info(CASH_SYMBOL)
        futures_contract = feed.symbol_info(FUTURES_SYMBOL)
        cash = _broker_h1(feed, CASH_SYMBOL, start, end)
        futures = _broker_h1(feed, FUTURES_SYMBOL, start, end)
    finally:
        feed.close()

    cash_metrics = parity_metrics(histdata, cash)
    futures_metrics = parity_metrics(histdata, futures)
    passed = cash_parity_pass(cash_metrics)
    preferred = CASH_SYMBOL if passed else None

    payload = {
        "artifact_contract": "BRENT_CASH_PARITY_V238D_1_EVIDENCE_1",
        "research_version": RESEARCH_VERSION,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "historical_reference": {
            "provider": "HistData",
            "pair": HISTDATA_PAIR,
            "semantics": "BRENT_CRUDE_OIL_IN_USD",
            "provenance": histdata_provenance,
        },
        "broker": {
            "name": "FP Markets",
            "environment": "DEMO",
            "cash_symbol": CASH_SYMBOL,
            "cash_symbol_id": int(getattr(cash_contract, "symbolId", 0) or 0),
            "futures_symbol": FUTURES_SYMBOL,
            "futures_symbol_id": int(getattr(futures_contract, "symbolId", 0) or 0),
        },
        "official_semantic_evidence": {
            "cash": {
                "symbol": CASH_SYMBOL,
                "description": "Brent Crude Oil vs US Dollar Cash",
                "source": FP_MARKETS_COMMODITIES_URL,
            },
            "future": {
                "symbol": FUTURES_SYMBOL,
                "description": "Brent Crude Oil vs US Dollar Future",
                "source": FP_MARKETS_COMMODITIES_URL,
                "introduced_as_new_futures_cfd": "2024-04-16",
                "announcement": FP_MARKETS_BRENT_FUTURES_ANNOUNCEMENT_URL,
            },
        },
        "parity": {
            CASH_SYMBOL: cash_metrics,
            FUTURES_SYMBOL: futures_metrics,
        },
        "thresholds": {
            "min_overlap": ParityThresholds.min_overlap,
            "min_return_corr": ParityThresholds.min_return_corr,
            "max_median_abs_pct": ParityThresholds.max_median_abs_pct,
        },
        "cash_parity_pass": passed,
        "preferred_historical_broker_symbol": preferred,
        "mapping_status": "SHADOW_REFERENCE" if passed else "UNRESOLVED",
        "interpretation": (
            "XBRUSD is the FP Markets Brent cash CFD and is the semantic candidate "
            "for the continuous HistData BCOUSD research series. BRENT is a distinct "
            "futures CFD introduced in 2024. H1 price parity is a confirmation gate, "
            "not execution evidence."
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
    }
    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "BRENT_CASH_PARITY_V238D "
        f"window={start}:{end} cash_overlap={cash_metrics['overlap']} "
        f"cash_corr={cash_metrics['return_corr']} cash_mape={cash_metrics['median_abs_pct']} "
        f"future_overlap={futures_metrics['overlap']} future_corr={futures_metrics['return_corr']} "
        f"mapping={preferred or 'UNRESOLVED'} execution_authority=0"
    )
    if not passed:
        raise SystemExit("BRENT_V238D_CASH_PARITY_GATE_FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
