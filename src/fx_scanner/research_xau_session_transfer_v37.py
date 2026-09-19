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

RESEARCH_VERSION = "XAU_SESSION_DIRECTION_TRANSFER_V37"
ARTIFACT_CONTRACT = "XAU_SESSION_DIRECTION_TRANSFER_V37_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
PIP_SIZE = 0.01
ATR_PERIOD = 14
MIN_SOURCE_MOVE_ATR = 0.25
STOP_ATR = 1.25
SCHEMA_TP_SENTINEL_R = 100.0


@dataclass(frozen=True, slots=True)
class TransferVariant:
    variant_id: str
    source_session: str
    target_session: str
    mode: str
    require_d1_match: bool = False


VARIANTS = (
    TransferVariant("V37_EU_FROM_ASIA_MOM", SESSION_ASIA, SESSION_EUROPE, "MOMENTUM"),
    TransferVariant("V37_EU_FROM_ASIA_REV", SESSION_ASIA, SESSION_EUROPE, "REVERSAL"),
    TransferVariant("V37_US_FROM_EU_MOM", SESSION_EUROPE, SESSION_US, "MOMENTUM"),
    TransferVariant("V37_US_FROM_EU_REV", SESSION_EUROPE, SESSION_US, "REVERSAL"),
    TransferVariant("V37_EU_FROM_ASIA_MOM_D1", SESSION_ASIA, SESSION_EUROPE, "MOMENTUM", True),
    TransferVariant("V37_EU_FROM_ASIA_REV_D1", SESSION_ASIA, SESSION_EUROPE, "REVERSAL", True),
    TransferVariant("V37_US_FROM_EU_MOM_D1", SESSION_EUROPE, SESSION_US, "MOMENTUM", True),
    TransferVariant("V37_US_FROM_EU_REV_D1", SESSION_EUROPE, SESSION_US, "REVERSAL", True),
)


@dataclass(frozen=True, slots=True)
class TransferSignal:
    variant_id: str
    signal_index: int
    target_last_index: int
    direction: str
    signal_at: Any
    atr: float
    source_return: float
    source_move_atr: float
    source_session: str
    target_session: str
    d1_regime: str
    d1_match: bool


def _validate(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("V37_EMPTY_HISTORY")
    if any(x.symbol.upper() != SYMBOL or x.timeframe.upper() != TIMEFRAME for x in bars):
        raise ValueError("V37_REQUIRES_XAUUSD_M15")
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
    if len(values) != period:
        return None
    atr = sum(values) / float(period)
    return atr if isfinite(atr) and atr > 0.0 else None


def _session_groups(rows: Sequence[Bar]) -> dict[tuple[str, Any], tuple[int, ...]]:
    groups: dict[tuple[str, Any], list[int]] = {}
    for i, row in enumerate(rows):
        session = _session_name(row)
        if session is None:
            continue
        key = _session_key(row, session)
        groups.setdefault((session, key), []).append(i)
    return {k: tuple(v) for k, v in groups.items()}


def _source_direction(source_return: float, mode: str) -> str:
    base = "LONG" if source_return > 0.0 else "SHORT"
    if mode == "MOMENTUM":
        return base
    if mode == "REVERSAL":
        return "SHORT" if base == "LONG" else "LONG"
    raise ValueError(f"V37_MODE_INVALID:{mode}")


def extract_transfer_signals(
    bars: Sequence[Bar],
    *,
    variant: TransferVariant,
) -> tuple[TransferSignal, ...]:
    rows = _validate(bars)
    groups = _session_groups(rows)
    d1 = build_d1_context(rows)
    d1_lookup = _Asof(d1)
    out: list[TransferSignal] = []

    target_groups = sorted(
        (
            (key, idxs)
            for (session, key), idxs in groups.items()
            if session == variant.target_session
        ),
        key=lambda x: ensure_utc(rows[x[1][0]].timestamp),
    )
    for key, target_idxs in target_groups:
        source_idxs = groups.get((variant.source_session, key))
        if not source_idxs or not target_idxs:
            continue
        source_first = source_idxs[0]
        source_last = source_idxs[-1]
        target_first = target_idxs[0]
        target_last = target_idxs[-1]
        if source_last >= target_first:
            continue

        source_open = float(rows[source_first].open)
        source_close = float(rows[source_last].close)
        source_return = source_close - source_open
        if source_return == 0.0:
            continue

        atr = _prior_atr(rows, target_first)
        if atr is None:
            continue
        move_atr = abs(source_return) / atr
        if move_atr < MIN_SOURCE_MOVE_ATR:
            continue

        direction = _source_direction(source_return, variant.mode)
        context = d1_lookup.row(rows[target_first].timestamp)
        if context is None:
            continue
        d1_side = int(context.get("regime_side") or 0)
        trade_side = 1 if direction == "LONG" else -1
        d1_match = d1_side == trade_side
        if variant.require_d1_match and not d1_match:
            continue

        out.append(
            TransferSignal(
                variant_id=variant.variant_id,
                signal_index=target_first,
                target_last_index=target_last,
                direction=direction,
                signal_at=ensure_utc(rows[target_first].timestamp),
                atr=float(atr),
                source_return=float(source_return),
                source_move_atr=float(move_atr),
                source_session=variant.source_session,
                target_session=variant.target_session,
                d1_regime=str(context.get("regime")),
                d1_match=bool(d1_match),
            )
        )
    return tuple(out)


def simulate_transfer(
    bars: Sequence[Bar],
    *,
    signals: Sequence[TransferSignal],
    costs: M15ResearchCosts,
    pip_size: float = PIP_SIZE,
) -> tuple[TournamentTrade, ...]:
    rows = _validate(bars)
    out: list[TournamentTrade] = []
    for signal in signals:
        entry_index = signal.signal_index
        exit_index = signal.target_last_index
        if entry_index >= len(rows) or exit_index <= entry_index:
            continue

        entry = float(rows[entry_index].open)
        risk_price = STOP_ATR * float(signal.atr)
        if risk_price <= 0.0:
            continue
        stop = entry - risk_price if signal.direction == "LONG" else entry + risk_price
        schema_tp = (
            entry + SCHEMA_TP_SENTINEL_R * risk_price
            if signal.direction == "LONG"
            else entry - SCHEMA_TP_SENTINEL_R * risk_price
        )
        risk_pips = risk_price / pip_size
        trade: TournamentTrade | None = None

        for i in range(entry_index, exit_index + 1):
            bar = rows[i]
            stop_hit = (
                float(bar.low) <= stop
                if signal.direction == "LONG"
                else float(bar.high) >= stop
            )
            if stop_hit:
                bars_held = i - entry_index
                cost_r = _roundtrip_cost_r(
                    risk_pips=risk_pips,
                    bars_held=bars_held,
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
                    bars_held,
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
            bars_held = exit_index - entry_index
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=bars_held,
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
                bars_held,
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


def _move_bucket(value: float) -> str:
    if value < 0.50:
        return "0.25_0.50"
    if value < 1.00:
        return "0.50_1.00"
    return "GE_1.00"


def _signal_trade_diagnostics(
    signals: Sequence[TransferSignal],
    trades: Sequence[TournamentTrade],
    *,
    trading_days: int,
) -> dict[str, Any]:
    trade_by_key = {
        (x.strategy_id, ensure_utc(x.signal_at), x.direction): x for x in trades
    }

    def selected(predicate):
        items = []
        for signal in signals:
            if not predicate(signal):
                continue
            trade = trade_by_key.get(
                (signal.variant_id, ensure_utc(signal.signal_at), signal.direction)
            )
            if trade is not None:
                items.append(trade)
        return tuple(items)

    return {
        "move_bucket": {
            bucket: _trade_stats(
                selected(lambda s, b=bucket: _move_bucket(s.source_move_atr) == b),
                trading_days,
            )
            for bucket in ("0.25_0.50", "0.50_1.00", "GE_1.00")
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


def evaluate_v37(
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
        variant.variant_id: extract_transfer_signals(rows, variant=variant)
        for variant in VARIANTS
    }
    scenario_results: dict[str, Any] = {}

    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=PIP_SIZE),
            start=start,
            end=end,
        )
        variants_payload: dict[str, Any] = {}
        portfolios_payload: dict[str, Any] = {}

        for variant in VARIANTS:
            signals = tuple(
                s
                for s in signal_map[variant.variant_id]
                if start <= ensure_utc(s.signal_at) < end
            )
            all_trades = simulate_transfer(rows, signals=signals, costs=costs)
            trades = _period(all_trades, start=start, end=end)
            variants_payload[variant.variant_id] = {
                "variant": asdict(variant),
                **_trade_stats(trades, trading_days),
                "diagnostics": _signal_trade_diagnostics(
                    signals,
                    trades,
                    trading_days=trading_days,
                ),
            }

            combined = _limit_concurrency(_dedupe_with_classic((*classic, *trades)))
            payload = {
                **_trade_stats(combined, trading_days),
            }
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
        "history_rows": len(rows),
        "trading_days": trading_days,
        "preregistered_contract": {
            "source_move_min_atr": MIN_SOURCE_MOVE_ATR,
            "protective_stop_atr": STOP_ATR,
            "exit": "TARGET_SESSION_LAST_M15_CLOSE_UNLESS_STOP_FIRST",
            "europe_source": "COMPLETED_ASIA_SESSION_RETURN",
            "us_source": "COMPLETED_EUROPE_SESSION_RETURN",
            "entry": "FIRST_M15_OPEN_OF_TARGET_SESSION",
            "d1_role": "CONTEXT_ONLY_OR_OPTIONAL_DIRECTION_MATCH",
            "uses_session_high_low_as_trigger": False,
            "uses_breakout_retest": False,
            "uses_liquidity_sweep": False,
            "selection_uses_future_outcomes": False,
        },
        "variants": [asdict(x) for x in VARIANTS],
        "scenario_results": scenario_results,
        "note": (
            "V37 is an orthogonal session-return transfer study. It does not retune "
            "L12/L20, does not use session high/low breakout or sweep triggers, and "
            "remains historical diagnostic evidence only."
        ),
    }
