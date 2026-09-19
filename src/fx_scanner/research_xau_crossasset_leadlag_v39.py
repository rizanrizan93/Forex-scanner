from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import timedelta
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

RESEARCH_VERSION = "XAU_CROSSASSET_LEADLAG_V39"
ARTIFACT_CONTRACT = "XAU_CROSSASSET_LEADLAG_V39_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

TARGET_SYMBOL = "XAUUSD"
SOURCE_XAG = "XAGUSD"
SOURCE_EUR = "EURUSD"
SOURCE_TIMEFRAME = "H1"
TARGET_TIMEFRAME = "M15"
PIP_SIZE = 0.01
SOURCE_ATR_PERIOD = 14
SOURCE_MOVE_MIN_ATR = 0.75
TARGET_ATR_PERIOD = 14
STOP_ATR = 1.25
HOLD_M15_BARS = 4
MAX_ENTRY_LAG_MINUTES = 30
SCHEMA_TP_SENTINEL_R = 100.0


@dataclass(frozen=True, slots=True)
class LeadLagVariant:
    variant_id: str
    source_family: str
    require_d1_match: bool


VARIANTS = (
    LeadLagVariant("V39_XAG_LEAD", "XAG", False),
    LeadLagVariant("V39_EURUSD_WEAKUSD_LEAD", "EUR", False),
    LeadLagVariant("V39_XAG_EUR_AGREE", "AGREE", False),
    LeadLagVariant("V39_XAG_LEAD_D1", "XAG", True),
    LeadLagVariant("V39_EURUSD_WEAKUSD_LEAD_D1", "EUR", True),
    LeadLagVariant("V39_XAG_EUR_AGREE_D1", "AGREE", True),
)


@dataclass(frozen=True, slots=True)
class SourceEvent:
    source: str
    completed_at: Any
    direction: str
    strength_atr: float


@dataclass(frozen=True, slots=True)
class CrossAssetSignal:
    variant_id: str
    signal_index: int
    direction: str
    signal_at: Any
    atr: float
    source_family: str
    source_strength_atr: float
    xag_strength_atr: float | None
    eur_strength_atr: float | None
    d1_regime: str
    d1_match: bool


def _validate_target(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("V39_EMPTY_XAU_HISTORY")
    if any(x.symbol.upper() != TARGET_SYMBOL or x.timeframe.upper() != TARGET_TIMEFRAME for x in bars):
        raise ValueError("V39_REQUIRES_XAUUSD_M15")
    return bars


def _validate_source(rows: Sequence[Bar], symbol: str) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError(f"V39_EMPTY_SOURCE:{symbol}")
    if any(x.symbol.upper() != symbol or x.timeframe.upper() != SOURCE_TIMEFRAME for x in bars):
        raise ValueError(f"V39_REQUIRES_{symbol}_H1")
    return bars


def _prior_atr(rows: Sequence[Bar], index: int, period: int) -> float | None:
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
    if len(values) != period:
        return None
    atr = sum(values) / float(period)
    return atr if isfinite(atr) and atr > 0.0 else None


def _source_events(rows: Sequence[Bar], *, symbol: str) -> dict[Any, SourceEvent]:
    bars = _validate_source(rows, symbol)
    output: dict[Any, SourceEvent] = {}
    for i in range(SOURCE_ATR_PERIOD, len(bars)):
        atr = _prior_atr(bars, i, SOURCE_ATR_PERIOD)
        if atr is None:
            continue
        row = bars[i]
        move = float(row.close) - float(row.open)
        if move == 0.0:
            continue
        strength = abs(move) / atr
        if strength < SOURCE_MOVE_MIN_ATR:
            continue
        completed_at = ensure_utc(row.timestamp) + timedelta(hours=1)
        # XAG positive maps to XAU LONG. EURUSD positive is preregistered as
        # broad USD-weakness evidence and also maps to XAU LONG.
        direction = "LONG" if move > 0.0 else "SHORT"
        output[completed_at] = SourceEvent(
            source=symbol,
            completed_at=completed_at,
            direction=direction,
            strength_atr=float(strength),
        )
    return output


def _candidate_events(
    *,
    xag_h1: Sequence[Bar],
    eur_h1: Sequence[Bar],
    source_family: str,
) -> tuple[tuple[Any, str, float, float | None, float | None], ...]:
    xag = _source_events(xag_h1, symbol=SOURCE_XAG)
    eur = _source_events(eur_h1, symbol=SOURCE_EUR)

    values: list[tuple[Any, str, float, float | None, float | None]] = []
    if source_family == "XAG":
        for stamp, event in xag.items():
            values.append((stamp, event.direction, event.strength_atr, event.strength_atr, None))
    elif source_family == "EUR":
        for stamp, event in eur.items():
            values.append((stamp, event.direction, event.strength_atr, None, event.strength_atr))
    elif source_family == "AGREE":
        for stamp in sorted(set(xag).intersection(eur)):
            a = xag[stamp]
            e = eur[stamp]
            if a.direction != e.direction:
                continue
            # Agreement strength is bounded by the weaker leg.
            values.append(
                (
                    stamp,
                    a.direction,
                    min(a.strength_atr, e.strength_atr),
                    a.strength_atr,
                    e.strength_atr,
                )
            )
    else:
        raise ValueError(f"V39_SOURCE_FAMILY_INVALID:{source_family}")
    values.sort(key=lambda x: ensure_utc(x[0]))
    return tuple(values)


def extract_signals(
    xau_m15: Sequence[Bar],
    *,
    xag_h1: Sequence[Bar],
    eur_h1: Sequence[Bar],
    variant: LeadLagVariant,
) -> tuple[CrossAssetSignal, ...]:
    xau = _validate_target(xau_m15)
    xau_times = tuple(ensure_utc(x.timestamp) for x in xau)
    d1_lookup = _Asof(build_d1_context(xau))
    candidates = _candidate_events(
        xag_h1=xag_h1,
        eur_h1=eur_h1,
        source_family=variant.source_family,
    )

    out: list[CrossAssetSignal] = []
    for completed_at, direction, strength, xag_strength, eur_strength in candidates:
        stamp = ensure_utc(completed_at)
        i = bisect_left(xau_times, stamp)
        if i >= len(xau):
            continue
        lag_minutes = (xau_times[i] - stamp).total_seconds() / 60.0
        if lag_minutes < 0.0 or lag_minutes > MAX_ENTRY_LAG_MINUTES:
            continue
        if i + HOLD_M15_BARS - 1 >= len(xau):
            continue

        target_atr = _prior_atr(xau, i, TARGET_ATR_PERIOD)
        if target_atr is None:
            continue
        context = d1_lookup.row(xau_times[i])
        if context is None:
            continue
        d1_side = int(context.get("regime_side") or 0)
        trade_side = 1 if direction == "LONG" else -1
        d1_match = d1_side == trade_side
        if variant.require_d1_match and not d1_match:
            continue

        out.append(
            CrossAssetSignal(
                variant_id=variant.variant_id,
                signal_index=i,
                direction=direction,
                signal_at=xau_times[i],
                atr=float(target_atr),
                source_family=variant.source_family,
                source_strength_atr=float(strength),
                xag_strength_atr=xag_strength,
                eur_strength_atr=eur_strength,
                d1_regime=str(context.get("regime")),
                d1_match=bool(d1_match),
            )
        )
    return tuple(out)


def simulate(
    xau_m15: Sequence[Bar],
    *,
    signals: Sequence[CrossAssetSignal],
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_target(xau_m15)
    out: list[TournamentTrade] = []
    for signal in signals:
        entry_index = signal.signal_index
        last_index = entry_index + HOLD_M15_BARS - 1
        if last_index >= len(rows):
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
        risk_pips = risk_price / PIP_SIZE
        trade = None

        for i in range(entry_index, last_index + 1):
            bar = rows[i]
            stop_hit = (
                float(bar.low) <= stop
                if signal.direction == "LONG"
                else float(bar.high) >= stop
            )
            if not stop_hit:
                continue
            held = i - entry_index
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=held,
                costs=costs,
            )
            trade = TournamentTrade(
                signal.variant_id,
                TARGET_SYMBOL,
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
            bar = rows[last_index]
            exit_price = float(bar.close)
            gross_r = (
                (exit_price - entry) / risk_price
                if signal.direction == "LONG"
                else (entry - exit_price) / risk_price
            )
            held = HOLD_M15_BARS - 1
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=held,
                costs=costs,
            )
            trade = TournamentTrade(
                signal.variant_id,
                TARGET_SYMBOL,
                signal.direction,
                signal.signal_at,
                ensure_utc(rows[entry_index].timestamp),
                ensure_utc(bar.timestamp),
                entry_index,
                last_index,
                entry,
                exit_price,
                signal.atr,
                stop,
                schema_tp,
                gross_r,
                cost_r,
                gross_r - cost_r,
                held,
                "H1_TIME_EXIT",
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


def _strength_bucket(value: float) -> str:
    if value < 1.00:
        return "0.75_1.00"
    if value < 1.50:
        return "1.00_1.50"
    return "GE_1.50"


def _diagnostics(
    signals: Sequence[CrossAssetSignal],
    trades: Sequence[TournamentTrade],
    *,
    trading_days: int,
) -> dict[str, Any]:
    lookup = {
        (x.strategy_id, ensure_utc(x.signal_at), x.direction): x for x in trades
    }

    def selected(predicate):
        values = []
        for signal in signals:
            if not predicate(signal):
                continue
            trade = lookup.get(
                (signal.variant_id, ensure_utc(signal.signal_at), signal.direction)
            )
            if trade is not None:
                values.append(trade)
        return tuple(values)

    return {
        "source_strength": {
            bucket: _trade_stats(
                selected(lambda s, b=bucket: _strength_bucket(s.source_strength_atr) == b),
                trading_days,
            )
            for bucket in ("0.75_1.00", "1.00_1.50", "GE_1.50")
        },
        "d1_relation": {
            "MATCH": _trade_stats(selected(lambda s: s.d1_match), trading_days),
            "NON_MATCH": _trade_stats(selected(lambda s: not s.d1_match), trading_days),
        },
        "d1_regime": {
            regime: _trade_stats(
                selected(lambda s, r=regime: s.d1_regime == r),
                trading_days,
            )
            for regime in ("STRONG_BULL", "BULL", "TRANSITION", "BEAR", "STRONG_BEAR")
        },
    }


def evaluate_v39(
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
    xau = _validate_target(xau_m15)
    _validate_source(xag_h1, SOURCE_XAG)
    _validate_source(eur_h1, SOURCE_EUR)
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    trading_dates = _trading_dates(xau, start=start, end=end)
    trading_days = len(trading_dates)

    signal_map = {
        variant.variant_id: extract_signals(
            xau,
            xag_h1=xag_h1,
            eur_h1=eur_h1,
            variant=variant,
        )
        for variant in VARIANTS
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(xau, costs=costs, pip_size=PIP_SIZE),
            start=start,
            end=end,
        )
        variants_payload: dict[str, Any] = {}
        portfolios_payload: dict[str, Any] = {}

        for variant in VARIANTS:
            signals = tuple(
                s for s in signal_map[variant.variant_id]
                if start <= ensure_utc(s.signal_at) < end
            )
            trades = _period(
                simulate(xau, signals=signals, costs=costs),
                start=start,
                end=end,
            )
            variants_payload[variant.variant_id] = {
                "variant": asdict(variant),
                **_trade_stats(trades, trading_days),
                "diagnostics": _diagnostics(
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
            portfolios_payload[f"D1_CLASSIC_PLUS_{variant.variant_id}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "classic": _trade_stats(classic, trading_days),
            "variants": variants_payload,
            "portfolios": portfolios_payload,
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
        "target_rows": len(xau),
        "xag_h1_rows": len(xag_h1),
        "eur_h1_rows": len(eur_h1),
        "trading_days": trading_days,
        "preregistered_contract": {
            "source_timeframe": SOURCE_TIMEFRAME,
            "source_h1_must_be_completed": True,
            "source_atr_baseline_prior_only": True,
            "source_move_min_atr": SOURCE_MOVE_MIN_ATR,
            "xag_direction_mapping": "POSITIVE_XAG_H1_RETURN=>XAU_LONG; NEGATIVE=>SHORT",
            "eur_direction_mapping": "POSITIVE_EURUSD_H1_RETURN=>XAU_LONG; NEGATIVE=>SHORT",
            "agreement_requires_same_direction": True,
            "target_entry": "FIRST_XAU_M15_OPEN_AT_OR_AFTER_SOURCE_H1_COMPLETION",
            "max_entry_lag_minutes": MAX_ENTRY_LAG_MINUTES,
            "target_stop_atr": STOP_ATR,
            "target_hold_m15_bars": HOLD_M15_BARS,
            "uses_xau_breakout_trigger": False,
            "uses_liquidity_sweep": False,
            "uses_l12_l20": False,
            "selection_uses_future_outcomes": False,
        },
        "variants": [asdict(x) for x in VARIANTS],
        "scenario_results": scenario_results,
        "note": (
            "V39 tests preregistered cross-asset H1 lead/lag into XAU M15. "
            "Historical results remain diagnostic only and cannot authorize execution."
        ),
    }
