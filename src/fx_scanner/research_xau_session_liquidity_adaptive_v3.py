from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentMetrics, TournamentTrade, compute_metrics, walk_forward
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_DEVELOPMENT_TRADES,
    MIN_HOLDOUT_TRADES,
    ContinuationSignal,
    _daily_coverage,
    _indicator_series,
    _metrics_pass,
    _validate_bars,
    simulate_trades,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_SESSION_LIQUIDITY_ADAPTIVE_V3"
ARTIFACT_CONTRACT = "XAU_SESSION_LIQUIDITY_ADAPTIVE_V3_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"

SESSION_ASIA = "ASIA"
SESSION_EUROPE = "EUROPE"
SESSION_US = "US"
VALID_SESSIONS = frozenset({SESSION_ASIA, SESSION_EUROPE, SESSION_US})


@dataclass(frozen=True, slots=True)
class SessionVariant:
    variant_id: str
    family: str
    target_reference_pairs: tuple[tuple[str, str], ...]
    target_r: float
    adaptive_adx_cutoff: float = 20.0
    reversal_adx_max: float = 25.0
    breakout_adx_min: float = 18.0
    sweep_min_atr: float = 0.03
    sweep_max_atr: float = 1.25
    reversal_body_atr: float = 0.35
    breakout_distance_atr: float = 0.08
    breakout_body_atr: float = 0.60
    retest_bars: int = 6
    stop_buffer_atr: float = 0.25
    selection_eligible: bool = True


VARIANTS = (
    SessionVariant(
        "XAU_V3_EU_ASIA_ADAPT_R15",
        "ADAPTIVE",
        ((SESSION_EUROPE, SESSION_ASIA),),
        1.50,
    ),
    SessionVariant(
        "XAU_V3_US_EU_ADAPT_R15",
        "ADAPTIVE",
        ((SESSION_US, SESSION_EUROPE),),
        1.50,
    ),
    SessionVariant(
        "XAU_V3_EUUS_ADAPT_R15",
        "ADAPTIVE",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        1.50,
    ),
    SessionVariant(
        "XAU_V3_EUUS_ADAPT_ADX18_R15",
        "ADAPTIVE",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        1.50,
        adaptive_adx_cutoff=18.0,
    ),
    SessionVariant(
        "XAU_V3_EUUS_ADAPT_ADX25_R15",
        "ADAPTIVE",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        1.50,
        adaptive_adx_cutoff=25.0,
    ),
    SessionVariant(
        "XAU_V3_EUUS_ADAPT_R20",
        "ADAPTIVE",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        2.00,
    ),
    SessionVariant(
        "XAU_V3_EUUS_REVERSAL_R15",
        "REVERSAL",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        1.50,
    ),
    SessionVariant(
        "XAU_V3_EUUS_BREAKOUT_R15",
        "BREAKOUT",
        ((SESSION_EUROPE, SESSION_ASIA), (SESSION_US, SESSION_EUROPE)),
        1.50,
    ),
    SessionVariant(
        "XAU_V3_ASIA_PRIOR_US_REV_CONTROL",
        "REVERSAL",
        ((SESSION_ASIA, SESSION_US),),
        1.50,
        selection_eligible=False,
    ),
)


def _session_name(bar: Bar) -> str | None:
    hour = ensure_utc(bar.timestamp).hour
    if hour >= 22 or hour < 7:
        return SESSION_ASIA
    if 7 <= hour < 12:
        return SESSION_EUROPE
    if 12 <= hour < 21:
        return SESSION_US
    return None


def _session_key(bar: Bar, session: str):
    stamp = ensure_utc(bar.timestamp)
    if session == SESSION_ASIA:
        if stamp.hour >= 22:
            return (stamp + timedelta(days=1)).date()
        return stamp.date()
    return stamp.date()


def _reference_key(target_bar: Bar, target_session: str, reference_session: str):
    target_key = _session_key(target_bar, target_session)
    if target_session == SESSION_ASIA and reference_session == SESSION_US:
        return target_key - timedelta(days=1)
    return target_key


def _session_ranges(rows: Sequence[Bar]) -> dict[tuple[str, Any], dict[str, float]]:
    output: dict[tuple[str, Any], dict[str, float]] = {}
    for row in rows:
        session = _session_name(row)
        if session is None:
            continue
        key = _session_key(row, session)
        bucket = output.setdefault(
            (session, key),
            {"high": float(row.high), "low": float(row.low)},
        )
        bucket["high"] = max(float(bucket["high"]), float(row.high))
        bucket["low"] = min(float(bucket["low"]), float(row.low))
    return output


def _family_allows_reversal(variant: SessionVariant, adx_value: float) -> bool:
    if variant.family == "ADAPTIVE":
        return adx_value < float(variant.adaptive_adx_cutoff)
    if variant.family == "REVERSAL":
        return adx_value <= float(variant.reversal_adx_max)
    return False


def _family_allows_breakout(variant: SessionVariant, adx_value: float) -> bool:
    if variant.family == "ADAPTIVE":
        return adx_value >= float(variant.adaptive_adx_cutoff)
    if variant.family == "BREAKOUT":
        return adx_value >= float(variant.breakout_adx_min)
    return False


def _reversal_signal(
    *,
    rows: Sequence[Bar],
    index: int,
    reference: Mapping[str, float],
    atr_value: float,
    adx_value: float,
    variant: SessionVariant,
) -> ContinuationSignal | None:
    if not _family_allows_reversal(variant, adx_value):
        return None
    row = rows[index]
    body = abs(float(row.close) - float(row.open))
    if body < float(variant.reversal_body_atr) * atr_value:
        return None

    ref_high = float(reference["high"])
    ref_low = float(reference["low"])
    high_excess = (float(row.high) - ref_high) / atr_value
    low_excess = (ref_low - float(row.low)) / atr_value

    short_sweep = bool(
        variant.sweep_min_atr <= high_excess <= variant.sweep_max_atr
        and float(row.close) < ref_high
        and float(row.close) < float(row.open)
        and (float(row.high) - float(row.close)) / max(float(row.high) - float(row.low), 1e-12) >= 0.55
    )
    long_sweep = bool(
        variant.sweep_min_atr <= low_excess <= variant.sweep_max_atr
        and float(row.close) > ref_low
        and float(row.close) > float(row.open)
        and (float(row.close) - float(row.low)) / max(float(row.high) - float(row.low), 1e-12) >= 0.55
    )
    if short_sweep == long_sweep:
        return None

    direction = "SHORT" if short_sweep else "LONG"
    stop = (
        float(row.high) + float(variant.stop_buffer_atr) * atr_value
        if direction == "SHORT"
        else float(row.low) - float(variant.stop_buffer_atr) * atr_value
    )
    level = ref_high if direction == "SHORT" else ref_low
    return ContinuationSignal(
        variant_id=variant.variant_id,
        signal_index=index,
        direction=direction,
        signal_at=ensure_utc(row.timestamp),
        atr=atr_value,
        breakout_level=level,
        structural_stop=stop,
        reward_r=float(variant.target_r),
        impulse_index=index,
        retest_index=index,
        fvg_low=None,
        fvg_high=None,
    )


def _breakout_retest_signal(
    *,
    rows: Sequence[Bar],
    index: int,
    reference: Mapping[str, float],
    atr_value: float,
    adx_value: float,
    ema20: float,
    ema50: float,
    target_session: str,
    target_key: Any,
    variant: SessionVariant,
) -> ContinuationSignal | None:
    if not _family_allows_breakout(variant, adx_value):
        return None

    row = rows[index]
    body = abs(float(row.close) - float(row.open))
    if body < float(variant.breakout_body_atr) * atr_value:
        return None

    ref_high = float(reference["high"])
    ref_low = float(reference["low"])
    long_break = bool(
        float(row.close) >= ref_high + float(variant.breakout_distance_atr) * atr_value
        and float(row.close) > float(row.open)
        and ema20 > ema50
    )
    short_break = bool(
        float(row.close) <= ref_low - float(variant.breakout_distance_atr) * atr_value
        and float(row.close) < float(row.open)
        and ema20 < ema50
    )
    if long_break == short_break:
        return None

    direction = "LONG" if long_break else "SHORT"
    level = ref_high if direction == "LONG" else ref_low
    last = min(len(rows) - 2, index + int(variant.retest_bars))
    for retest_index in range(index + 1, last + 1):
        retest = rows[retest_index]
        if _session_name(retest) != target_session or _session_key(retest, target_session) != target_key:
            break
        accepted = float(retest.close) > level if direction == "LONG" else float(retest.close) < level
        touched = (
            float(retest.low) <= level + 0.20 * atr_value
            if direction == "LONG"
            else float(retest.high) >= level - 0.20 * atr_value
        )
        invalid = (
            float(retest.close) < level - 0.30 * atr_value
            if direction == "LONG"
            else float(retest.close) > level + 0.30 * atr_value
        )
        if invalid:
            break
        if not (accepted and touched):
            continue
        stop = (
            level - float(variant.stop_buffer_atr) * atr_value
            if direction == "LONG"
            else level + float(variant.stop_buffer_atr) * atr_value
        )
        return ContinuationSignal(
            variant_id=variant.variant_id,
            signal_index=retest_index,
            direction=direction,
            signal_at=ensure_utc(retest.timestamp),
            atr=atr_value,
            breakout_level=level,
            structural_stop=stop,
            reward_r=float(variant.target_r),
            impulse_index=index,
            retest_index=retest_index,
            fvg_low=None,
            fvg_high=None,
        )
    return None


def extract_session_signals(
    bars: Sequence[Bar],
    *,
    variant: SessionVariant,
) -> tuple[ContinuationSignal, ...]:
    rows = _validate_bars(bars)
    indicators = _indicator_series(rows)
    ranges = _session_ranges(rows)
    wanted = set(variant.target_reference_pairs)
    output: list[ContinuationSignal] = []
    seen: set[tuple[str, Any, str]] = set()

    for index, row in enumerate(rows[:-2]):
        target_session = _session_name(row)
        if target_session is None:
            continue
        target_key = _session_key(row, target_session)

        atr_raw = indicators["atr"][index]
        adx_raw = indicators["adx"][index]
        ema20_raw = indicators["ema20"][index]
        ema50_raw = indicators["ema50"][index]
        if None in (atr_raw, adx_raw, ema20_raw, ema50_raw):
            continue
        atr_value = float(atr_raw)
        adx_value = float(adx_raw)
        if atr_value <= 0.0:
            continue

        for target, reference_session in wanted:
            if target != target_session:
                continue
            reference_key = _reference_key(row, target_session, reference_session)
            reference = ranges.get((reference_session, reference_key))
            if reference is None:
                continue

            reversal = _reversal_signal(
                rows=rows,
                index=index,
                reference=reference,
                atr_value=atr_value,
                adx_value=adx_value,
                variant=variant,
            )
            if reversal is not None:
                key = (target_session, target_key, reversal.direction)
                if key not in seen:
                    output.append(reversal)
                    seen.add(key)

            breakout = _breakout_retest_signal(
                rows=rows,
                index=index,
                reference=reference,
                atr_value=atr_value,
                adx_value=adx_value,
                ema20=float(ema20_raw),
                ema50=float(ema50_raw),
                target_session=target_session,
                target_key=target_key,
                variant=variant,
            )
            if breakout is not None:
                key = (target_session, target_key, breakout.direction)
                if key not in seen:
                    output.append(breakout)
                    seen.add(key)

    output.sort(key=lambda signal: (signal.signal_index, signal.direction))
    return tuple(output)


def _final_oos_pass(metrics: TournamentMetrics) -> bool:
    return bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.win_rate is not None
        and metrics.win_rate >= FINAL_OOS_WIN_RATE_MIN
        and metrics.profit_factor is not None
        and metrics.profit_factor >= FINAL_OOS_PROFIT_FACTOR_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= FINAL_OOS_EXPECTANCY_R_MIN
    )


def evaluate_session_liquidity_v3(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    split_index = max(1000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]

    evaluations: list[dict[str, Any]] = []
    base_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    stress_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    signal_sets: dict[str, tuple[ContinuationSignal, ...]] = {}

    for variant in VARIANTS:
        signals = extract_session_signals(rows, variant=variant)
        base_trades = simulate_trades(rows, signals=signals, costs=costs)
        stressed_trades = simulate_trades(rows, signals=signals, costs=stressed_costs)
        signal_sets[variant.variant_id] = signals
        base_trade_sets[variant.variant_id] = base_trades
        stress_trade_sets[variant.variant_id] = stressed_trades

        development = tuple(
            trade for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade for trade in stressed_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(development)
        stressed_metrics = compute_metrics(development_stressed)

        signal_index = {
            (signal.signal_index, signal.direction): signal
            for signal in signals
        }

        def diagnostic_payload(trades):
            by_direction = {
                direction: compute_metrics(
                    tuple(trade for trade in trades if trade.direction == direction)
                ).payload()
                for direction in ("LONG", "SHORT")
            }
            by_setup_type = {}
            for setup_type in ("REVERSAL", "BREAKOUT_RETEST"):
                selected_trades = []
                for trade in trades:
                    signal = signal_index.get((trade.signal_index, trade.direction))
                    if signal is None:
                        continue
                    inferred = "REVERSAL" if signal.impulse_index == signal.retest_index else "BREAKOUT_RETEST"
                    if inferred == setup_type:
                        selected_trades.append(trade)
                by_setup_type[setup_type] = compute_metrics(tuple(selected_trades)).payload()

            by_session = {}
            by_session_direction = {}
            for session in (SESSION_ASIA, SESSION_EUROPE, SESSION_US):
                selected_trades = []
                for trade in trades:
                    signal = signal_index.get((trade.signal_index, trade.direction))
                    if signal is None:
                        continue
                    if _session_name(rows[signal.signal_index]) == session:
                        selected_trades.append(trade)
                by_session[session] = compute_metrics(tuple(selected_trades)).payload()
                for direction in ("LONG", "SHORT"):
                    directional = tuple(
                        trade for trade in selected_trades
                        if trade.direction == direction
                    )
                    by_session_direction[f"{session}_{direction}"] = compute_metrics(
                        directional
                    ).payload()
            return {
                "by_direction": by_direction,
                "by_setup_type": by_setup_type,
                "by_session": by_session,
                "by_session_direction": by_session_direction,
            }

        diagnostics = diagnostic_payload(development)
        stressed_diagnostics = diagnostic_payload(development_stressed)
        folds, pass_fraction, walk_forward_passed = walk_forward(
            development,
            validation_cfg["walk_forward"],
        )
        stress_passed = _metrics_pass(
            stressed_metrics,
            validation_cfg["stress_acceptance"],
        )
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and walk_forward_passed
            and stress_passed
        )
        development_signals = tuple(
            signal for signal in signals if signal.signal_index < split_index
        )
        evaluations.append(
            {
                "variant": asdict(variant),
                "development": metrics.payload(),
                "development_diagnostics": diagnostics,
                "stressed_development": stressed_metrics.payload(),
                "stressed_development_diagnostics": stressed_diagnostics,
                "walk_forward": {
                    "folds": [
                        {
                            "fold": fold.fold,
                            "train_trades": fold.train_trades,
                            "test_trades": fold.test_trades,
                            "passed": fold.passed,
                            "test_metrics": fold.test_metrics.payload(),
                        }
                        for fold in folds
                    ],
                    "pass_fraction": pass_fraction,
                    "passed": walk_forward_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "development_coverage": _daily_coverage(
                    development_rows,
                    development_signals,
                ),
            }
        )

    eligible = [
        row for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
            float(row["development"].get("expectancy_r") or -999.0),
            -float(row["development"].get("max_drawdown_r") or 999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    holdout: dict[str, Any] | None = None
    promotion_eligible = False
    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        holdout_base = tuple(
            trade for trade in base_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_stressed = tuple(
            trade for trade in stress_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        holdout_signals = tuple(
            signal for signal in signal_sets[variant_id]
            if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(holdout_metrics)
            and _metrics_pass(
                holdout_stress_metrics,
                validation_cfg["stress_acceptance"],
            )
        )
        holdout = {
            "variant_id": variant_id,
            "base": holdout_metrics.payload(),
            "stressed": holdout_stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "final_oos_thresholds": {
                "minimum_trades": MIN_HOLDOUT_TRADES,
                "win_rate_min": FINAL_OOS_WIN_RATE_MIN,
                "profit_factor_min": FINAL_OOS_PROFIT_FACTOR_MIN,
                "expectancy_r_min": FINAL_OOS_EXPECTANCY_R_MIN,
            },
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "history_bars": len(rows),
        "development_bars": len(development_rows),
        "holdout_bars": len(holdout_rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V3 preregisters session-liquidity sweep reversal and breakout-retest "
            "families before locked holdout access. Controls cannot enter selection."
        ),
    }
