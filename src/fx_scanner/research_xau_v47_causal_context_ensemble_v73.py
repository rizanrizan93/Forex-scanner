from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, time, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_canonical_ict_context_v65 import _build_context_map, _signal_key
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_h1_structure_context_v56 import build_h1_structure_context
from .research_xau_h1_volatility_state_v63 import build_h1_volatility_context
from .research_xau_hierarchical_regime_router_v35 import (
    L20_ID,
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _limit_concurrency, _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_realized_skew_state_v64 import build_prior_day_skew_context
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_CAUSAL_CONTEXT_ENSEMBLE_V73"
ARTIFACT_CONTRACT = "XAU_V47_CAUSAL_CONTEXT_ENSEMBLE_V73_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")

MODEL_LOOKBACK_TRADING_DAYS = 252
MIN_COMPLETED_TRAINING_TRADES = 60
RIDGE_LAMBDA = 10.0
PREDICTION_THRESHOLD_R = 0.0
COLD_START_POLICY = "PASS_THROUGH"


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
        "direction_metrics": _direction_metrics(values),
    }


def _unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    seen: set[tuple[Any, ...]] = set()
    output: list[TournamentTrade] = []
    for trade in sorted(
        trades,
        key=lambda x: (
            ensure_utc(x.signal_at),
            str(x.strategy_id),
            ensure_utc(x.entry_at),
        ),
    ):
        key = (
            str(trade.strategy_id),
            ensure_utc(trade.signal_at),
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
            str(trade.direction),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(trade)
    return tuple(output)


def _friction_pips(costs: M15ResearchCosts) -> float:
    return (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
    )


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if isfinite(x) else default


def _one_hot(value: str, levels: Sequence[str]) -> list[float]:
    return [1.0 if value == level else 0.0 for level in levels]


FEATURE_NAMES = (
    "family_l20",
    "ict_sweep",
    "ict_fvg",
    "ict_order_block",
    "ict_ote",
    "ict_premium_discount",
    "ict_anti_chase",
    "ict_confluence_scaled",
    "break_bull_bos",
    "break_bull_mss",
    "break_bear_bos",
    "break_bear_mss",
    "structure_bull",
    "structure_bear",
    "structure_mixed",
    "vol_q1",
    "vol_q2",
    "vol_q3",
    "vol_q4",
    "vol_q5",
    "skew_q1",
    "skew_q2",
    "skew_q3",
    "skew_q4",
    "skew_q5",
    "entry_friction_scaled",
    "post_transition_age_scaled",
)


def _feature_vector(
    trade: TournamentTrade,
    *,
    d1_lookup: _Asof,
    structure_lookup: _Asof,
    volatility_lookup: _Asof,
    skew_lookup: _Asof,
    ict_map: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    costs: M15ResearchCosts,
    pip_size: float,
) -> np.ndarray:
    signal_at = ensure_utc(trade.signal_at)
    d1 = d1_lookup.row(signal_at)
    structure = structure_lookup.row(signal_at)
    volatility = volatility_lookup.row(signal_at)
    skew = skew_lookup.row(signal_at)
    ict = ict_map.get(_signal_key(trade), {})

    event = "NONE" if structure is None else str(structure.get("last_break_event") or "NONE")
    state = "INSUFFICIENT" if structure is None else str(
        structure.get("swing_structure_state") or "INSUFFICIENT"
    )
    vol_state = "UNAVAILABLE" if volatility is None else str(
        volatility.get("vol_state") or "UNAVAILABLE"
    )
    skew_state = "UNAVAILABLE" if skew is None else str(
        skew.get("skew_state") or "UNAVAILABLE"
    )

    risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
    risk_pips = risk_price / float(pip_size) if risk_price > 0.0 else float("inf")
    friction_r = (
        _friction_pips(costs) / risk_pips
        if isfinite(risk_pips) and risk_pips > 0.0
        else 1.0
    )
    age = 0 if d1 is None else int(_finite(d1.get("post_transition_age_days"), 0.0))

    values: list[float] = [
        1.0 if str(trade.strategy_id) == L20_ID else 0.0,
        1.0 if bool(ict.get("swept_liquidity")) else 0.0,
        1.0 if bool(ict.get("fvg_retest")) else 0.0,
        1.0 if bool(ict.get("order_block_retest")) else 0.0,
        1.0 if bool(ict.get("ote_retest")) else 0.0,
        1.0 if bool(ict.get("premium_discount_ok")) else 0.0,
        1.0 if bool(ict.get("anti_chase_ok")) else 0.0,
        min(4.0, max(0.0, _finite(ict.get("confluence_count"), 0.0))) / 4.0,
        *_one_hot(event, ("BULL_BOS", "BULL_MSS", "BEAR_BOS", "BEAR_MSS")),
        *_one_hot(state, ("BULL_HH_HL", "BEAR_LH_LL", "MIXED_OR_RANGE")),
        *_one_hot(vol_state, ("Q1_LOW", "Q2", "Q3", "Q4", "Q5_HIGH")),
        *_one_hot(
            skew_state,
            ("Q1_MOST_NEGATIVE", "Q2", "Q3", "Q4", "Q5_MOST_POSITIVE"),
        ),
        min(2.0, max(0.0, float(friction_r) / 0.10)),
        min(1.5, max(0.0, float(age) / 20.0)),
    ]
    if len(values) != len(FEATURE_NAMES):
        raise ValueError("V73_FEATURE_LENGTH_MISMATCH")
    return np.asarray(values, dtype=float)


def _cutoff_date(signal_at: datetime, trading_dates: Sequence[Any]) -> Any:
    dates = tuple(trading_dates)
    signal_date = ensure_utc(signal_at).date()
    pos = bisect_left(dates, signal_date)
    if not dates:
        return signal_date
    if pos <= MODEL_LOOKBACK_TRADING_DAYS:
        return dates[0]
    return dates[pos - MODEL_LOOKBACK_TRADING_DAYS]


def _fit_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_current: np.ndarray,
) -> float:
    means = x_train.mean(axis=0)
    stds = x_train.std(axis=0)
    stds = np.where(stds > 1e-9, stds, 1.0)
    z_train = (x_train - means) / stds
    z_current = (x_current - means) / stds

    design = np.column_stack([np.ones(len(z_train)), z_train])
    current = np.concatenate([[1.0], z_current])
    penalty = np.eye(design.shape[1], dtype=float) * RIDGE_LAMBDA
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ y_train,
    )
    return float(current @ beta)


def _causal_predictions(
    trades: Sequence[TournamentTrade],
    *,
    features: Mapping[tuple[Any, ...], np.ndarray],
    trading_dates: Sequence[Any],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], tuple[TournamentTrade, ...]]:
    ordered_signal = tuple(sorted(trades, key=lambda x: ensure_utc(x.signal_at)))
    ordered_exit = tuple(sorted(trades, key=lambda x: ensure_utc(x.exit_at)))
    predictions: dict[tuple[Any, ...], dict[str, Any]] = {}
    kept: list[TournamentTrade] = []

    def key(trade: TournamentTrade) -> tuple[Any, ...]:
        return (
            str(trade.strategy_id),
            ensure_utc(trade.signal_at),
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
        )

    for trade in ordered_signal:
        signal_at = ensure_utc(trade.signal_at)
        cutoff = datetime.combine(
            _cutoff_date(signal_at, trading_dates),
            time.min,
            tzinfo=timezone.utc,
        )
        training = tuple(
            row
            for row in ordered_exit
            if cutoff <= ensure_utc(row.exit_at) < signal_at
        )
        ready = len(training) >= MIN_COMPLETED_TRAINING_TRADES
        predicted = None
        if ready:
            x_train = np.vstack([features[key(row)] for row in training])
            y_train = np.asarray([float(row.net_r) for row in training], dtype=float)
            predicted = _fit_predict(x_train, y_train, features[key(trade)])

        pass_overlay = (
            True
            if not ready and COLD_START_POLICY == "PASS_THROUGH"
            else bool(predicted is not None and predicted > PREDICTION_THRESHOLD_R)
        )
        if pass_overlay:
            kept.append(trade)
        predictions[key(trade)] = {
            "signal_at": signal_at.isoformat(),
            "training_trades": len(training),
            "model_ready": ready,
            "predicted_expectancy_r": predicted,
            "realized_net_r": float(trade.net_r),
            "overlay_kept": pass_overlay,
        }

    return predictions, tuple(kept)


def _prediction_diagnostics(predictions: Mapping[tuple[Any, ...], Mapping[str, Any]]) -> dict[str, Any]:
    ready = [
        row
        for row in predictions.values()
        if bool(row["model_ready"]) and row["predicted_expectancy_r"] is not None
    ]
    if not ready:
        return {
            "model_ready_predictions": 0,
            "pearson_prediction_vs_realized": None,
            "positive_prediction_count": 0,
            "negative_prediction_count": 0,
            "positive_prediction_realized_expectancy_r": None,
            "negative_prediction_realized_expectancy_r": None,
        }
    pred = np.asarray([float(row["predicted_expectancy_r"]) for row in ready], dtype=float)
    actual = np.asarray([float(row["realized_net_r"]) for row in ready], dtype=float)
    corr = None
    if len(ready) >= 2 and float(pred.std()) > 1e-12 and float(actual.std()) > 1e-12:
        corr = float(np.corrcoef(pred, actual)[0, 1])
    positive = actual[pred > PREDICTION_THRESHOLD_R]
    negative = actual[pred <= PREDICTION_THRESHOLD_R]
    return {
        "model_ready_predictions": len(ready),
        "pearson_prediction_vs_realized": corr,
        "positive_prediction_count": int(len(positive)),
        "negative_prediction_count": int(len(negative)),
        "positive_prediction_realized_expectancy_r": (
            None if len(positive) == 0 else float(positive.mean())
        ),
        "negative_prediction_realized_expectancy_r": (
            None if len(negative) == 0 else float(negative.mean())
        ),
    }


def _net(stats: Mapping[str, Any]) -> float:
    metric = stats["metrics"]
    return float(metric.get("gross_profit_r") or 0.0) - float(metric.get("gross_loss_r") or 0.0)


def _window_compare(
    *,
    baseline: Sequence[TournamentTrade],
    overlay: Sequence[TournamentTrade],
    trading_dates: Sequence[Any],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    base = tuple(x for x in baseline if start <= ensure_utc(x.entry_at) < end)
    kept = tuple(x for x in overlay if start <= ensure_utc(x.entry_at) < end)
    days = sum(1 for d in trading_dates if start.date() <= d < end.date())
    base_stats = _stats(base, days)
    kept_stats = _stats(kept, days)
    return {
        "baseline": base_stats,
        "overlay": kept_stats,
        "overlay_delta_net_r": _net(kept_stats) - _net(base_stats),
        "overlay_delta_drawdown_r": (
            float(kept_stats["metrics"].get("max_drawdown_r") or 0.0)
            - float(base_stats["metrics"].get("max_drawdown_r") or 0.0)
        ),
    }


def evaluate_v73(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V73_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V73_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    structure_context = build_h1_structure_context(rows)
    volatility_context = build_h1_volatility_context(rows)
    skew_context = build_prior_day_skew_context(rows)
    d1_lookup = _Asof(d1_context)
    structure_lookup = _Asof(structure_context)
    volatility_lookup = _Asof(volatility_context)
    skew_lookup = _Asof(skew_context)

    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=FULL_END,
    )
    era_dates = _trading_dates(rows, start=FULL_START, end=FULL_END)
    era_days = len(era_dates)

    scenarios: dict[str, Any] = {}
    for cost_id in REQUIRED_COSTS:
        costs = cost_scenarios[cost_id]
        annotated = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        baseline_all: list[TournamentTrade] = []
        family_gates: dict[str, Any] = {}
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(annotated[family], route=FROZEN_ROUTE)
            gated, gate = gate_family_causally(candidate, trading_dates=full_dates)
            gated = _period(gated, start=FULL_START, end=FULL_END)
            baseline_all.extend(gated)
            family_gates[family] = gate

        baseline = _unique(baseline_all)
        ict_map = _build_context_map(rows, baseline)

        def trade_key(trade: TournamentTrade) -> tuple[Any, ...]:
            return (
                str(trade.strategy_id),
                ensure_utc(trade.signal_at),
                ensure_utc(trade.entry_at),
                ensure_utc(trade.exit_at),
            )

        features = {
            trade_key(trade): _feature_vector(
                trade,
                d1_lookup=d1_lookup,
                structure_lookup=structure_lookup,
                volatility_lookup=volatility_lookup,
                skew_lookup=skew_lookup,
                ict_map=ict_map,
                costs=costs,
                pip_size=pip_size,
            )
            for trade in baseline
        }
        predictions, overlay = _causal_predictions(
            baseline,
            features=features,
            trading_dates=full_dates,
        )

        core = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=FULL_START,
            end=FULL_END,
        )
        baseline_portfolio = _limit_concurrency(_dedupe_with_classic((*core, *baseline)))
        overlay_portfolio = _limit_concurrency(_dedupe_with_classic((*core, *overlay)))

        annual = {}
        for year in range(FULL_START.year, FULL_END.year + 1):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            annual[str(year)] = _window_compare(
                baseline=baseline,
                overlay=overlay,
                trading_dates=era_dates,
                start=start,
                end=end,
            )

        rolling = {}
        for year in range(FULL_START.year, FULL_END.year - 1):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 3, 1, 1, tzinfo=timezone.utc)
            rolling[f"{year}_{year+2}"] = _window_compare(
                baseline=baseline,
                overlay=overlay,
                trading_dates=era_dates,
                start=start,
                end=end,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "baseline_v47_satellite": _stats(baseline, era_days),
            "causal_overlay_satellite": _stats(overlay, era_days),
            "baseline_d1_plus_satellite": _stats(baseline_portfolio, era_days),
            "overlay_d1_plus_satellite": _stats(overlay_portfolio, era_days),
            "prediction_diagnostics": _prediction_diagnostics(predictions),
            "prediction_rows": list(predictions.values()),
            "annual": annual,
            "rolling_3y": rolling,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "period_start": FULL_START.isoformat(),
        "period_end_exclusive": FULL_END.isoformat(),
        "feature_names": list(FEATURE_NAMES),
        "preregistered_contract": {
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "training_population": "all original V47-approved trades, including trades the overlay itself would suppress",
            "training_uses_only_completed_prior_trades": True,
            "rolling_training_lookback_trading_days": MODEL_LOOKBACK_TRADING_DAYS,
            "minimum_completed_training_trades": MIN_COMPLETED_TRAINING_TRADES,
            "ridge_lambda": RIDGE_LAMBDA,
            "prediction_threshold_r": PREDICTION_THRESHOLD_R,
            "cold_start_policy": COLD_START_POLICY,
            "single_model_only": True,
            "hyperparameter_grid_search": False,
            "feature_selection_from_v73_outcomes": False,
            "secondary_features_change_v69_forward_contract": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V73 tests whether a single predeclared ridge model can adaptively combine the already-frozen "
            "V47 context features using only completed prior V47 trades. It is historical shadow research "
            "and cannot alter the independently frozen V69 prospective sweep experiment."
        ),
    }
