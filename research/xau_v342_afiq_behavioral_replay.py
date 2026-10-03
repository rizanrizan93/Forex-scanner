from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import (
    build_htf_zones,
    bars_from_frame,
    causal_superseded_at,
    evaluate_first_touch,
    load_price_frame,
    resample_ohlc,
)
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity

SCHEMA = "XAU_V342_AFIQ_BEHAVIORAL_REPLAY_V1"
OFFSETS_MINUTES = (0, 15, 30, 60, 120)
WINDOWS = {"H4": 400, "H1": 560, "M30": 320, "M15": 256, "M5": 384}
RULES = {"H4": "4h", "H1": "1h", "M30": "30min", "M15": "15min", "M5": "5min"}
TF_MINUTES = {"H4": 240, "H1": 60, "M30": 30, "M15": 15, "M5": 5}


def _completed_window(frame: pd.DataFrame, timeframe: str, as_of: datetime) -> pd.DataFrame:
    delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    known = frame[(frame["timestamp"] + delta) <= pd.Timestamp(ensure_utc(as_of))]
    return known.tail(WINDOWS[timeframe]).reset_index(drop=True)


def _m30_state(frame: pd.DataFrame, as_of: datetime) -> dict[str, Any]:
    work = _completed_window(frame, "M30", as_of)
    if len(work) < 24:
        return {"state": "UNKNOWN"}
    work = work.copy()
    work["ema20"] = work["close"].ewm(span=20, adjust=False).mean()
    last = work.iloc[-1]
    prior = work.iloc[-7:-1]
    close = float(last["close"])
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    ema20 = float(last["ema20"])
    if close > prior_high:
        state = "BULLISH_INTERNAL_BREAK"
    elif close < prior_low:
        state = "BEARISH_INTERNAL_BREAK"
    elif close > ema20:
        state = "BULLISH_INTERNAL_RANGE"
    elif close < ema20:
        state = "BEARISH_INTERNAL_RANGE"
    else:
        state = "NEUTRAL"
    return {
        "state": state,
        "close": close,
        "ema20": ema20,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "completed_at": (pd.Timestamp(last["timestamp"]) + pd.Timedelta(minutes=30)).isoformat(),
    }


def _zone_overlap(a: dict[str, Any], b: Any) -> float:
    if not a:
        return 0.0
    lo = max(float(a.get("low", 0.0)), float(b.low))
    hi = min(float(a.get("high", 0.0)), float(b.high))
    overlap = max(0.0, hi - lo)
    denom = max(1e-9, min(float(a.get("high", 0.0)) - float(a.get("low", 0.0)), float(b.high) - float(b.low)))
    return overlap / denom


def _snapshot(
    *,
    frames: dict[str, pd.DataFrame],
    as_of: datetime,
    price_now: float,
    touched_zone: Any,
) -> dict[str, Any]:
    h4 = _completed_window(frames["H4"], "H4", as_of)
    h1 = _completed_window(frames["H1"], "H1", as_of)
    m15 = _completed_window(frames["M15"], "M15", as_of)
    m5 = _completed_window(frames["M5"], "M5", as_of)
    if len(h4) < 24 or len(h1) < 24 or len(m15) < 20 or len(m5) < 20:
        return {"as_of": as_of.isoformat(), "state": "INSUFFICIENT_WINDOW"}

    evaluation = evaluate_sd_liquidity(
        bars_h1=bars_from_frame(h1, "H1"),
        bars_h4=bars_from_frame(h4, "H4"),
        bars_m15=bars_from_frame(m15, "M15"),
        bars_m5=bars_from_frame(m5, "M5"),
        as_of=as_of,
        price_now=price_now,
    )
    decision = dict(evaluation.get("decision_zone") or {})
    micro = dict(evaluation.get("micro_confirmation") or {})
    guide = dict(evaluation.get("entry_guide") or {})
    destination = dict(evaluation.get("structural_destination") or {})
    liquidity = dict(evaluation.get("liquidity_map") or {})
    candidates = list(evaluation.get("main_reversal_candidates") or [])
    exact = str(decision.get("zone_id") or "") == str(touched_zone.zone_id)
    overlap = _zone_overlap(decision, touched_zone)
    same_direction = str(decision.get("direction") or "") == str(touched_zone.direction)
    candidate_rank = None
    for idx, row in enumerate(candidates, start=1):
        if str(row.get("zone_id") or "") == str(touched_zone.zone_id):
            candidate_rank = idx
            break

    return {
        "as_of": as_of.isoformat(),
        "state": str(evaluation.get("state") or ""),
        "engine_contract": evaluation.get("contract"),
        "expected_direction": evaluation.get("expected_reversal_direction"),
        "guide_state": guide.get("state"),
        "decision_zone_id": decision.get("zone_id"),
        "decision_timeframe": decision.get("timeframe"),
        "decision_direction": decision.get("direction"),
        "decision_low": decision.get("low"),
        "decision_high": decision.get("high"),
        "decision_exact_touched_zone": exact,
        "decision_overlap_ratio": overlap,
        "decision_same_direction": same_direction,
        "touched_zone_candidate_rank": candidate_rank,
        "micro_stage": micro.get("stage"),
        "confirmation_tier": micro.get("confirmation_tier"),
        "early_confirmed": bool(micro.get("early_confirmed")),
        "full_confirmed": bool(micro.get("confirmed")),
        "sweep_seen": bool(micro.get("sweep_seen")),
        "entry_reference": guide.get("entry_reference"),
        "invalidation": guide.get("invalidation"),
        "liquidity_warning": liquidity.get("warning"),
        "liquidity_side": liquidity.get("side"),
        "destination_price": destination.get("price"),
        "destination_timeframe": destination.get("timeframe"),
        "destination_zone_id": destination.get("zone_id"),
        "nearest_roadblock": dict(evaluation.get("nearest_roadblock") or {}),
        "structural_room_state": dict(evaluation.get("structural_room") or {}).get("state"),
        "roadblock_room_state": dict(evaluation.get("roadblock_room") or {}).get("state"),
        "m30": _m30_state(frames["M30"], as_of),
    }


def _m1_price_at(price: pd.DataFrame, as_of: datetime) -> float | None:
    rows = price[price["timestamp"] < pd.Timestamp(ensure_utc(as_of))]
    if rows.empty:
        return None
    return float(rows.iloc[-1]["close"])


def run(year: int, csv_path: Path, output: Path) -> dict[str, Any]:
    price = load_price_frame(csv_path)
    frames = {tf: resample_ohlc(price, rule) for tf, rule in RULES.items()}
    zones = build_htf_zones(price)
    superseded = causal_superseded_at(zones)
    episodes: list[dict[str, Any]] = []

    for zone in zones:
        valid_until = superseded.get(zone.zone_id)
        episode = evaluate_first_touch(price, zone=zone, valid_until=valid_until)
        if not episode:
            continue
        touch_at = ensure_utc(datetime.fromisoformat(str(episode["touch_at"]).replace("Z", "+00:00")))
        if touch_at.year != year:
            continue
        outcome_at = ensure_utc(datetime.fromisoformat(str(episode["outcome_at"]).replace("Z", "+00:00")))
        snapshots: list[dict[str, Any]] = []
        for offset in OFFSETS_MINUTES:
            as_of = touch_at + timedelta(minutes=offset)
            if offset > 0 and as_of > outcome_at:
                break
            px = _m1_price_at(price, as_of)
            if px is None:
                continue
            snap = _snapshot(frames=frames, as_of=as_of, price_now=px, touched_zone=zone)
            snap["offset_minutes"] = offset
            snapshots.append(snap)

        valid = [s for s in snapshots if s.get("state") != "INSUFFICIENT_WINDOW"]
        any_exact = any(bool(s.get("decision_exact_touched_zone")) for s in valid)
        any_same_direction = any(bool(s.get("decision_same_direction")) for s in valid)
        any_early = any(bool(s.get("early_confirmed")) for s in valid)
        any_full = any(bool(s.get("full_confirmed")) for s in valid)
        any_sweep = any(bool(s.get("sweep_seen")) for s in valid)
        first_confirm = next((int(s["offset_minutes"]) for s in valid if s.get("early_confirmed")), None)
        m30_aligned = False
        for s in valid:
            state = str(dict(s.get("m30") or {}).get("state") or "")
            if zone.direction == "LONG" and state.startswith("BULLISH"):
                m30_aligned = True
            if zone.direction == "SHORT" and state.startswith("BEARISH"):
                m30_aligned = True

        episodes.append({
            "zone_id": zone.zone_id,
            "timeframe": zone.timeframe,
            "direction": zone.direction,
            "zone_low": float(zone.low),
            "zone_high": float(zone.high),
            "available_at": ensure_utc(zone.available_at).isoformat(),
            "touch_at": episode["touch_at"],
            "outcome_at": episode["outcome_at"],
            "outcome": episode["outcome"],
            "reaction_hit_050_atr": bool(episode.get("reaction_hit")),
            "break_hit": bool(episode.get("break_hit")),
            "reversal_after_sweep": bool(episode.get("reversal_after_sweep")),
            "turning_depth": episode.get("turning_depth"),
            "sweep_extension_atr": episode.get("sweep_extension_atr"),
            "v342_selected_exact": any_exact,
            "v342_selected_same_direction": any_same_direction,
            "v342_early_confirmed": any_early,
            "v342_full_confirmed": any_full,
            "v342_sweep_seen": any_sweep,
            "first_early_confirmation_delay_minutes": first_confirm,
            "m30_direction_aligned": m30_aligned,
            "snapshots": snapshots,
        })

    def rate(rows: list[dict[str, Any]], field: str) -> float | None:
        return None if not rows else sum(bool(r.get(field)) for r in rows) / len(rows)

    reactions = [r for r in episodes if r["reaction_hit_050_atr"]]
    breaks = [r for r in episodes if r["break_hit"]]
    confirmed = [r for r in episodes if r["v342_early_confirmed"]]
    confirmed_reactions = [r for r in confirmed if r["reaction_hit_050_atr"]]
    delays = [r["first_early_confirmation_delay_minutes"] for r in episodes if r["first_early_confirmation_delay_minutes"] is not None]
    outcome_counts = Counter(str(r["outcome"]) for r in episodes)

    payload = {
        "schema": SCHEMA,
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY",
        "causal": True,
        "execution_authority": False,
        "purpose": "Measure current V342 Afiq-style zone selection, liquidity/sweep recognition, confirmation timing, destination availability, and research-only M30 alignment at causal first-touch episodes.",
        "engine_under_test": "CURRENT_XAU_RIZAN_SD_LIQUIDITY_V342",
        "offsets_minutes": list(OFFSETS_MINUTES),
        "episode_count": len(episodes),
        "summary": {
            "reaction_050_rate": rate(episodes, "reaction_hit_050_atr"),
            "v342_exact_zone_selection_rate": rate(episodes, "v342_selected_exact"),
            "v342_same_direction_selection_rate": rate(episodes, "v342_selected_same_direction"),
            "v342_early_confirmation_rate": rate(episodes, "v342_early_confirmed"),
            "v342_full_confirmation_rate": rate(episodes, "v342_full_confirmed"),
            "v342_sweep_detection_rate": rate(episodes, "v342_sweep_seen"),
            "m30_alignment_rate": rate(episodes, "m30_direction_aligned"),
            "reaction_exact_zone_selection_rate": rate(reactions, "v342_selected_exact"),
            "break_exact_zone_selection_rate": rate(breaks, "v342_selected_exact"),
            "reaction_m30_alignment_rate": rate(reactions, "m30_direction_aligned"),
            "break_m30_alignment_rate": rate(breaks, "m30_direction_aligned"),
            "confirmed_episode_precision_for_050_reaction": None if not confirmed else len(confirmed_reactions) / len(confirmed),
            "confirmed_episode_count": len(confirmed),
            "median_early_confirmation_delay_minutes": None if not delays else float(pd.Series(delays).median()),
            "outcome_counts": dict(outcome_counts),
        },
        "episodes": episodes,
        "limitations": [
            "First-stage behavioral replay uses public M1 OHLC; it is not yet true bid/ask tick execution replay.",
            "M30 is research-only diagnostic and does not change production V342 in this run.",
            "V345 0.50 ATR reaction outcome is used as a neutral zone-reaction label, not as a trade TP or win-rate claim.",
            "News/macro are not reconstructed in this first-stage behavioral replay.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V342_AFIQ_BEHAVIORAL_REPLAY=" + json.dumps(payload["summary"], sort_keys=True))
    print(f"EPISODES={len(episodes)} OUTPUT={output}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.year, args.csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
