from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import _cash, build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION = "XAU_QUALITATIVE_REACCEL_GATE_V126"
ARTIFACT_CONTRACT = "XAU_QUALITATIVE_REACCEL_GATE_V126_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

ROUTE_ID = "COMPRESSED_REACCEL"
MEDIAN = 0.50
EVALUATION_START = datetime(2012, 1, 1, tzinfo=timezone.utc)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def passes_qualitative_gate(record: Mapping[str, Any]) -> bool:
    side = str(record.get("side") or "").upper()
    if side not in {"LONG", "SHORT"}:
        return False

    required = (
        "pct_atr14_pct",
        "pct_atr_ratio_252",
        "d20_pct_atr14_pct",
        "d20_pct_atr_ratio_252",
        "pct_ema200_distance_atr",
        "d5_pct_trend60_atr",
    )
    if any(record.get(k) is None for k in required):
        return False

    # Pre-registered qualitative semantics only:
    # 1) volatility is below its causal rolling median;
    # 2) volatility ranks have compressed over the prior 20 completed D1 rows;
    # 3) price is on the trend-consistent side of the EMA200 rank median;
    # 4) 60D trend rank has re-accelerated over the prior 5 completed D1 rows.
    if float(record["pct_atr14_pct"]) > MEDIAN:
        return False
    if float(record["pct_atr_ratio_252"]) > MEDIAN:
        return False
    if float(record["d20_pct_atr14_pct"]) >= 0.0:
        return False
    if float(record["d20_pct_atr_ratio_252"]) >= 0.0:
        return False

    ema_rank = float(record["pct_ema200_distance_atr"])
    trend_delta = float(record["d5_pct_trend60_atr"])
    if side == "LONG":
        return ema_rank >= MEDIAN and trend_delta > 0.0
    return ema_rank <= MEDIAN and trend_delta < 0.0


def _epoch_window(record: Mapping[str, Any], evaluation_end):
    start = ensure_utc(pd.Timestamp(record["start"]).to_pydatetime())
    if record.get("end_exclusive") is None:
        end = ensure_utc(evaluation_end)
    else:
        end = ensure_utc(pd.Timestamp(record["end_exclusive"]).to_pydatetime())
    return start, end


def route_v110_by_eligible_epochs(
    trades: Sequence[TournamentTrade],
    epoch_records: Sequence[Mapping[str, Any]],
    *,
    evaluation_end,
) -> tuple[TournamentTrade, ...]:
    windows = []
    for record in epoch_records:
        if not passes_qualitative_gate(record):
            continue
        start, end = _epoch_window(record, evaluation_end)
        windows.append((start, end, str(record["side"]).upper()))

    kept = []
    for trade in sorted(trades, key=lambda x: ensure_utc(x.entry_at)):
        at = ensure_utc(trade.entry_at)
        side = str(trade.direction).upper()
        if any(a <= at < b and side == s for a, b, s in windows):
            kept.append(trade)
    return tuple(kept)


def evaluate_v126(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    feature_frame = build_v122_feature_frame(bars)
    _, epochs = build_reaccel_route_frame(feature_frame, route_id=ROUTE_ID)
    _, selector_all, _ = assemble_v110_selector(
        bars,
        costs=costs,
        pip_size=pip_size,
        evaluation_end=end,
    )
    selector = tuple(t for t in selector_all if ensure_utc(t.entry_at) < end)

    epoch_records = annotate_compressed_epochs(feature_frame, epochs, selector)
    eligible_epochs = tuple(r for r in epoch_records if passes_qualitative_gate(r))
    routed = route_v110_by_eligible_epochs(selector, epoch_records, evaluation_end=end)

    windows = (
        ("2012_2018", datetime(2012, 1, 1, tzinfo=timezone.utc), datetime(2019, 1, 1, tzinfo=timezone.utc)),
        ("2019_2024", datetime(2019, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("2025_2026YTD", datetime(2025, 1, 1, tzinfo=timezone.utc), end),
    )

    eras = {}
    for label, a, b in windows:
        vals = _period(routed, a, b)
        eps = tuple(
            r for r in eligible_epochs
            if a <= ensure_utc(pd.Timestamp(r["start"]).to_pydatetime()) < b
        )
        eras[label] = {
            "metrics": _metrics(vals),
            "fresh_100_cash": _cash(
                routed,
                bars=bars,
                start=a,
                end=b,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            ),
            "eligible_epoch_count": len(eps),
        }

    pre2025 = [
        r for r in epoch_records
        if ensure_utc(pd.Timestamp(r["start"]).to_pydatetime()) < datetime(2025, 1, 1, tzinfo=timezone.utc)
        and r["outcome_sign"] != "NO_TRADES"
    ]
    pre2025_pos = [r for r in pre2025 if r["outcome_sign"] == "POSITIVE_NET_R"]
    pre2025_bad = [r for r in pre2025 if r["outcome_sign"] == "NONPOSITIVE_NET_R"]
    mid_bad = [r for r in pre2025_bad if r["era"] == "2019_2024"]

    jan2025 = next((r for r in epoch_records if str(r["start"]).startswith("2025-01-16")), None)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "base_strategy": "exact frozen V110 selector",
            "base_route": ROUTE_ID,
            "gate_id": "MEDIAN_COMPRESSION_REACCEL",
            "median_threshold_source": "fixed percentile median = 0.50; not optimized",
            "sign_threshold_source": "zero-change sign only; not optimized",
            "rules": [
                "pct_atr14_pct <= 0.50",
                "pct_atr_ratio_252 <= 0.50",
                "d20_pct_atr14_pct < 0",
                "d20_pct_atr_ratio_252 < 0",
                "LONG: pct_ema200_distance_atr >= 0.50 and d5_pct_trend60_atr > 0",
                "SHORT: pct_ema200_distance_atr <= 0.50 and d5_pct_trend60_atr < 0",
            ],
            "calendar_year_used_for_routing": False,
            "nominal_price_used": False,
            "risk_price_used": False,
            "parameter_grid_search": False,
            "future_outcome_used_for_gate": False,
            "execution_authority": False,
        },
        "full_metrics": _metrics(_period(routed, EVALUATION_START, end)),
        "continuous_100_cash_2012_to_end": _cash(
            routed,
            bars=bars,
            start=EVALUATION_START,
            end=end,
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        ),
        "eras": eras,
        "epoch_counts": {
            "all": len(epoch_records),
            "eligible": len(eligible_epochs),
            "pre2025_positive_all": len(pre2025_pos),
            "pre2025_positive_retained": sum(passes_qualitative_gate(r) for r in pre2025_pos),
            "pre2025_nonpositive_all": len(pre2025_bad),
            "pre2025_nonpositive_retained": sum(passes_qualitative_gate(r) for r in pre2025_bad),
            "mid_2019_2024_nonpositive_all": len(mid_bad),
            "mid_2019_2024_nonpositive_retained": sum(passes_qualitative_gate(r) for r in mid_bad),
        },
        "jan2025": {
            "found": jan2025 is not None,
            "retained": False if jan2025 is None else passes_qualitative_gate(jan2025),
            "record": jan2025,
        },
        "eligible_epochs": list(eligible_epochs),
        "note": (
            "V126 is a preregistered historical hypothesis test derived after V125 forensic work. "
            "It remains SHADOW_ONLY and is not promotion evidence. Its job is to test whether simple "
            "median/sign semantics reduce false onsets while preserving the Jan-2025 epoch."
        ),
    }
