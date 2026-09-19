from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    _Asof,
    _max_losing_streak,
    _period,
    build_d1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts, _roundtrip_cost_r
from .research_xau_session_liquidity_adaptive_v3 import (
    SESSION_ASIA,
    SESSION_EUROPE,
    SESSION_US,
    _session_key,
    _session_name,
)

RESEARCH_VERSION = "XAU_D1_SESSION_CARRY_V38"
ARTIFACT_CONTRACT = "XAU_D1_SESSION_CARRY_V38_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
PIP_SIZE = 0.01
ATR_PERIOD = 14
STOP_ATR = 1.25
SCHEMA_TP_SENTINEL_R = 100.0


@dataclass(frozen=True, slots=True)
class CarryVariant:
    variant_id: str
    session: str
    strong_only: bool


VARIANTS = (
    CarryVariant("V38_ASIA_D1_CARRY", SESSION_ASIA, False),
    CarryVariant("V38_EUROPE_D1_CARRY", SESSION_EUROPE, False),
    CarryVariant("V38_US_D1_CARRY", SESSION_US, False),
    CarryVariant("V38_ASIA_STRONG_D1_CARRY", SESSION_ASIA, True),
    CarryVariant("V38_EUROPE_STRONG_D1_CARRY", SESSION_EUROPE, True),
    CarryVariant("V38_US_STRONG_D1_CARRY", SESSION_US, True),
)


@dataclass(frozen=True, slots=True)
class CarrySignal:
    variant_id: str
    signal_index: int
    target_last_index: int
    direction: str
    signal_at: Any
    atr: float
    session: str
    d1_regime: str
    days_in_regime: int
    maturity: str


def _validate(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("V38_EMPTY_HISTORY")
    if any(x.symbol.upper() != SYMBOL or x.timeframe.upper() != TIMEFRAME for x in bars):
        raise ValueError("V38_REQUIRES_XAUUSD_M15")
    return bars


def _prior_atr(rows: Sequence[Bar], index: int, period: int = ATR_PERIOD) -> float | None:
    if index < period:
        return None
    values: list[float] = []
    for i in range(index - period, index):
        current = rows[i]
        prev_close = float(rows[i - 1].close) if i > 0 else float(current.close)
        tr = max(
            float(current.high) - float(current.low),
            abs(float(current.high) - prev_close),
            abs(float(current.low) - prev_close),
        )
        values.append(tr)
    atr = sum(values) / float(period)
    return atr if len(values) == period and isfinite(atr) and atr > 0.0 else None


def _session_groups(rows: Sequence[Bar]) -> dict[tuple[str, Any], tuple[int, ...]]:
    groups: dict[tuple[str, Any], list[int]] = {}
    for i, row in enumerate(rows):
        session = _session_name(row)
        if session is None:
            continue
        key = _session_key(row, session)
        groups.setdefault((session, key), []).append(i)
    return {key: tuple(value) for key, value in groups.items()}


def extract_carry_signals(
    bars: Sequence[Bar],
    *,
    variant: CarryVariant,
) -> tuple[CarrySignal, ...]:
    rows = _validate(bars)
    groups = _session_groups(rows)
    d1 = build_d1_context(rows)
    lookup = _Asof(d1)

    selected_groups = sorted(
        (
            (key, idxs)
            for (session, key), idxs in groups.items()
            if session == variant.session
        ),
        key=lambda x: ensure_utc(rows[x[1][0]].timestamp),
    )

    out: list[CarrySignal] = []
    for _, idxs in selected_groups:
        if not idxs:
            continue
        first = idxs[0]
        last = idxs[-1]
        context = lookup.row(rows[first].timestamp)
        if context is None:
            continue
        side = int(context.get("regime_side") or 0)
        regime = str(context.get("regime"))
        if side == 0:
            continue
        if variant.strong_only and regime not in {"STRONG_BULL", "STRONG_BEAR"}:
            continue

        atr = _prior_atr(rows, first)
        if atr is None:
            continue
        direction = "LONG" if side > 0 else "SHORT"
        out.append(
            CarrySignal(
                variant_id=variant.variant_id,
                signal_index=first,
                target_last_index=last,
                direction=direction,
                signal_at=ensure_utc(rows[first].timestamp),
                atr=float(atr),
                session=variant.session,
                d1_regime=regime,
                days_in_regime=int(context.get("days_in_regime") or 0),
                maturity=str(context.get("maturity")),
            )
        )
    return tuple(out)


def simulate_carry(
    bars: Sequence[Bar],
    *,
    signals: Sequence[CarrySignal],
    costs: M15ResearchCosts,
    pip_size: float = PIP_SIZE,
) -> tuple[TournamentTrade, ...]:
    rows = _validate(bars)
    out: list[TournamentTrade] = []
    for signal in signals:
        entry_index = signal.signal_index
        exit_index = signal.target_last_index
        if exit_index <= entry_index or entry_index >= len(rows):
            continue

        entry = float(rows[entry_index].open)
        risk_price = STOP_ATR * signal.atr
        if risk_price <= 0.0:
            continue
        stop = entry - risk_price if signal.direction == "LONG" else entry + risk_price
        schema_tp = (
            entry + SCHEMA_TP_SENTINEL_R * risk_price
            if signal.direction == "LONG"
            else entry - SCHEMA_TP_SENTINEL_R * risk_price
        )
        risk_pips = risk_price / pip_size
        trade = None
        for i in range(entry_index, exit_index + 1):
            bar = rows[i]
            stop_hit = (
                float(bar.low) <= stop
                if signal.direction == "LONG"
                else float(bar.high) >= stop
            )
            if stop_hit:
                held = i - entry_index
                cost_r = _roundtrip_cost_r(
                    risk_pips=risk_pips,
                    bars_held=held,
                    costs=costs,
                )
                trade = TournamentTrade(
                    signal.variant_id,
                    SYMBOL,
                    signal.direction,
                    signal.signal_at,
                    ensure_utc(rows[entry_index].timestamp),
                    ensure_utc(bar.timestamp),
                    entry_index,
                    i,
                    entry,
                    stop,
                    signal.atr,
                    stop,
                    schema_tp,
                    -1.0,
                    cost_r,
                    -1.0 - cost_r,
                    held,
                    "STOP_HIT",
                )
                break

        if trade is None:
            bar = rows[exit_index]
            exit_price = float(bar.close)
            gross_r = (
                (exit_price - entry) / risk_price
                if signal.direction == "LONG"
                else (entry - exit_price) / risk_price
            )
            held = exit_index - entry_index
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=held,
                costs=costs,
            )
            trade = TournamentTrade(
                signal.variant_id,
                SYMBOL,
                signal.direction,
                signal.signal_at,
                ensure_utc(rows[entry_index].timestamp),
                ensure_utc(bar.timestamp),
                entry_index,
                exit_index,
                entry,
                exit_price,
                signal.atr,
                stop,
                schema_tp,
                gross_r,
                cost_r,
                gross_r - cost_r,
                held,
                "SESSION_TIME_EXIT",
            )
        out.append(trade)
    return tuple(out)


def _trade_stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": compute_metrics(values).payload(),
        "by_direction": {
            direction: compute_metrics(tuple(x for x in values if x.direction == direction)).payload()
            for direction in ("LONG", "SHORT")
        },
    }


def _signal_trade_diagnostics(
    signals: Sequence[CarrySignal],
    trades: Sequence[TournamentTrade],
    *,
    trading_days: int,
) -> dict[str, Any]:
    trade_by_key = {
        (x.strategy_id, ensure_utc(x.signal_at), x.direction): x for x in trades
    }

    def selected(predicate):
        values = []
        for signal in signals:
            if not predicate(signal):
                continue
            trade = trade_by_key.get(
                (signal.variant_id, ensure_utc(signal.signal_at), signal.direction)
            )
            if trade is not None:
                values.append(trade)
        return tuple(values)

    maturity_values = ("EARLY", "ESTABLISHED", "MATURE", "EXTENDED")
    return {
        "maturity": {
            maturity: _trade_stats(
                selected(lambda s, m=maturity: s.maturity == m),
                trading_days,
            )
            for maturity in maturity_values
        },
        "regime": {
            regime: _trade_stats(
                selected(lambda s, r=regime: s.d1_regime == r),
                trading_days,
            )
            for regime in ("STRONG_BULL", "BULL", "BEAR", "STRONG_BEAR")
        },
    }


def evaluate_v38(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = _validate(bars)
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    signal_map = {
        variant.variant_id: extract_carry_signals(rows, variant=variant)
        for variant in VARIANTS
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=PIP_SIZE),
            start=start,
            end=end,
        )
        variant_payload: dict[str, Any] = {}
        portfolio_payload: dict[str, Any] = {}

        for variant in VARIANTS:
            signals = tuple(
                s for s in signal_map[variant.variant_id]
                if start <= ensure_utc(s.signal_at) < end
            )
            trades = _period(
                simulate_carry(rows, signals=signals, costs=costs),
                start=start,
                end=end,
            )
            variant_payload[variant.variant_id] = {
                "variant": asdict(variant),
                **_trade_stats(trades, trading_days),
                "diagnostics": _signal_trade_diagnostics(
                    signals,
                    trades,
                    trading_days=trading_days,
                ),
            }

            combined = _limit_concurrency(_dedupe_with_classic((*classic, *trades)))
            payload = _trade_stats(combined, trading_days)
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    combined,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolio_payload[f"D1_CLASSIC_PLUS_{variant.variant_id}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "classic": _trade_stats(classic, trading_days),
            "variants": variant_payload,
            "portfolios": portfolio_payload,
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
        "history_rows": len(rows),
        "trading_days": trading_days,
        "preregistered_contract": {
            "direction_source": "COMPLETED_D1_REGIME_SIDE_ONLY",
            "entry": "FIRST_M15_OPEN_OF_SESSION",
            "protective_stop_atr": STOP_ATR,
            "exit": "SESSION_LAST_M15_CLOSE_UNLESS_STOP_FIRST",
            "session_trigger_features": "NONE",
            "uses_previous_session_direction": False,
            "uses_breakout_retest": False,
            "uses_liquidity_sweep": False,
            "uses_l12_l20": False,
            "selection_uses_future_outcomes": False,
        },
        "variants": [asdict(x) for x in VARIANTS],
        "scenario_results": scenario_results,
        "note": (
            "V38 tests whether the existing causal D1 regime can be monetized through "
            "fixed session carry without technical entry triggers. Historical evidence "
            "remains diagnostic and cannot directly authorize execution."
        ),
    }
