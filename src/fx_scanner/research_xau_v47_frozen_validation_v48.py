from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    ROUTES as V47_ROUTES,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_FROZEN_VALIDATION_V48"
ARTIFACT_CONTRACT = "XAU_V47_FROZEN_VALIDATION_V48_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
assert FROZEN_ROUTE in V47_ROUTES

VALIDATION_COST_IDS = ("LOW_1700", "V24_STRESS_4675")
FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": compute_metrics(values).payload(),
        "direction_metrics": _direction_metrics(values),
    }


def _year_slices(
    trades: Sequence[TournamentTrade],
    *,
    start: datetime,
    end: datetime,
    trading_dates: Sequence[Any],
) -> dict[str, Any]:
    by_year: dict[int, list[TournamentTrade]] = defaultdict(list)
    for trade in trades:
        ts = ensure_utc(trade.entry_at)
        if start <= ts < end:
            by_year[ts.year].append(trade)

    date_by_year: dict[int, int] = defaultdict(int)
    for day in trading_dates:
        if start.date() <= day < end.date():
            date_by_year[day.year] += 1

    out: dict[str, Any] = {}
    for year in range(start.year, end.year + 1):
        values = tuple(by_year.get(year, ()))
        out[str(year)] = _stats(values, date_by_year.get(year, 0))
    return out


def _rolling_three_year(
    trades: Sequence[TournamentTrade],
    *,
    trading_dates: Sequence[Any],
    first_year: int,
    last_year: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for year in range(first_year, last_year - 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 3, 1, 1, tzinfo=timezone.utc)
        selected = tuple(
            x for x in trades
            if start <= ensure_utc(x.entry_at) < end
        )
        days = sum(1 for d in trading_dates if start.date() <= d < end.date())
        out[f"{year}_{year+2}"] = _stats(selected, days)
    return out


def _verdict(
    *,
    full_portfolio_metrics: Mapping[str, Any],
    core_metrics: Mapping[str, Any],
    annual: Mapping[str, Any],
    rolling: Mapping[str, Any],
) -> dict[str, Any]:
    pf = full_portfolio_metrics.get("profit_factor")
    exp = full_portfolio_metrics.get("expectancy_r")
    core_net = float(core_metrics.get("gross_profit_r") or 0.0) - float(core_metrics.get("gross_loss_r") or 0.0)
    net = float(full_portfolio_metrics.get("gross_profit_r") or 0.0) - float(full_portfolio_metrics.get("gross_loss_r") or 0.0)
    dd = float(full_portfolio_metrics.get("max_drawdown_r") or 0.0)

    nonnegative_years = sum(
        1 for row in annual.values()
        if float(row["metrics"].get("gross_profit_r") or 0.0)
        - float(row["metrics"].get("gross_loss_r") or 0.0) >= 0.0
    )
    observed_years = sum(1 for row in annual.values() if int(row["trades"]) > 0)
    rolling_floor = min(
        (
            float(row["metrics"].get("gross_profit_r") or 0.0)
            - float(row["metrics"].get("gross_loss_r") or 0.0)
        )
        for row in rolling.values()
    ) if rolling else 0.0

    checks = {
        "full_pf_ge_1_10": pf is not None and float(pf) >= 1.10,
        "full_expectancy_ge_0_05r": exp is not None and float(exp) >= 0.05,
        "beats_core_by_at_least_5r": net >= core_net + 5.0,
        "max_drawdown_le_20r": dd <= 20.0,
        "nonnegative_year_fraction_ge_60pct": (
            observed_years > 0 and nonnegative_years / observed_years >= 0.60
        ),
        "worst_3y_window_ge_minus_5r": rolling_floor >= -5.0,
    }
    return {
        "checks": checks,
        "all_pass": all(checks.values()),
        "portfolio_net_r": net,
        "core_net_r": core_net,
        "nonnegative_years": nonnegative_years,
        "observed_years": observed_years,
        "worst_3y_net_r": rolling_floor,
    }


def evaluate_v48(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
    cost_scenarios: Mapping[str, M15ResearchCosts] | None = None,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V48_EMPTY_HISTORY")
    costs_map = dict(COST_SCENARIOS if cost_scenarios is None else cost_scenarios)
    missing = [x for x in VALIDATION_COST_IDS if x not in costs_map]
    if missing:
        raise ValueError(f"V48_MISSING_COST_SCENARIOS:{missing}")

    start, end = FULL_START, FULL_END
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(era_dates)

    scenarios: dict[str, Any] = {}
    for cost_id in VALIDATION_COST_IDS:
        costs = costs_map[cost_id]
        classic_all = _simulate_d1_classic(rows, costs=costs, pip_size=pip_size)
        classic = _period(classic_all, start=start, end=end)

        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        gated_families: dict[str, tuple[TournamentTrade, ...]] = {}
        gate_payload: dict[str, Any] = {}
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            gated_families[family] = gated
            gate_payload[family] = {
                **gate,
                "candidate_full_metrics": compute_metrics(
                    _period(candidate, start=start, end=end)
                ).payload(),
                "gated_full_metrics": compute_metrics(
                    _period(gated, start=start, end=end)
                ).payload(),
            }

        satellite = tuple(
            trade
            for family in FAMILY_MAP
            for trade in _period(gated_families[family], start=start, end=end)
        )
        portfolio = _limit_concurrency(
            _dedupe_with_classic((*classic, *satellite))
        )

        annual = _year_slices(
            portfolio,
            start=start,
            end=end,
            trading_dates=era_dates,
        )
        rolling = _rolling_three_year(
            portfolio,
            trading_dates=era_dates,
            first_year=start.year,
            last_year=end.year,
        )

        cash = _cash_path_stopout_safe(
            portfolio,
            spec=broker_spec,
            tiers=leverage_tiers,
            account_leverage=ACCOUNT_LEVERAGE,
            stopout_pct=MARGIN_FLOOR_PCT,
            trading_dates=era_dates,
        )

        portfolio_stats = _stats(portfolio, trading_days)
        core_stats = _stats(classic, trading_days)
        scenarios[cost_id] = {
            "costs": asdict(costs),
            "core_d1_classic": core_stats,
            "satellite": _stats(satellite, trading_days),
            "portfolio": portfolio_stats,
            "gates": gate_payload,
            "annual": annual,
            "rolling_3y": rolling,
            "cash_fixed_001": cash,
            "verdict": _verdict(
                full_portfolio_metrics=portfolio_stats["metrics"],
                core_metrics=core_stats["metrics"],
                annual=annual,
                rolling=rolling,
            ),
        }

    low_net = scenarios["LOW_1700"]["verdict"]["portfolio_net_r"]
    stress_net = scenarios["V24_STRESS_4675"]["verdict"]["portfolio_net_r"]

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "history_rows": len(rows),
        "trading_days": trading_days,
        "frozen_candidate": {
            "route": FROZEN_ROUTE,
            "gate_logic": "V47_UNCHANGED",
            "entry_families": list(FAMILY_MAP.values()),
            "parameter_retuning": False,
            "cost_scenarios": list(VALIDATION_COST_IDS),
        },
        "cross_cost_checks": {
            "low_cost_net_not_below_stress_net": low_net >= stress_net,
        },
        "scenarios": scenarios,
        "note": (
            "V48 freezes the V47 candidate and evaluates one continuous 2012-2026 path, "
            "calendar-year slices, rolling three-year windows, realistic-low and stress costs. "
            "It does not tune thresholds or grant execution authority."
        ),
    }
