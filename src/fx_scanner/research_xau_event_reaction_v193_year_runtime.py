from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .research_xau_event_conditioning_v193 import (
    build_conditioning_frames,
    event_conditioning_from_frames,
)
from .research_xau_event_reaction_v193 import (
    HistoricalEvent,
    build_reaction_atlas,
    cluster_events,
    reaction_for_cluster,
)

ARTIFACT_CONTRACT = "XAU_EVENT_REACTION_V193_YEAR_SHARD_1"


@dataclass(frozen=True)
class _PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def _year() -> int:
    year = int(os.getenv("XAU_V193_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V193_YEAR_INVALID:{year}")
    return year


def _path_env(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"{name}_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"{name}_NOT_FOUND:{path}")
    return path


def _output_path(year: int) -> Path:
    raw = os.getenv(
        "XAU_V193_YEAR_OUTPUT",
        f"artifacts/xau-event-reaction-v193-{year}.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_V193_YEAR_OUTPUT_REQUIRED")
    return Path(raw)


def _load_corpus(path: Path, year: int) -> tuple[HistoricalEvent, ...]:
    payload = json.loads(path.read_text())
    rows = list(payload.get("events") or [])
    output: list[HistoricalEvent] = []
    for row in rows:
        raw_at = str(row.get("scheduled_at") or "")
        if not raw_at:
            continue
        at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        if at.tzinfo is None:
            continue
        at = at.astimezone(UTC)
        if at.year != year:
            continue
        family = str(row.get("family") or "OTHER_USD")
        if family == "OTHER_USD":
            continue
        output.append(
            HistoricalEvent(
                event_id=str(row.get("event_id") or ""),
                scheduled_at=at,
                title=str(row.get("title") or ""),
                family=family,
                impact=str(row.get("impact") or "UNKNOWN"),
                source=str(row.get("source") or "UNKNOWN"),
                source_tier=str(row.get("source_tier") or "UNKNOWN"),
                actual=row.get("actual"),
                forecast=row.get("forecast"),
                previous=row.get("previous"),
            )
        )
    return tuple(sorted(output, key=lambda item: (item.scheduled_at, item.event_id)))


def _load_price(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V193 price CSV missing columns: {sorted(missing)}")

    raw_ts = frame["timestamp"]
    if pd.api.types.is_numeric_dtype(raw_ts):
        numeric = pd.to_numeric(raw_ts, errors="coerce")
        magnitude = float(numeric.dropna().abs().median()) if numeric.notna().any() else 0.0
        if magnitude > 1e14:
            unit = "us"
        elif magnitude > 1e11:
            unit = "ms"
        elif magnitude > 1e9:
            unit = "s"
        else:
            unit = "s"
        frame["timestamp"] = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        frame["timestamp"] = pd.to_datetime(raw_ts, utc=True, errors="coerce")

    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise RuntimeError("V193 price CSV parsed empty")
    return frame.set_index("timestamp")


def _bars_for_reaction(frame: pd.DataFrame, event_at: datetime) -> tuple[_PriceBar, ...]:
    start = event_at - timedelta(hours=8)
    end = event_at + timedelta(minutes=75)
    sample = frame.loc[(frame.index >= start) & (frame.index <= end)]
    rows: list[_PriceBar] = []
    for ts, row in sample.iterrows():
        dt = ts.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        rows.append(
            _PriceBar(
                dt.astimezone(UTC),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
            )
        )
    return tuple(rows)


def _conditioning_key(conditioning: dict[str, Any]) -> str:
    mtf = dict(conditioning.get("mtf") or {})
    h1 = dict(mtf.get("H1") or {})
    h4 = dict(mtf.get("H4") or {})
    sd = dict(conditioning.get("supply_demand") or {})
    parts = [
        f"H4:{h4.get('ema_stack','UNKNOWN')}/{h4.get('market_structure','UNKNOWN')}",
        f"H1:{h1.get('ema_stack','UNKNOWN')}/{h1.get('market_structure','UNKNOWN')}",
        f"SD:{sd.get('active_reaction_direction','NONE')}/{sd.get('source_timeframe','NONE')}/{sd.get('source_freshness','NONE')}",
    ]
    return "|".join(parts)


def run() -> int:
    year = _year()
    corpus_path = _path_env("XAU_V193_CORPUS_JSON")
    price_path = _path_env("XAU_V193_PRICE_CSV")
    output_path = _output_path(year)

    events = _load_corpus(corpus_path, year)
    price = _load_price(price_path)
    frames = build_conditioning_frames(price.reset_index())
    clusters = cluster_events(events)

    reactions: list[dict[str, Any]] = []
    skipped_no_price = 0
    for cluster in clusters:
        bars = _bars_for_reaction(price, cluster.scheduled_at)
        if len(bars) < 30:
            skipped_no_price += 1
            continue
        reaction = reaction_for_cluster(cluster, bars)
        if reaction is None:
            skipped_no_price += 1
            continue
        conditioning = event_conditioning_from_frames(
            frames,
            event_at=cluster.scheduled_at,
            supply_demand_lookback_days=90,
        )
        reaction["conditioning"] = conditioning
        reaction["conditioning_key"] = _conditioning_key(conditioning)
        reaction["price_source"] = "DUKASCOPY_PUBLIC_M1"
        reaction["execution_influence"] = False
        reaction["execution_authority"] = False
        reactions.append(reaction)

    atlas = build_reaction_atlas(reactions, minimum_samples=10)
    payload = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "year": year,
        "event_count": len(events),
        "cluster_count": len(clusters),
        "reaction_count": len(reactions),
        "skipped_no_price": skipped_no_price,
        "price_bar_count": len(price),
        "price_start": price.index.min().isoformat(),
        "price_end": price.index.max().isoformat(),
        "atlas": atlas,
        "reactions": reactions,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )
    healthy = len(reactions) >= 10
    print(
        "XAU_EVENT_REACTION_V193_YEAR "
        f"year={year} events={len(events)} clusters={len(clusters)} "
        f"reactions={len(reactions)} skipped_no_price={skipped_no_price} "
        f"bars={len(price)} healthy={int(healthy)} "
        f"artifact={output_path} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
