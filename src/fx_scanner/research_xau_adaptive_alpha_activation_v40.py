from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict
from datetime import datetime, time, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_crossasset_leadlag_v39 import (
    VARIANTS as CROSS_VARIANTS,
    extract_signals as extract_cross_signals,
    simulate as simulate_cross,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    L12_ID,
    L20_ID,
    MARGIN_FLOOR_PCT,
    _max_losing_streak,
    _period,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_ADAPTIVE_ALPHA_ACTIVATION_V40"
ARTIFACT_CONTRACT = "XAU_ADAPTIVE_ALPHA_ACTIVATION_V40_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

LOOKBACK_TRADING_DAYS = 126
MIN_COMPLETED_TRADES = 30
MIN_TRAILING_PF = 1.10
MIN_TRAILING_EXPECTANCY_R = 0.05

SATELLITE_FAMILIES = (
    "M15_L12",
    "M15_L20",
    "XAG_D1",
    "EUR_D1",
    "AGREE_D1",
)

CROSS_ID_MAP = {
    "XAG_D1": "V39_XAG_LEAD_D1",
    "EUR_D1": "V39_EURUSD_WEAKUSD_LEAD_D1",
    "AGREE_D1": "V39_XAG_EUR_AGREE_D1",
}


def _trade_stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": compute_metrics(values).payload(),
    }


def _trailing_health(values: Sequence[TournamentTrade]) -> dict[str, Any]:
    trades = tuple(values)
    n = len(trades)
    if n == 0:
        return {
            "completed_trades": 0,
            "profit_factor": None,
            "expectancy_r": None,
            "net_r": 0.0,
            "active": False,
        }
    net = [float(x.net_r) for x in trades]
    gross_profit = sum(x for x in net if x > 0.0)
    gross_loss = -sum(x for x in net if x < 0.0)
    pf = (
        float("inf")
        if gross_loss <= 0.0 and gross_profit > 0.0
        else (None if gross_loss <= 0.0 else gross_profit / gross_loss)
    )
    expectancy = sum(net) / float(n)
    active = (
        n >= MIN_COMPLETED_TRADES
        and pf is not None
        and pf >= MIN_TRAILING_PF
        and expectancy >= MIN_TRAILING_EXPECTANCY_R
    )
    return {
        "completed_trades": n,
        "profit_factor": pf,
        "expectancy_r": expectancy,
        "net_r": sum(net),
        "active": bool(active),
    }


def _date_cutoff(
    signal_at,
    *,
    trading_dates: Sequence[Any],
) -> Any:
    signal_date = ensure_utc(signal_at).date()
    dates = tuple(trading_dates)
    pos = bisect_left(dates, signal_date)
    if pos <= LOOKBACK_TRADING_DAYS:
        return dates[0] if dates else signal_date
    return dates[pos - LOOKBACK_TRADING_DAYS]


def gate_family_causally(
    trades: Sequence[TournamentTrade],
    *,
    trading_dates: Sequence[Any],
) -> tuple[tuple[TournamentTrade, ...], dict[str, Any]]:
    ordered_signal = tuple(sorted(trades, key=lambda x: ensure_utc(x.signal_at)))
    ordered_exit = tuple(sorted(trades, key=lambda x: ensure_utc(x.exit_at)))
    exit_times = tuple(ensure_utc(x.exit_at) for x in ordered_exit)

    kept: list[TournamentTrade] = []
    active_checks = 0
    inactive_checks = 0
    first_active_at = None
    last_health: dict[str, Any] | None = None

    for trade in ordered_signal:
        signal_at = ensure_utc(trade.signal_at)
        completed_end = bisect_left(exit_times, signal_at)
        cutoff_date = _date_cutoff(signal_at, trading_dates=trading_dates)
        cutoff = datetime.combine(cutoff_date, time.min, tzinfo=timezone.utc)
        completed_start = bisect_left(exit_times, cutoff, hi=completed_end)
        trailing = ordered_exit[completed_start:completed_end]
        health = _trailing_health(trailing)
        last_health = health
        if health["active"]:
            active_checks += 1
            if first_active_at is None:
                first_active_at = signal_at
            kept.append(trade)
        else:
            inactive_checks += 1

    total = active_checks + inactive_checks
    return tuple(kept), {
        "candidate_trades": len(ordered_signal),
        "kept_trades": len(kept),
        "suppressed_trades": len(ordered_signal) - len(kept),
        "activation_fraction": 0.0 if total == 0 else active_checks / float(total),
        "first_active_at": None if first_active_at is None else first_active_at.isoformat(),
        "last_health": last_health,
    }


def _m15_trade_streams(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
) -> dict[str, tuple[TournamentTrade, ...]]:
    by_id = {x.variant_id: x for x in M15_VARIANTS}
    result: dict[str, tuple[TournamentTrade, ...]] = {}
    for family, variant_id in (("M15_L12", L12_ID), ("M15_L20", L20_ID)):
        variant = by_id[variant_id]
        signals = extract_m15_breakout(rows, variant=variant)
        result[family] = simulate_m15(
            rows,
            signals=signals,
            costs=costs,
            pip_size=0.01,
        )
    return result


def _cross_trade_streams(
    xau: Sequence[Bar],
    *,
    xag_h1: Sequence[Bar],
    eur_h1: Sequence[Bar],
    costs: M15ResearchCosts,
) -> dict[str, tuple[TournamentTrade, ...]]:
    by_id = {x.variant_id: x for x in CROSS_VARIANTS}
    result: dict[str, tuple[TournamentTrade, ...]] = {}
    for family, variant_id in CROSS_ID_MAP.items():
        variant = by_id[variant_id]
        signals = extract_cross_signals(
            xau,
            xag_h1=xag_h1,
            eur_h1=eur_h1,
            variant=variant,
        )
        result[family] = simulate_cross(
            xau,
            signals=signals,
            costs=costs,
        )
    return result


def evaluate_v40(
    xau_m15: Sequence[Bar],
    *,
    xag_h1: Sequence[Bar],
    eur_h1: Sequence[Bar],
    era_id: str,
    era_start,
    era_end,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(xau_m15, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V40_EMPTY_XAU")
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)

    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    era_trading_days = len(era_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic_all = _simulate_d1_classic(rows, costs=costs, pip_size=0.01)
        classic = _period(classic_all, start=start, end=end)

        streams = {
            **_m15_trade_streams(rows, costs=costs),
            **_cross_trade_streams(
                rows,
                xag_h1=xag_h1,
                eur_h1=eur_h1,
                costs=costs,
            ),
        }

        gated_all: dict[str, tuple[TournamentTrade, ...]] = {}
        gate_payload: dict[str, Any] = {}
        for family in SATELLITE_FAMILIES:
            gated, gate = gate_family_causally(
                streams[family],
                trading_dates=full_dates,
            )
            gated_all[family] = gated
            gate_payload[family] = {
                **gate,
                "all_history_metrics": compute_metrics(streams[family]).payload(),
                "era_kept_metrics": compute_metrics(
                    _period(gated, start=start, end=end)
                ).payload(),
            }

        adaptive_satellites = tuple(
            trade
            for family in SATELLITE_FAMILIES
            for trade in _period(gated_all[family], start=start, end=end)
        )
        adaptive_portfolio = _limit_concurrency(
            _dedupe_with_classic((*classic, *adaptive_satellites))
        )

        always_on_l12_l20 = _limit_concurrency(
            _dedupe_with_classic(
                (
                    *classic,
                    *_period(streams["M15_L12"], start=start, end=end),
                    *_period(streams["M15_L20"], start=start, end=end),
                )
            )
        )

        payload = {
            "core_d1_classic": _trade_stats(classic, era_trading_days),
            "always_on_d1_plus_l12_l20": _trade_stats(
                always_on_l12_l20,
                era_trading_days,
            ),
            "adaptive_d1_plus_satellites": _trade_stats(
                adaptive_portfolio,
                era_trading_days,
            ),
            "gates": gate_payload,
            "adaptive_satellite_family_metrics": {
                family: _trade_stats(
                    _period(gated_all[family], start=start, end=end),
                    era_trading_days,
                )
                for family in SATELLITE_FAMILIES
            },
        }
        if cost_id == "V24_STRESS_4675":
            payload["adaptive_cash_fixed_001"] = _cash_path_stopout_safe(
                adaptive_portfolio,
                spec=broker_spec,
                tiers=leverage_tiers,
                account_leverage=ACCOUNT_LEVERAGE,
                stopout_pct=MARGIN_FLOOR_PCT,
                trading_dates=era_dates,
            )
        scenario_results[cost_id] = payload

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
        "era_trading_days": era_trading_days,
        "preregistered_gate": {
            "lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "min_completed_trades": MIN_COMPLETED_TRADES,
            "min_trailing_profit_factor": MIN_TRAILING_PF,
            "min_trailing_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "uses_only_trades_with_exit_before_current_signal": True,
            "core_d1_classic_always_on": True,
            "satellite_families": list(SATELLITE_FAMILIES),
            "threshold_grid_search": False,
            "era_or_calendar_year_feature_used": False,
            "selection_uses_future_outcomes": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V40 tests a causal online activation gate rather than another static alpha. "
            "All activation decisions use only completed prior net trades inside the fixed "
            "126-trading-day window. Historical success would still require forward DEMO validation."
        ),
    }
