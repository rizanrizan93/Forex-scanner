from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_champion_decomposition_v121 import START, _trace_cash
from .research_xau_changepoint_reset_router_v87 import build_regime_feature_frame, detect_change_points
from .research_xau_causal_era_selector_v98 import (
    RANK_LOOKBACK_DAYS,
    RANK_MIN_HISTORY_DAYS,
    _pct_rank,
    _strategy_streams,
)
from .research_xau_era_fingerprint_v97 import FEATURES
from .research_xau_expansion_species_v99 import build_species_frame
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION = "XAU_2025_BOOTSTRAP_ONSET_FORENSIC_V122"
ARTIFACT_CONTRACT = "XAU_2025_BOOTSTRAP_ONSET_FORENSIC_V122_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

BOOTSTRAP_END = datetime(2025, 4, 17, tzinfo=timezone.utc)
PRIOR_OLD_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
PRIOR_MID_START = datetime(2019, 1, 1, tzinfo=timezone.utc)
PRIOR_MID_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
D1_IDS = {"V31_D1_TSMOM_CLASSIC", "V20_D1_TSMOM_C1_R200"}


class _Asof:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.reset_index(drop=True)
        self.times = [ensure_utc(x) for x in self.frame["available_at"]]

    def row(self, timestamp) -> Mapping[str, Any] | None:
        i = bisect_right(self.times, ensure_utc(timestamp)) - 1
        if i < 0:
            return None
        return self.frame.iloc[i].to_dict()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def build_v122_feature_frame(rows: Sequence[Bar]) -> pd.DataFrame:
    # build_species_frame inherits the complete V97 fingerprint and adds
    # causal V98 state + V99 species. All rows are available only after
    # the source D1 bar is completed.
    x = build_species_frame(rows).copy().sort_values("available_at").reset_index(drop=True)
    for feature in FEATURES:
        ranks: list[float] = []
        for i in range(len(x)):
            value = float(x.loc[i, feature]) if pd.notna(x.loc[i, feature]) else float("nan")
            hist = (
                x.loc[max(0, i - RANK_LOOKBACK_DAYS): i - 1, feature].to_numpy(dtype=float)
                if i > 0
                else np.array([])
            )
            r = _pct_rank(value, hist)
            ranks.append(float("nan") if r is None else float(r))
        x[f"pct_{feature}"] = ranks
    return x


def _latest_cp(signal_at, change_points: Sequence[Mapping[str, Any]]) -> tuple[str | None, float | None]:
    signal = ensure_utc(signal_at)
    prior = []
    for cp in change_points:
        t = ensure_utc(pd.Timestamp(cp["effective_at"]).to_pydatetime())
        if t <= signal:
            prior.append(t)
    if not prior:
        return None, None
    last = max(prior)
    return last.isoformat(), float((signal - last).total_seconds() / 86400.0)


def _annotate_trade(
    trade: TournamentTrade,
    *,
    lookup: _Asof,
    change_points: Sequence[Mapping[str, Any]],
    broker_spec,
    entry_cash: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # D1 trade.signal_at is the left-labelled start of the signal day, while
    # the signal uses that day's completed close and enters at the next D1 open.
    # The correct causal decision snapshot is therefore entry_at: at that instant
    # the signal-day D1/H1 features are completed and available, but no entry-day
    # future information exists.
    decision_at = ensure_utc(trade.entry_at)
    row = lookup.row(decision_at)
    cp_at, cp_days = _latest_cp(decision_at, change_points)
    units_001 = float(broker_spec.contract_units_per_lot) * 0.01
    risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
    risk_usd_001 = risk_price * units_001

    out: dict[str, Any] = {
        "strategy_id": trade.strategy_id,
        "direction": str(trade.direction),
        "signal_at": ensure_utc(trade.signal_at).isoformat(),
        "decision_at": decision_at.isoformat(),
        "entry_at": ensure_utc(trade.entry_at).isoformat(),
        "exit_at": ensure_utc(trade.exit_at).isoformat(),
        "entry_price": float(trade.entry_price),
        "stop_loss": float(trade.stop_loss),
        "target": float(trade.take_profit),
        "risk_price": float(risk_price),
        "risk_usd_001": float(risk_usd_001),
        "net_r": float(trade.net_r),
        "cost_r": float(trade.cost_r),
        "exit_reason": str(trade.exit_reason),
        "latest_change_point_at": cp_at,
        "days_since_change_point": cp_days,
    }
    if row is not None:
        if row.get("available_at") is not None:
            out["fingerprint_available_at"] = ensure_utc(row["available_at"]).isoformat()
        out["state"] = str(row.get("state") or "UNCLASSIFIED")
        out["species"] = str(row.get("species") or "UNCLASSIFIED")
        out["era_score"] = None if pd.isna(row.get("era_score")) else float(row.get("era_score"))
        out["quality_score"] = None if pd.isna(row.get("quality_score")) else float(row.get("quality_score"))
        for feature in FEATURES:
            v = row.get(feature)
            p = row.get(f"pct_{feature}")
            out[feature] = None if pd.isna(v) else float(v)
            out[f"pct_{feature}"] = None if pd.isna(p) else float(p)
    if entry_cash is not None:
        for key in (
            "balance",
            "planned_loss_usd",
            "margin_usd",
            "planned_margin_level_pct",
        ):
            if key in entry_cash:
                out[key] = float(entry_cash[key])
        if "balance" in entry_cash and float(entry_cash["balance"]) > 0:
            out["planned_loss_pct_of_balance"] = (
                100.0 * float(entry_cash.get("planned_loss_usd", 0.0)) / float(entry_cash["balance"])
            )
    return out


def _profile(records: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        vals = []
        for r in records:
            v = r.get(key)
            if v is not None:
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if isfinite(f):
                    vals.append(f)
        if not vals:
            out[key] = {"n": 0, "p25": None, "median": None, "p75": None, "mean": None}
            continue
        a = np.asarray(vals, dtype=float)
        out[key] = {
            "n": int(len(a)),
            "p25": float(np.quantile(a, 0.25)),
            "median": float(np.median(a)),
            "p75": float(np.quantile(a, 0.75)),
            "mean": float(np.mean(a)),
        }
    return out


def _robust_effect(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], key: str) -> float | None:
    xa = np.asarray([float(r[key]) for r in a if r.get(key) is not None and isfinite(float(r[key]))], dtype=float)
    xb = np.asarray([float(r[key]) for r in b if r.get(key) is not None and isfinite(float(r[key]))], dtype=float)
    if len(xa) == 0 or len(xb) == 0:
        return None
    pooled = np.concatenate([xa, xb])
    med = float(np.median(pooled))
    mad = float(np.median(np.abs(pooled - med)))
    if not isfinite(mad) or mad <= 1e-12:
        return None
    return float((np.median(xa) - np.median(xb)) / (1.4826 * mad))


def _milestones(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exits = [x for x in ledger if x.get("event") == "EXIT"]
    out = {}
    for level in (200.0, 500.0, 1000.0):
        hit = next((x for x in exits if float(x.get("balance_after", 0.0)) >= level), None)
        out[str(int(level))] = hit
    return out


def evaluate_v122(
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

    frame = build_v122_feature_frame(bars)
    lookup = _Asof(frame)
    change_points = detect_change_points(build_regime_feature_frame(bars))

    core_all, selector_all, selected = assemble_v110_selector(
        bars, costs=costs, pip_size=pip_size, evaluation_end=end
    )
    streams = _strategy_streams(bars, costs=costs, pip_size=pip_size)

    full_2025 = _period(selector_all, START, end)
    trace = _trace_cash(
        full_2025,
        spec=broker_spec,
        tiers=leverage_tiers,
        evaluation_start=START,
        evaluation_end=end,
    )
    ledger = trace["ledger_to_first_1000"]
    entry_cash = {
        (str(x["strategy_id"]), str(x["at"])): x
        for x in ledger
        if x.get("event") == "ENTRY"
    }

    trade_index = {
        (t.strategy_id, ensure_utc(t.entry_at).isoformat()): t
        for t in selector_all
    }
    bootstrap_realized = []
    for x in ledger:
        if x.get("event") != "EXIT":
            continue
        key = (str(x["strategy_id"]), str(x["entry_at"]))
        trade = trade_index.get(key)
        if trade is None or trade.strategy_id not in D1_IDS:
            continue
        cash = entry_cash.get((trade.strategy_id, ensure_utc(trade.entry_at).isoformat()))
        rec = _annotate_trade(
            trade,
            lookup=lookup,
            change_points=change_points,
            broker_spec=broker_spec,
            entry_cash=cash,
        )
        rec["cash_pnl_usd"] = float(x["pnl_usd"])
        rec["balance_before_exit"] = float(x["balance_before"])
        rec["balance_after_exit"] = float(x["balance_after"])
        bootstrap_realized.append(rec)

    bootstrap_winners = [x for x in bootstrap_realized if float(x["net_r"]) > 0.0]
    bootstrap_losers = [x for x in bootstrap_realized if float(x["net_r"]) <= 0.0]

    selected_d1 = tuple(
        t for t in (*tuple(core_all), *tuple(selected["D1_STAGGERED"]))
        if t.strategy_id in D1_IDS
    )
    # Deduplicate by exact strategy+entry; classic and staggered are intentionally
    # retained as different families when their timestamps differ.
    seen = set()
    selected_d1_unique = []
    for t in sorted(selected_d1, key=lambda z: (ensure_utc(z.entry_at), z.strategy_id)):
        k = (t.strategy_id, ensure_utc(t.entry_at).isoformat())
        if k not in seen:
            seen.add(k)
            selected_d1_unique.append(t)

    prior_old = [
        _annotate_trade(t, lookup=lookup, change_points=change_points, broker_spec=broker_spec)
        for t in selected_d1_unique
        if PRIOR_OLD_START <= ensure_utc(t.entry_at) < PRIOR_MID_START
    ]
    prior_mid = [
        _annotate_trade(t, lookup=lookup, change_points=change_points, broker_spec=broker_spec)
        for t in selected_d1_unique
        if PRIOR_MID_START <= ensure_utc(t.entry_at) < PRIOR_MID_END
    ]

    early_d1 = [
        t for t in selected_d1_unique
        if START <= ensure_utc(t.entry_at) < BOOTSTRAP_END
    ]
    accepted_keys = {
        (str(x["strategy_id"]), str(x["at"]))
        for x in ledger
        if x.get("event") == "ENTRY" and str(x.get("strategy_id")) in D1_IDS
    }
    early_annotated = []
    for t in early_d1:
        key = (t.strategy_id, ensure_utc(t.entry_at).isoformat())
        rec = _annotate_trade(
            t,
            lookup=lookup,
            change_points=change_points,
            broker_spec=broker_spec,
            entry_cash=entry_cash.get(key),
        )
        rec["cash_accepted_before_first_1000"] = key in accepted_keys
        early_annotated.append(rec)

    profile_keys = tuple(FEATURES) + tuple(f"pct_{f}" for f in FEATURES) + (
        "era_score",
        "quality_score",
        "days_since_change_point",
        "risk_price",
        "risk_usd_001",
    )
    effects = {}
    for key in profile_keys:
        effects[key] = {
            "bootstrap_winners_vs_2012_2018": _robust_effect(bootstrap_winners, prior_old, key),
            "bootstrap_winners_vs_2019_2024": _robust_effect(bootstrap_winners, prior_mid, key),
        }
    ranked = sorted(
        effects,
        key=lambda k: (
            abs(effects[k]["bootstrap_winners_vs_2012_2018"] or 0.0)
            + abs(effects[k]["bootstrap_winners_vs_2019_2024"] or 0.0)
        ),
        reverse=True,
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "purpose": "causal forensic decomposition only; no routing threshold selected",
            "feature_availability": "completed signal-day D1/H1 only; as-of lookup at next D1 entry open",
            "historical_outcome_used_only_as_label": True,
            "calendar_year_used_for_execution": False,
            "threshold_grid_search": False,
            "v110_strategy_rules_changed": False,
            "cash_contract": "fresh $100 / 1:100 / fixed 0.01 / no risk-% cap / 50% stop-out survivability",
        },
        "first_1000_exit": trace["first_1000_exit"],
        "milestones": _milestones(ledger),
        "bootstrap_realized_d1": bootstrap_realized,
        "bootstrap_winners_d1": bootstrap_winners,
        "bootstrap_losers_d1": bootstrap_losers,
        "early_2025_selected_d1": early_annotated,
        "profiles": {
            "bootstrap_winners": _profile(bootstrap_winners, profile_keys),
            "bootstrap_losers": _profile(bootstrap_losers, profile_keys),
            "selected_d1_2012_2018": _profile(prior_old, profile_keys),
            "selected_d1_2019_2024": _profile(prior_mid, profile_keys),
        },
        "metrics": {
            "selected_d1_2012_2018": _metrics(tuple(
                t for t in selected_d1_unique if PRIOR_OLD_START <= ensure_utc(t.entry_at) < PRIOR_MID_START
            )),
            "selected_d1_2019_2024": _metrics(tuple(
                t for t in selected_d1_unique if PRIOR_MID_START <= ensure_utc(t.entry_at) < PRIOR_MID_END
            )),
            "early_2025_selected_d1": _metrics(tuple(early_d1)),
        },
        "effect_sizes": effects,
        "top_distinguishing_features": ranked[:12],
        "change_points": list(change_points),
        "counts": {
            "bootstrap_realized_d1": len(bootstrap_realized),
            "bootstrap_winners_d1": len(bootstrap_winners),
            "bootstrap_losers_d1": len(bootstrap_losers),
            "selected_d1_2012_2018": len(prior_old),
            "selected_d1_2019_2024": len(prior_mid),
            "early_2025_selected_d1": len(early_annotated),
            "early_2025_cash_accepted_entries": sum(1 for x in early_annotated if x["cash_accepted_before_first_1000"]),
        },
        "note": (
            "V122 is deliberately forensic. It identifies which already-frozen causal market fingerprints "
            "were unusual on the D1 trades that bootstrapped $100 to $1,000. No discovered feature or "
            "threshold receives execution authority here; any detector must be preregistered separately."
        ),
    }
