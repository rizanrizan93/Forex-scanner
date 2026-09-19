from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade
from .models import Bar, ensure_utc
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_era_robustness_v31 import (
    _dedupe_with_classic,
    _simulate_d1_classic,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _period,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import (
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1
from .research_xau_v47_frozen_validation_v48 import (
    FROZEN_ROUTE,
    FULL_END,
    FULL_START,
    VALIDATION_COST_IDS,
    _rolling_three_year,
    _stats,
    _year_slices,
)

RESEARCH_VERSION = "XAU_SATELLITE_ATTRIBUTION_V59"
ARTIFACT_CONTRACT = "XAU_SATELLITE_ATTRIBUTION_V59_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True


def _net(metrics: Mapping[str, Any]) -> float:
    return (
        float(metrics.get("gross_profit_r") or 0.0)
        - float(metrics.get("gross_loss_r") or 0.0)
    )


def _attribution(
    *,
    core: Mapping[str, Any],
    portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    core_metrics = core["metrics"]
    portfolio_metrics = portfolio["metrics"]
    return {
        "incremental_net_r": _net(portfolio_metrics) - _net(core_metrics),
        "drawdown_delta_r": (
            float(portfolio_metrics.get("max_drawdown_r") or 0.0)
            - float(core_metrics.get("max_drawdown_r") or 0.0)
        ),
        "trade_delta": int(portfolio["trades"]) - int(core["trades"]),
        "portfolio_pf": portfolio_metrics.get("profit_factor"),
        "core_pf": core_metrics.get("profit_factor"),
        "portfolio_expectancy_r": portfolio_metrics.get("expectancy_r"),
        "core_expectancy_r": core_metrics.get("expectancy_r"),
    }


def _window_attribution(
    *,
    core_windows: Mapping[str, Mapping[str, Any]],
    portfolio_windows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    keys = sorted(set(core_windows) | set(portfolio_windows))
    output: dict[str, Any] = {}
    for key in keys:
        core = core_windows.get(key, {"trades": 0, "metrics": {}})
        portfolio = portfolio_windows.get(key, {"trades": 0, "metrics": {}})
        output[key] = {
            "core": core,
            "portfolio": portfolio,
            "delta": _attribution(core=core, portfolio=portfolio),
        }
    return output


def _summaries(
    *,
    core: Sequence[TournamentTrade],
    satellite: Sequence[TournamentTrade],
    portfolio: Sequence[TournamentTrade],
    trading_dates,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    trading_days = len(
        tuple(d for d in trading_dates if start.date() <= d < end.date())
    )
    core_stats = _stats(core, trading_days)
    satellite_stats = _stats(satellite, trading_days)
    portfolio_stats = _stats(portfolio, trading_days)

    core_year = _year_slices(
        core,
        start=start,
        end=end,
        trading_dates=trading_dates,
    )
    portfolio_year = _year_slices(
        portfolio,
        start=start,
        end=end,
        trading_dates=trading_dates,
    )
    annual = _window_attribution(
        core_windows=core_year,
        portfolio_windows=portfolio_year,
    )

    core_roll = _rolling_three_year(
        core,
        trading_dates=trading_dates,
        first_year=start.year,
        last_year=end.year,
    )
    portfolio_roll = _rolling_three_year(
        portfolio,
        trading_dates=trading_dates,
        first_year=start.year,
        last_year=end.year,
    )
    rolling = _window_attribution(
        core_windows=core_roll,
        portfolio_windows=portfolio_roll,
    )

    observed_rolling = {
        key: row
        for key, row in rolling.items()
        if int(row["core"]["trades"]) > 0
        or int(row["portfolio"]["trades"]) > 0
    }

    worst_core = min(
        observed_rolling.items(),
        key=lambda item: _net(item[1]["core"]["metrics"]),
    ) if observed_rolling else None
    worst_portfolio = min(
        observed_rolling.items(),
        key=lambda item: _net(item[1]["portfolio"]["metrics"]),
    ) if observed_rolling else None
    worst_incremental = min(
        observed_rolling.items(),
        key=lambda item: float(item[1]["delta"]["incremental_net_r"]),
    ) if observed_rolling else None

    negative_incremental = [
        key
        for key, row in observed_rolling.items()
        if float(row["delta"]["incremental_net_r"]) < 0.0
    ]
    positive_incremental = [
        key
        for key, row in observed_rolling.items()
        if float(row["delta"]["incremental_net_r"]) > 0.0
    ]

    return {
        "core": core_stats,
        "satellite": satellite_stats,
        "portfolio": portfolio_stats,
        "full_period_attribution": _attribution(
            core=core_stats,
            portfolio=portfolio_stats,
        ),
        "annual": annual,
        "rolling_3y": rolling,
        "attribution_summary": {
            "worst_core_3y": (
                None
                if worst_core is None
                else {
                    "window": worst_core[0],
                    "core_net_r": _net(worst_core[1]["core"]["metrics"]),
                    "portfolio_net_r": _net(
                        worst_core[1]["portfolio"]["metrics"]
                    ),
                    "incremental_net_r": worst_core[1]["delta"][
                        "incremental_net_r"
                    ],
                }
            ),
            "worst_portfolio_3y": (
                None
                if worst_portfolio is None
                else {
                    "window": worst_portfolio[0],
                    "core_net_r": _net(worst_portfolio[1]["core"]["metrics"]),
                    "portfolio_net_r": _net(
                        worst_portfolio[1]["portfolio"]["metrics"]
                    ),
                    "incremental_net_r": worst_portfolio[1]["delta"][
                        "incremental_net_r"
                    ],
                }
            ),
            "worst_incremental_3y": (
                None
                if worst_incremental is None
                else {
                    "window": worst_incremental[0],
                    "core_net_r": _net(
                        worst_incremental[1]["core"]["metrics"]
                    ),
                    "portfolio_net_r": _net(
                        worst_incremental[1]["portfolio"]["metrics"]
                    ),
                    "incremental_net_r": worst_incremental[1]["delta"][
                        "incremental_net_r"
                    ],
                }
            ),
            "rolling_windows_positive_incremental": positive_incremental,
            "rolling_windows_negative_incremental": negative_incremental,
            "rolling_windows_total": len(observed_rolling),
        },
    }


def evaluate_v59(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V59_EMPTY_HISTORY")

    start = FULL_START
    end = FULL_END
    costs_map = dict(cost_scenarios)
    missing = [x for x in VALIDATION_COST_IDS if x not in costs_map]
    if missing:
        raise ValueError(f"V59_MISSING_COST_SCENARIOS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)

    scenarios: dict[str, Any] = {}
    for cost_id in VALIDATION_COST_IDS:
        costs = costs_map[cost_id]
        classic_all = _simulate_d1_classic(
            rows,
            costs=costs,
            pip_size=pip_size,
        )
        classic = _period(classic_all, start=start, end=end)

        annotated = _family_streams(
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
                annotated[family],
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            gated_families[family] = gated
            gate_payload[family] = gate

        satellite = tuple(
            trade
            for family in FAMILY_MAP
            for trade in _period(
                gated_families[family],
                start=start,
                end=end,
            )
        )
        portfolio = _limit_concurrency(
            _dedupe_with_classic((*classic, *satellite))
        )

        scenarios[cost_id] = {
            "costs": asdict(costs),
            "gates": gate_payload,
            **_summaries(
                core=classic,
                satellite=satellite,
                portfolio=portfolio,
                trading_dates=era_dates,
                start=start,
                end=end,
            ),
        }

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
        "frozen_candidate": {
            "route": FROZEN_ROUTE,
            "families": FAMILY_MAP,
            "gate_logic": "V47_UNCHANGED",
            "strategy_or_threshold_retuning": False,
        },
        "attribution_question": (
            "Separate inherited D1-core historical weakness from incremental "
            "satellite contribution. V59 does not replace or relax the V48 "
            "pre-registered absolute portfolio gate."
        ),
        "scenarios": scenarios,
    }
