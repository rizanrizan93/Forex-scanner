from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_v134_h3_robustness_v135 import RECENT, START, frozen_h3
from .research_xau_v136_structural_regime_forensic_v137 import annotate_structural

RESEARCH_VERSION = "XAU_V137_CFTC_POSITIONING_FORENSIC_V138"
ARTIFACT_CONTRACT = "XAU_V137_CFTC_POSITIONING_FORENSIC_V138_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

GOLD_CFTC_CONTRACT_MARKET_CODE = "088691"
CFTC_PUBLICATION_LAG_DAYS = 7
POSITION_LOOKBACK_REPORTS = 4


@dataclass(frozen=True)
class CotRow:
    report_date: date
    available_at: datetime
    open_interest: float
    managed_money_long: float
    managed_money_short: float
    producer_long: float
    producer_short: float
    swap_long: float
    swap_short: float
    mm_net: float
    mm_net_pct_oi: float
    mm_net_delta4: float | None
    mm_net_pct_oi_delta4: float | None
    oi_change4_pct: float | None


class CotAsof:
    def __init__(self, rows: Sequence[CotRow]):
        ordered = sorted(rows, key=lambda x: x.available_at)
        self.rows = tuple(ordered)
        self.times = tuple(x.available_at for x in ordered)

    def row(self, signal_at: datetime) -> CotRow | None:
        t = ensure_utc(signal_at)
        i = bisect_right(self.times, t) - 1
        return None if i < 0 else self.rows[i]


def build_cot_rows(raw_rows: Sequence[Mapping[str, Any]]) -> tuple[CotRow, ...]:
    base = []
    for raw in raw_rows:
        report_date = raw["report_date"]
        if isinstance(report_date, datetime):
            report_date = report_date.date()
        oi = float(raw["open_interest"])
        mm_long = float(raw["managed_money_long"])
        mm_short = float(raw["managed_money_short"])
        prod_long = float(raw["producer_long"])
        prod_short = float(raw["producer_short"])
        swap_long = float(raw["swap_long"])
        swap_short = float(raw["swap_short"])
        if not np.isfinite(oi) or oi <= 0:
            continue
        mm_net = mm_long - mm_short
        base.append(
            {
                "report_date": report_date,
                "open_interest": oi,
                "managed_money_long": mm_long,
                "managed_money_short": mm_short,
                "producer_long": prod_long,
                "producer_short": prod_short,
                "swap_long": swap_long,
                "swap_short": swap_short,
                "mm_net": mm_net,
                "mm_net_pct_oi": mm_net / oi,
            }
        )

    base.sort(key=lambda x: x["report_date"])
    out = []
    for i, row in enumerate(base):
        prior = base[i - POSITION_LOOKBACK_REPORTS] if i >= POSITION_LOOKBACK_REPORTS else None
        mm_delta = None if prior is None else row["mm_net"] - prior["mm_net"]
        pct_delta = None if prior is None else row["mm_net_pct_oi"] - prior["mm_net_pct_oi"]
        oi_change = (
            None
            if prior is None or prior["open_interest"] == 0
            else row["open_interest"] / prior["open_interest"] - 1.0
        )
        available = datetime.combine(
            row["report_date"] + timedelta(days=CFTC_PUBLICATION_LAG_DAYS),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        out.append(
            CotRow(
                report_date=row["report_date"],
                available_at=available,
                open_interest=row["open_interest"],
                managed_money_long=row["managed_money_long"],
                managed_money_short=row["managed_money_short"],
                producer_long=row["producer_long"],
                producer_short=row["producer_short"],
                swap_long=row["swap_long"],
                swap_short=row["swap_short"],
                mm_net=row["mm_net"],
                mm_net_pct_oi=row["mm_net_pct_oi"],
                mm_net_delta4=mm_delta,
                mm_net_pct_oi_delta4=pct_delta,
                oi_change4_pct=oi_change,
            )
        )
    return tuple(out)


def _position_state(cot: CotRow | None) -> str:
    if cot is None or cot.mm_net_delta4 is None:
        return "UNKNOWN"
    if cot.mm_net > 0 and cot.mm_net_delta4 > 0:
        return "MM_NET_LONG_EXPANDING"
    if cot.mm_net > 0:
        return "MM_NET_LONG_CONTRACTING"
    return "MM_NONLONG"


def _oi_state(cot: CotRow | None) -> str:
    if cot is None or cot.oi_change4_pct is None:
        return "UNKNOWN"
    return "OI_EXPANDING" if cot.oi_change4_pct > 0 else "OI_CONTRACTING"


def _crowding_direction(cot: CotRow | None) -> str:
    if cot is None:
        return "UNKNOWN"
    return "MM_NET_LONG" if cot.mm_net > 0 else "MM_NET_NONLONG"


def annotate_cot(
    structural_rows: Sequence[Mapping[str, Any]],
    cot_rows: Sequence[CotRow],
) -> tuple[dict[str, Any], ...]:
    lookup = CotAsof(cot_rows)
    out = []
    for row in structural_rows:
        trade = row["trade"]
        cot = lookup.row(trade.signal_at)
        payload = dict(row)
        payload.update(
            {
                "cot_state": _position_state(cot),
                "cot_oi_state": _oi_state(cot),
                "cot_crowding_direction": _crowding_direction(cot),
                "cot_report_date": None if cot is None else cot.report_date.isoformat(),
                "cot_available_at": None if cot is None else cot.available_at.isoformat(),
                "cot_mm_net": None if cot is None else cot.mm_net,
                "cot_mm_net_pct_oi": None if cot is None else cot.mm_net_pct_oi,
                "cot_mm_net_delta4": None if cot is None else cot.mm_net_delta4,
                "cot_mm_net_pct_oi_delta4": None if cot is None else cot.mm_net_pct_oi_delta4,
                "cot_oi_change4_pct": None if cot is None else cot.oi_change4_pct,
            }
        )
        out.append(payload)
    return tuple(out)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _group(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    buckets: dict[str, list[TournamentTrade]] = defaultdict(list)
    for row in rows:
        name = "|".join(str(row[k]) for k in keys)
        buckets[name].append(row["trade"])
    return {k: _metrics(v) for k, v in sorted(buckets.items())}


def _feature_summary(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    values = [
        float(r[key])
        for r in rows
        if r.get(key) is not None and np.isfinite(float(r[key]))
    ]
    wins = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
        and np.isfinite(float(r[key]))
        and float(r["trade"].net_r) > 0
    ]
    losses = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
        and np.isfinite(float(r[key]))
        and float(r["trade"].net_r) <= 0
    ]

    def pack(vals):
        if not vals:
            return {"n": 0, "median": None, "mean": None, "q25": None, "q75": None}
        a = np.asarray(vals, dtype=float)
        return {
            "n": int(a.size),
            "median": float(np.median(a)),
            "mean": float(np.mean(a)),
            "q25": float(np.quantile(a, 0.25)),
            "q75": float(np.quantile(a, 0.75)),
        }

    return {"all": pack(values), "wins": pack(wins), "losses": pack(losses)}


def _slice(
    rows: Sequence[Mapping[str, Any]], *, start: datetime, end: datetime
) -> dict[str, Any]:
    scoped = tuple(
        r for r in rows
        if ensure_utc(start) <= ensure_utc(r["trade"].entry_at) < ensure_utc(end)
    )
    covered = tuple(r for r in scoped if r["cot_state"] != "UNKNOWN")
    extended_strong = tuple(
        r for r in scoped
        if r["d1_regime"] == "STRONG_BULL" and r["d1_maturity"] == "EXTENDED"
    )
    return {
        "count": len(scoped),
        "metrics": _metrics(tuple(r["trade"] for r in scoped)),
        "cot_covered": len(covered),
        "cot_coverage": len(covered) / len(scoped) if scoped else None,
        "by_cot_state": _group(scoped, ("cot_state",)),
        "by_oi_state": _group(scoped, ("cot_oi_state",)),
        "cot_state_x_oi": _group(scoped, ("cot_state", "cot_oi_state")),
        "d1_regime_x_cot": _group(scoped, ("d1_regime", "cot_state")),
        "d1_maturity_x_cot": _group(scoped, ("d1_maturity", "cot_state")),
        "extended_strong_bull": {
            "count": len(extended_strong),
            "metrics": _metrics(tuple(r["trade"] for r in extended_strong)),
            "by_cot_state": _group(extended_strong, ("cot_state",)),
            "cot_state_x_oi": _group(
                extended_strong, ("cot_state", "cot_oi_state")
            ),
        },
        "feature_summary": {
            k: _feature_summary(scoped, k)
            for k in (
                "cot_mm_net",
                "cot_mm_net_pct_oi",
                "cot_mm_net_delta4",
                "cot_mm_net_pct_oi_delta4",
                "cot_oi_change4_pct",
            )
        },
    }


def evaluate_v138(
    bars: Sequence[Bar],
    *,
    macro_series,
    cot_raw_rows: Sequence[Mapping[str, Any]],
    evaluation_end: datetime,
    pip_size: float,
    costs,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=costs)
    structural = annotate_structural(rows, trades, macro_series=macro_series)
    cot = build_cot_rows(cot_raw_rows)
    annotated = annotate_cot(structural, cot)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "live_execution_enabled": False,
        "contract": {
            "candidate": "V134_H3_C2_H1_STRICT_FROZEN",
            "cftc_contract_market_code": GOLD_CFTC_CONTRACT_MARKET_CODE,
            "cftc_report": "DISAGGREGATED_FUTURES_ONLY",
            "publication_lag_days": CFTC_PUBLICATION_LAG_DAYS,
            "publication_rule": (
                "a Tuesday report is considered usable only from report_date + 7 calendar days; "
                "this is deliberately more conservative than the normal Friday release"
            ),
            "position_lookback_reports": POSITION_LOOKBACK_REPORTS,
            "position_state_rule": {
                "MM_NET_LONG_EXPANDING": "MM net > 0 and 4-report net delta > 0",
                "MM_NET_LONG_CONTRACTING": "MM net > 0 and 4-report net delta <= 0",
                "MM_NONLONG": "MM net <= 0",
            },
            "oi_state_rule": "4-report OI change sign only",
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "trade_rule_changes": False,
            "selection_authority": False,
        },
        "cot_rows": len(cot),
        "cot_first_report": None if not cot else cot[0].report_date.isoformat(),
        "cot_last_report": None if not cot else cot[-1].report_date.isoformat(),
        "full": _slice(annotated, start=START, end=end),
        "pre2025": _slice(annotated, start=START, end=RECENT),
        "recent": _slice(annotated, start=RECENT, end=end),
        "note": (
            "V138 is forensic only. It asks whether point-in-time CFTC Managed Money "
            "and open-interest dynamics explain why old STRONG_BULL/EXTENDED H3 was weak "
            "while the recent STRONG_BULL/EXTENDED H3 regime is strong. No gate is selected."
        ),
    }
