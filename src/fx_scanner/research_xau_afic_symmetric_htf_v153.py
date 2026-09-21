from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    MAX_HOLD_BARS,
    VARIANTS as V18_VARIANTS,
    _cost_r,
    extract_signals,
)
from .research_xau_afic_htf_reconstruction_v152 import (
    AficVariant,
    _capital,
    _filter_trades,
    _period,
    _states,
)
from .research_xau_v134_h3_robustness_v135 import RECENT, START

UTC = timezone.utc
RESEARCH_VERSION = "XAU_AFIC_SYMMETRIC_HTF_V153"
ARTIFACT_CONTRACT = "XAU_AFIC_SYMMETRIC_HTF_V153_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

BASE_SIGNAL_VARIANT_ID = "V18_L12_ADX12_NOD1_R150"
LOOKBACK = 12
RETEST_BARS = 2
PIP_SIZE = 0.01

ERA_2012_2018_END = datetime(2019, 1, 1, tzinfo=UTC)
ERA_2019_2024_END = datetime(2025, 1, 1, tzinfo=UTC)

VARIANTS = (
    AficVariant("AFIC_V153_CONTROL", "NONE", "NONE", selection_eligible=False),
    AficVariant("AFIC_V153_D1_MATCH", "MATCH", "NONE"),
    AficVariant("AFIC_V153_H4_MATCH", "NONE", "MATCH"),
    AficVariant("AFIC_V153_D1_H4_MATCH", "MATCH", "MATCH"),
    AficVariant("AFIC_V153_D1_H4_NOT_OPPOSED", "NOT_OPPOSED", "NOT_OPPOSED"),
    AficVariant("AFIC_V153_D1_H4_MATCH_PD", "MATCH", "MATCH", require_h4_pd=True),
)


def _base_variant():
    matches = [x for x in V18_VARIANTS if x.variant_id == BASE_SIGNAL_VARIANT_ID]
    if len(matches) != 1:
        raise ValueError("AFIC_V153_BASE_VARIANT_MISSING")
    return matches[0]


def _metrics(trades) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _breakout_level(rows: Sequence[Bar], signal) -> float:
    i = int(signal.signal_index)
    prior = rows[i - LOOKBACK : i]
    if len(prior) != LOOKBACK:
        raise ValueError("AFIC_V153_BREAKOUT_LOOKBACK_SHORT")
    return (
        max(float(x.high) for x in prior)
        if signal.direction == "LONG"
        else min(float(x.low) for x in prior)
    )


def _retest_trades(rows: Sequence[Bar], *, costs, pip_size: float):
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    signals = extract_signals(bars, variant=_base_variant())
    output: list[TournamentTrade] = []
    fills = 0
    long_signals = sum(1 for x in signals if x.direction == "LONG")
    short_signals = sum(1 for x in signals if x.direction == "SHORT")

    for sig in signals:
        level = _breakout_level(bars, sig)
        fill_i = None
        for j in range(
            int(sig.signal_index) + 1,
            min(len(bars), int(sig.signal_index) + 1 + RETEST_BARS),
        ):
            if float(bars[j].low) <= level <= float(bars[j].high):
                fill_i = j
                break
        if fill_i is None:
            continue
        fills += 1
        entry = float(level)
        stop = float(sig.stop)
        risk = entry - stop if sig.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0:
            continue
        target = (
            entry + float(sig.reward_r) * risk
            if sig.direction == "LONG"
            else entry - float(sig.reward_r) * risk
        )
        risk_pips = risk / float(pip_size)
        if risk_pips <= 0:
            continue

        last_i = min(len(bars) - 1, fill_i + MAX_HOLD_BARS)
        trade = None
        for j in range(fill_i, last_i + 1):
            bar = bars[j]
            if sig.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            raw_target = target_hit
            if j == fill_i:
                target_hit = False
            held = j - fill_i
            cost = _cost_r(risk_pips=risk_pips, bars_held=held, costs=costs)
            if stop_hit:
                gross = -1.0
                trade = TournamentTrade(
                    sig.variant_id,
                    sig.symbol,
                    sig.direction,
                    sig.signal_at,
                    ensure_utc(bars[fill_i].timestamp),
                    ensure_utc(bar.timestamp),
                    sig.signal_index,
                    j,
                    entry,
                    stop,
                    sig.atr,
                    stop,
                    target,
                    gross,
                    cost,
                    gross - cost,
                    held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
                )
                break
            if target_hit:
                gross = float(sig.reward_r)
                trade = TournamentTrade(
                    sig.variant_id,
                    sig.symbol,
                    sig.direction,
                    sig.signal_at,
                    ensure_utc(bars[fill_i].timestamp),
                    ensure_utc(bar.timestamp),
                    sig.signal_index,
                    j,
                    entry,
                    target,
                    sig.atr,
                    stop,
                    target,
                    gross,
                    cost,
                    gross - cost,
                    held,
                    "TARGET_HIT",
                )
                break
        if trade is None:
            if last_i < fill_i + MAX_HOLD_BARS:
                continue
            bar = bars[last_i]
            exit_price = float(bar.close)
            gross = (
                (exit_price - entry) / risk
                if sig.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost = _cost_r(
                risk_pips=risk_pips,
                bars_held=MAX_HOLD_BARS,
                costs=costs,
            )
            trade = TournamentTrade(
                sig.variant_id,
                sig.symbol,
                sig.direction,
                sig.signal_at,
                ensure_utc(bars[fill_i].timestamp),
                ensure_utc(bar.timestamp),
                sig.signal_index,
                last_i,
                entry,
                exit_price,
                sig.atr,
                stop,
                target,
                gross,
                cost,
                gross - cost,
                MAX_HOLD_BARS,
                "TIME_EXIT",
            )
        output.append(trade)

    return tuple(output), {
        "raw_signals": len(signals),
        "raw_long_signals": long_signals,
        "raw_short_signals": short_signals,
        "raw_fills": fills,
        "raw_fill_rate": 0.0 if not signals else fills / len(signals),
    }


def _direction_metrics(trades):
    return {
        side: _metrics(tuple(x for x in trades if x.direction == side))
        for side in ("LONG", "SHORT")
    }


def evaluate_v153(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    costs,
    broker_spec,
    leverage_tiers,
    pip_size: float = PIP_SIZE,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("AFIC_V153_BARS_EMPTY")
    end = ensure_utc(evaluation_end)

    raw, fill_stats = _retest_trades(bars, costs=costs, pip_size=pip_size)
    raw = _period(raw, START, end)
    d1_states = _states(bars, "D1")
    h4_states = _states(bars, "H4")

    variants: dict[str, Any] = {}
    for variant in VARIANTS:
        trades, filter_counts = _filter_trades(
            raw,
            variant=variant,
            d1_states=d1_states,
            h4_states=h4_states,
        )
        era_a = _period(trades, START, ERA_2012_2018_END)
        era_b = _period(trades, ERA_2012_2018_END, ERA_2019_2024_END)
        era_c = _period(trades, ERA_2019_2024_END, end)
        recent = _period(trades, RECENT, end)
        variants[variant.variant_id] = {
            "variant": asdict(variant),
            "filter_counts": filter_counts,
            "full_metrics": _metrics(trades),
            "full_by_direction": _direction_metrics(trades),
            "era_2012_2018": _metrics(era_a),
            "era_2012_2018_by_direction": _direction_metrics(era_a),
            "era_2019_2024": _metrics(era_b),
            "era_2019_2024_by_direction": _direction_metrics(era_b),
            "era_2025_2026": _metrics(era_c),
            "era_2025_2026_by_direction": _direction_metrics(era_c),
            "recent_metrics": _metrics(recent),
            "live100": _capital(
                trades,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            ),
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "identity": "AFIC-inspired symmetric HTF hypothesis; not AFIC proprietary rules",
            "base_signal": BASE_SIGNAL_VARIANT_ID,
            "base_signal_d1_filter": False,
            "base_tactical_filter": "existing H1 EMA20/50 + DI/ADX alignment",
            "m15_trigger": "12-bar BOS/displacement",
            "entry": "prior breakout-level retest within two completed M15 bars",
            "stop": "existing structural local-six extreme + 0.15 ATR",
            "target": "1.5R",
            "htf_tests": [
                "D1 structure match",
                "H4 structure match",
                "D1+H4 structure match",
                "D1+H4 not opposed",
                "D1+H4 match plus H4 premium/discount",
            ],
            "causality": "completed HTF buckets only",
            "no_parameter_grid": True,
            "execution_authority": False,
        },
        "fill_stats": fill_stats,
        "base_trade_count": len(raw),
        "base_by_direction": _direction_metrics(raw),
        "variants": variants,
        "note": (
            "V153 repairs the V152 diagnostic limitation: V152 inherited a routed V143 stream "
            "that happened to contain only LONG trades. V153 removes that D1/router inheritance "
            "and uses a symmetric no-D1 M15/H1 base so SHORT and LONG HTF hypotheses are both testable."
        ),
    }
