from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import (
    TournamentCosts,
    TournamentTrade,
    compute_metrics,
    simulate_variant,
)
from .demo_donchian_contextual_v2 import CORE_VARIANT
from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _Asof
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_DONCHIAN_REGIME_AUDIT_V83"
ARTIFACT_CONTRACT = "XAU_DONCHIAN_REGIME_AUDIT_V83_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ROUTES = (
    "RAW",
    "LONG_ALL",
    "SHORT_ALL",
    "SECULAR_BULL_LONG",
    "SECULAR_BEAR_SHORT",
    "SECULAR_ALIGNED_BOTH",
    "SECULAR_BULL_REACCEL_LONG_1_20",
)


def _to_h1(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    ordered = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    frame = pd.DataFrame(
        {
            "time": [ensure_utc(x.timestamp) for x in ordered],
            "open": [float(x.open) for x in ordered],
            "high": [float(x.high) for x in ordered],
            "low": [float(x.low) for x in ordered],
            "close": [float(x.close) for x in ordered],
        }
    ).set_index("time")
    h1 = (
        frame.resample("1h", label="right", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .dropna()
        .reset_index()
    )
    return tuple(
        Bar(
            symbol="XAUUSD",
            timeframe="H1",
            timestamp=ensure_utc(row.time.to_pydatetime()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_count=1,
            spread_avg=0.0,
            spread_max=0.0,
        )
        for row in h1.itertuples(index=False)
    )


def _costs(value: M15ResearchCosts) -> TournamentCosts:
    return TournamentCosts(
        spread_pips=float(value.spread_pips),
        slippage_pips=float(value.slippage_pips),
        commission_pips_round_trip=float(value.commission_pips_round_trip),
        swap_pips_per_day=float(value.swap_pips_per_day),
        spread_multiplier=float(value.spread_multiplier),
        slippage_multiplier=float(value.slippage_multiplier),
    )


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(
    trades: Sequence[TournamentTrade],
    *,
    start,
    end,
) -> tuple[TournamentTrade, ...]:
    lo = ensure_utc(start)
    hi = ensure_utc(end)
    return tuple(
        trade
        for trade in trades
        if lo <= ensure_utc(trade.entry_at) < hi
    )


def _route(
    trades: Sequence[TournamentTrade],
    *,
    d1_context,
    route: str,
) -> tuple[TournamentTrade, ...]:
    if route == "RAW":
        return tuple(trades)

    lookup = _Asof(d1_context)
    output: list[TournamentTrade] = []
    for trade in trades:
        d1 = lookup.row(trade.signal_at)
        if d1 is None:
            continue
        direction = str(trade.direction).upper()
        secular_side = int(d1.get("secular_side") or 0)
        secular_regime = str(d1.get("secular_regime") or "SECULAR_NEUTRAL")
        transition = str(d1.get("transition_outcome") or "NONE")
        age = int(d1.get("post_transition_age_days") or 0)

        keep = False
        if route == "LONG_ALL":
            keep = direction == "LONG"
        elif route == "SHORT_ALL":
            keep = direction == "SHORT"
        elif route == "SECULAR_BULL_LONG":
            keep = direction == "LONG" and secular_regime == "SECULAR_BULL"
        elif route == "SECULAR_BEAR_SHORT":
            keep = direction == "SHORT" and secular_regime == "SECULAR_BEAR"
        elif route == "SECULAR_ALIGNED_BOTH":
            keep = (
                (direction == "LONG" and secular_side == 1)
                or (direction == "SHORT" and secular_side == -1)
            )
        elif route == "SECULAR_BULL_REACCEL_LONG_1_20":
            keep = (
                direction == "LONG"
                and secular_regime == "SECULAR_BULL"
                and transition == "REACCELERATION"
                and 1 <= age <= 20
            )
        else:
            raise ValueError(f"V83_ROUTE_INVALID:{route}")

        if keep:
            output.append(trade)
    return tuple(output)


def evaluate_v83(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V83_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    h1 = _to_h1(rows)
    d1_context = build_secular_d1(rows)

    scenario_results: dict[str, Any] = {}
    for cost_id, cost in cost_scenarios.items():
        all_trades = simulate_variant(
            h1,
            symbol="XAUUSD",
            pip_size=float(pip_size),
            variant=CORE_VARIANT,
            costs=_costs(cost),
        )
        era_trades = _period(all_trades, start=start, end=end)
        routed = {
            route: _route(
                era_trades,
                d1_context=d1_context,
                route=route,
            )
            for route in ROUTES
        }
        scenario_results[cost_id] = {
            "costs": asdict(_costs(cost)),
            "routes": {
                route: {
                    "trades": len(trades),
                    "metrics": _metrics(trades),
                }
                for route, trades in routed.items()
            },
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "h1_bars": len(h1),
        "preregistered_contract": {
            "symbol": "XAUUSD",
            "core_variant": {
                "lookback": CORE_VARIANT.lookback,
                "atr_period": CORE_VARIANT.atr_period,
                "buffer_atr": CORE_VARIANT.buffer_atr,
            },
            "stop_atr": 2.0,
            "reward_r": 2.0,
            "max_hold_h1": 72,
            "routes": list(ROUTES),
            "d1_secular_definition": "V46 unchanged",
            "parameter_grid_search": False,
            "donchian_params_retuned": False,
            "route_selected_as_winner": False,
            "historical_bid_spread_source": "preset XAU cost scenario; no invented historical ASK",
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V83 isolates the repository's already-frozen Donchian 20/ATR14/0.10 H1 core on XAU "
            "under XAU-specific cost assumptions. D1 secular routes are attribution only; no route "
            "is selected or promoted by this study."
        ),
    }
