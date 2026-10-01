from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from math import isfinite
from typing import Any, Iterable, Sequence

import pandas as pd

from .models import ensure_utc
from .research_xau_zone_path_v174 import wilson_lower_bound
from .research_xau_zone_reversal_depth_v225 import DepthEpisode

RESEARCH_VERSION = "XAU_RIZAN_AXY_DELTA_CALIBRATION_V323"
ARTIFACT_CONTRACT = "XAU_RIZAN_AXY_DELTA_CALIBRATION_V323_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

DELTA_FRACTIONS = (0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35, 0.40)
ENTRY_TIERS = ("A_RETEST", "X", "Y")
TARGET_MULTIPLES = (5, 8, 13)
SOURCE_TIMEFRAMES = ("H1", "H4")

IMPULSE_ATR_MULTIPLE = 0.75
STRUCTURAL_SL_BUFFER_ATR = 0.10
HORIZON_MINUTES = {"H1": 8 * 60, "H4": 16 * 60}


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _resample_m5(price_m1: pd.DataFrame) -> pd.DataFrame:
    if price_m1.empty:
        return pd.DataFrame()
    work = price_m1.loc[:, ["timestamp", "open", "high", "low", "close"]].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    out = (
        work.set_index("timestamp")
        .resample("5min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )
    previous_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - previous_close).abs(),
            (out["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.rolling(14, min_periods=8).mean()
    out["known_at"] = out["timestamp"] + pd.Timedelta(minutes=5)
    return out


def _anchor_for_episode(
    m5: pd.DataFrame,
    episode: DepthEpisode,
) -> dict[str, Any] | None:
    timeframe = str(episode.timeframe).upper()
    if timeframe not in HORIZON_MINUTES:
        return None
    touch_at = pd.Timestamp(ensure_utc(episode.touch_at))
    horizon_at = touch_at + pd.Timedelta(minutes=HORIZON_MINUTES[timeframe])
    prior_atr_rows = m5[
        (m5["known_at"] <= touch_at)
        & m5["atr14"].notna()
    ]
    if prior_atr_rows.empty:
        return None
    touch_atr = _f(prior_atr_rows.iloc[-1]["atr14"])
    if touch_atr is None or touch_atr <= 0:
        return None

    rows = m5[
        (m5["known_at"] > touch_at)
        & (m5["timestamp"] < horizon_at)
    ].reset_index(drop=True)
    if len(rows) < 5:
        return None

    direction = str(episode.direction).upper()
    proximal = float(episode.proximal)
    impulse_threshold = (
        proximal + IMPULSE_ATR_MULTIPLE * touch_atr
        if direction == "LONG"
        else proximal - IMPULSE_ATR_MULTIPLE * touch_atr
    )

    impulse_idx: int | None = None
    for i, row in rows.iterrows():
        if direction == "LONG" and float(row["high"]) >= impulse_threshold:
            impulse_idx = int(i)
            break
        if direction == "SHORT" and float(row["low"]) <= impulse_threshold:
            impulse_idx = int(i)
            break
    if impulse_idx is None:
        return None

    reclaim_idx: int | None = None
    for i in range(1, len(rows)):
        a = float(rows.iloc[i - 1]["close"])
        b = float(rows.iloc[i]["close"])
        if direction == "LONG" and a > proximal and b > proximal:
            reclaim_idx = i
            break
        if direction == "SHORT" and a < proximal and b < proximal:
            reclaim_idx = i
            break
    if reclaim_idx is None:
        return None

    scan_start = max(impulse_idx + 1, reclaim_idx)
    for i in range(max(1, scan_start), len(rows) - 1):
        prev_row = rows.iloc[i - 1]
        row = rows.iloc[i]
        next_row = rows.iloc[i + 1]
        if direction == "LONG":
            pivot = (
                float(row["low"]) <= float(prev_row["low"])
                and float(row["low"]) < float(next_row["low"])
                and float(next_row["close"]) > float(row["close"])
            )
            anchor = float(row["low"])
        else:
            pivot = (
                float(row["high"]) >= float(prev_row["high"])
                and float(row["high"]) > float(next_row["high"])
                and float(next_row["close"]) < float(row["close"])
            )
            anchor = float(row["high"])
        if not pivot:
            continue
        confirmed_at = pd.Timestamp(next_row["known_at"])
        if confirmed_at >= horizon_at:
            return None
        confirmed_atr = _f(next_row.get("atr14"))
        if confirmed_atr is None or confirmed_atr <= 0:
            confirmed_atr = touch_atr
        return {
            "a": anchor,
            "pivot_at": pd.Timestamp(row["timestamp"]),
            "confirmed_at": confirmed_at,
            "impulse_at": pd.Timestamp(rows.iloc[impulse_idx]["known_at"]),
            "reclaim_at": pd.Timestamp(rows.iloc[reclaim_idx]["known_at"]),
            "horizon_at": horizon_at,
            "touch_atr14_m5": float(touch_atr),
            "atr14_m5": float(confirmed_atr),
        }
    return None


def _first_fill_index(
    m1: pd.DataFrame,
    *,
    direction: str,
    entry: float,
    distal: float,
) -> int | None:
    for idx, row in m1.iterrows():
        close = float(row["close"])
        invalid = close < distal if direction == "LONG" else close > distal
        if invalid:
            return None
        if float(row["low"]) <= entry <= float(row["high"]):
            return int(idx)
    return None


def _resolve_trade(
    m1: pd.DataFrame,
    *,
    fill_index: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> str:
    for i in range(fill_index, len(m1)):
        row = m1.iloc[i]
        if direction == "LONG":
            stop_hit = float(row["low"]) <= sl
            target_hit = float(row["high"]) >= tp
        else:
            stop_hit = float(row["high"]) >= sl
            target_hit = float(row["low"]) <= tp
        # Conservative same-M1 precedence because intrabar order is unavailable.
        if stop_hit:
            return "SL"
        if target_hit:
            return "TP"
    return "UNRESOLVED"


def _candidate_key(
    *,
    delta_fraction: float,
    entry_tier: str,
    target_multiple: int,
) -> str:
    return f"D{delta_fraction:.2f}|{entry_tier}|TP{target_multiple}"


def _empty_stats() -> dict[str, Any]:
    return {
        "episodes": 0,
        "anchors": 0,
        "fills": 0,
        "wins": 0,
        "losses": 0,
        "unresolved": 0,
        "gross_win_r": 0.0,
        "gross_loss_r": 0.0,
        "planned_rr_sum": 0.0,
        "planned_rr_n": 0,
        "entry_error_atr_sum": 0.0,
        "entry_error_atr_n": 0,
    }


def _finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    out = dict(stats)
    episodes = int(out["episodes"])
    anchors = int(out["anchors"])
    fills = int(out["fills"])
    wins = int(out["wins"])
    losses = int(out["losses"])
    resolved = wins + losses
    gross_win = float(out["gross_win_r"])
    gross_loss = float(out["gross_loss_r"])
    out.update(
        {
            "anchor_rate": None if episodes == 0 else anchors / episodes,
            "fill_rate_of_anchors": None if anchors == 0 else fills / anchors,
            "fill_rate_of_episodes": None if episodes == 0 else fills / episodes,
            "resolved": resolved,
            "win_rate_resolved": None if resolved == 0 else wins / resolved,
            "win_wilson_lower_95": (
                None if resolved == 0 else wilson_lower_bound(wins, resolved)
            ),
            "profit_factor_gross_r": (
                None if gross_loss <= 0 else gross_win / gross_loss
            ),
            "expectancy_r_all_fills": (
                None if fills == 0 else (gross_win - gross_loss) / fills
            ),
            "expectancy_r_resolved": (
                None if resolved == 0 else (gross_win - gross_loss) / resolved
            ),
            "average_planned_rr": (
                None
                if int(out["planned_rr_n"]) == 0
                else float(out["planned_rr_sum"]) / int(out["planned_rr_n"])
            ),
            "mean_entry_error_atr": (
                None
                if int(out["entry_error_atr_n"]) == 0
                else float(out["entry_error_atr_sum"]) / int(out["entry_error_atr_n"])
            ),
        }
    )
    return out


def evaluate_year(
    price_m1: pd.DataFrame,
    episodes: Sequence[DepthEpisode],
) -> dict[str, Any]:
    price = price_m1.loc[:, ["timestamp", "open", "high", "low", "close"]].copy()
    price["timestamp"] = pd.to_datetime(price["timestamp"], utc=True)
    price = price.sort_values("timestamp").reset_index(drop=True)
    m5 = _resample_m5(price)

    selected_episodes = [
        row for row in episodes
        if str(row.timeframe).upper() in SOURCE_TIMEFRAMES
    ]
    keys = [
        _candidate_key(
            delta_fraction=frac,
            entry_tier=tier,
            target_multiple=target,
        )
        for frac in DELTA_FRACTIONS
        for tier in ENTRY_TIERS
        for target in TARGET_MULTIPLES
    ]
    stats = {key: _empty_stats() for key in keys}
    anchor_examples: list[dict[str, Any]] = []

    for episode in selected_episodes:
        direction = str(episode.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        parent_atr = max(float(episode.atr_points), 1e-9)
        anchor = _anchor_for_episode(m5, episode)
        touch_at = pd.Timestamp(ensure_utc(episode.touch_at))
        horizon_at = touch_at + pd.Timedelta(
            minutes=HORIZON_MINUTES[str(episode.timeframe).upper()]
        )

        for row in stats.values():
            row["episodes"] += 1
        if anchor is None:
            continue
        for row in stats.values():
            row["anchors"] += 1

        if len(anchor_examples) < 12:
            anchor_examples.append(
                {
                    "zone_id": episode.zone_id,
                    "timeframe": episode.timeframe,
                    "direction": direction,
                    "touch_at": touch_at.isoformat(),
                    "a": float(anchor["a"]),
                    "confirmed_at": pd.Timestamp(anchor["confirmed_at"]).isoformat(),
                    "turning_price": episode.turning_price,
                    "reaction_hit": bool(episode.reaction_hit),
                    "m5_atr14": float(anchor["atr14_m5"]),
                    "parent_atr": parent_atr,
                }
            )

        after_confirm = price[
            (price["timestamp"] >= pd.Timestamp(anchor["confirmed_at"]))
            & (price["timestamp"] <= horizon_at)
        ].reset_index(drop=True)
        if after_confirm.empty:
            continue

        sign = 1.0 if direction == "LONG" else -1.0
        distal = float(episode.distal)
        micro_atr = max(float(anchor["atr14_m5"]), 1e-9)
        sl = (
            distal - STRUCTURAL_SL_BUFFER_ATR * micro_atr
            if direction == "LONG"
            else distal + STRUCTURAL_SL_BUFFER_ATR * micro_atr
        )

        for frac in DELTA_FRACTIONS:
            delta = float(frac) * micro_atr
            a = float(anchor["a"])
            entry_levels = {
                "A_RETEST": a,
                "X": a + sign * delta,
                "Y": a + sign * 2.0 * delta,
            }
            targets = {
                multiple: a + sign * float(multiple) * delta
                for multiple in TARGET_MULTIPLES
            }

            for tier, entry in entry_levels.items():
                risk = abs(entry - sl)
                if risk <= 1e-9:
                    continue
                fill_idx = _first_fill_index(
                    after_confirm,
                    direction=direction,
                    entry=entry,
                    distal=distal,
                )
                for multiple, tp in targets.items():
                    key = _candidate_key(
                        delta_fraction=frac,
                        entry_tier=tier,
                        target_multiple=multiple,
                    )
                    row = stats[key]
                    if fill_idx is None:
                        continue
                    reward = (
                        tp - entry
                        if direction == "LONG"
                        else entry - tp
                    )
                    if reward <= 0:
                        continue
                    rr = reward / risk
                    row["fills"] += 1
                    row["planned_rr_sum"] += rr
                    row["planned_rr_n"] += 1
                    if episode.turning_price is not None:
                        row["entry_error_atr_sum"] += (
                            abs(entry - float(episode.turning_price)) / micro_atr
                        )
                        row["entry_error_atr_n"] += 1
                    outcome = _resolve_trade(
                        after_confirm,
                        fill_index=fill_idx,
                        direction=direction,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                    )
                    if outcome == "TP":
                        row["wins"] += 1
                        row["gross_win_r"] += rr
                    elif outcome == "SL":
                        row["losses"] += 1
                        row["gross_loss_r"] += 1.0
                    else:
                        row["unresolved"] += 1

    candidates = []
    for frac in DELTA_FRACTIONS:
        for tier in ENTRY_TIERS:
            for target in TARGET_MULTIPLES:
                key = _candidate_key(
                    delta_fraction=frac,
                    entry_tier=tier,
                    target_multiple=target,
                )
                candidates.append(
                    {
                        "candidate_key": key,
                        "delta_fraction": frac,
                        "entry_tier": tier,
                        "target_multiple": target,
                        **_finalize_stats(stats[key]),
                    }
                )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "source_timeframes": list(SOURCE_TIMEFRAMES),
        "delta_fractions": list(DELTA_FRACTIONS),
        "delta_basis": "CAUSAL_M5_ATR14_AT_ANCHOR_CONFIRMATION",
        "entry_tiers": list(ENTRY_TIERS),
        "target_multiples": list(TARGET_MULTIPLES),
        "anchor_contract": {
            "reclaim": "TWO_CONSECUTIVE_M5_CLOSES_BEYOND_PARENT_PROXIMAL",
            "touch_atr": "LAST_M5_ATR14_KNOWN_AT_OR_BEFORE_PARENT_TOUCH",
            "impulse": f"{IMPULSE_ATR_MULTIPLE:.2f}_CAUSAL_M5_ATR14_FROM_PROXIMAL",
            "a": "FIRST_CAUSALLY_CONFIRMED_POST_IMPULSE_M5_PULLBACK_PIVOT",
            "a_known_at": "CLOSE_OF_M5_BAR_AFTER_PIVOT",
            "no_future_turning_price_used_for_signal": True,
        },
        "trade_contract": {
            "entry_fill": "M1_TOUCH_AFTER_A_KNOWN",
            "sl": f"PARENT_DISTAL_PLUS_{STRUCTURAL_SL_BUFFER_ATR:.2f}_M5_ATR14_BUFFER",
            "same_m1_stop_target_precedence": "STOP_FIRST",
            "friction": "NOT_INCLUDED_GROSS_RESEARCH",
            "horizon_minutes": dict(HORIZON_MINUTES),
        },
        "episodes": len(selected_episodes),
        "anchor_examples": anchor_examples,
        "candidates": candidates,
    }


def combine_candidate_stats(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    total = _empty_stats()
    for raw in rows:
        row = dict(raw or {})
        for key in (
            "episodes",
            "anchors",
            "fills",
            "wins",
            "losses",
            "unresolved",
            "planned_rr_n",
            "entry_error_atr_n",
        ):
            total[key] += int(row.get(key) or 0)
        for key in (
            "gross_win_r",
            "gross_loss_r",
            "planned_rr_sum",
            "entry_error_atr_sum",
        ):
            total[key] += float(row.get(key) or 0.0)
    return _finalize_stats(total)
