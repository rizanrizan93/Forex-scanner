from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_fx_cross_sectional_strength_v28 import (
    FX_SYMBOLS,
    PAIR_META,
    MIN_PAIR_COVERAGE,
    MAX_ACCOUNT_POSITIONS,
    _atr_series,
    _cap_account,
    _frequency,
    _normalized_momentum,
    _stability,
    _strength_snapshot,
    simulate_symbol,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "FX_CROSS_SECTIONAL_REVERSION_H1_V29"
ARTIFACT_CONTRACT = "FX_CROSS_SECTIONAL_REVERSION_H1_V29_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True
DEVELOPMENT_FRACTION = 0.70
FREQUENCY_TARGET = 5.0
EMA_PERIOD = 20


@dataclass(frozen=True, slots=True)
class ReversionVariant:
    variant_id: str
    momentum_hours: int
    edge_min: float
    stretch_atr: float
    top_k_per_hour: int
    require_rejection_bar: bool
    stop_atr: float
    target_r: float
    max_hold_hours: int
    cooldown_hours: int


VARIANTS = (
    ReversionVariant("V29_H12_E35_S075_K3_R100",12,35.0,0.75,3,False,1.00,1.00,6,3),
    ReversionVariant("V29_H12_E45_S100_K2_REJ_R125",12,45.0,1.00,2,True,1.00,1.25,8,4),
    ReversionVariant("V29_H24_E35_S075_K3_REJ_R100",24,35.0,0.75,3,True,1.00,1.00,8,4),
    ReversionVariant("V29_H24_E45_S100_K2_REJ_R125",24,45.0,1.00,2,True,1.10,1.25,8,4),
    ReversionVariant("V29_H48_E35_S100_K2_REJ_R125",48,35.0,1.00,2,True,1.10,1.25,12,6),
    ReversionVariant("V29_H48_E50_S125_K2_REJ_R150",48,50.0,1.25,2,True,1.25,1.50,12,6),
)


@dataclass(frozen=True, slots=True)
class ReversionSignal:
    variant_id: str
    symbol: str
    direction: str
    signal_index: int
    signal_at: Any
    edge: float
    atr: float


def _ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(x) for x in values[:period]) / period
    out: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (period + 1.0)
    prev = seed
    for value in values[period:]:
        prev = alpha * float(value) + (1.0 - alpha) * prev
        out.append(prev)
    return tuple(out)


def extract_reversion_signals(
    datasets: Mapping[str, Sequence[Bar]],
    *,
    variant: ReversionVariant,
) -> tuple[ReversionSignal, ...]:
    rows = {
        symbol: tuple(sorted(values, key=lambda x: ensure_utc(x.timestamp)))
        for symbol, values in datasets.items()
        if symbol in PAIR_META
    }
    index_by_time = {}
    momentum = {}
    atrs = {}
    emas = {}
    timeline = set()

    for symbol, values in rows.items():
        index_by_time[symbol] = {ensure_utc(row.timestamp):i for i,row in enumerate(values)}
        timeline.update(index_by_time[symbol])
        momentum[symbol] = _normalized_momentum(values, variant.momentum_hours)
        atrs[symbol] = _atr_series(values)
        emas[symbol] = _ema([float(x.close) for x in values], EMA_PERIOD)

    last_signal_time = {}
    output = []

    for stamp in sorted(timeline):
        pair_scores = {}
        current = {}
        for symbol, values in rows.items():
            i = index_by_time[symbol].get(stamp)
            if i is None:
                continue
            current[symbol] = i
            score = momentum[symbol][i]
            if score is not None:
                pair_scores[symbol] = float(score)
        if len(pair_scores) < 12:
            continue

        strengths = _strength_snapshot(pair_scores)
        candidates = []
        for symbol, i in current.items():
            base, quote = PAIR_META[symbol]
            b = strengths.get(base); q = strengths.get(quote)
            if b is None or q is None or min(b[1],q[1]) < MIN_PAIR_COVERAGE:
                continue
            edge = max(-100.0, min(100.0, (b[0]-q[0])/2.0))
            if abs(edge) < variant.edge_min:
                continue
            atr = atrs[symbol][i]
            ema = emas[symbol][i]
            if atr is None or ema is None or not isfinite(float(atr)) or float(atr) <= 0:
                continue

            bar = rows[symbol][i]
            close = float(bar.close)
            stretch = (close - float(ema)) / float(atr)
            if edge > 0:
                # Cross-sectional strength has become stretched upward: fade only
                # after price is materially above its own H1 EMA20.
                if stretch < variant.stretch_atr:
                    continue
                direction = "SHORT"
                if variant.require_rejection_bar and not (float(bar.close) < float(bar.open)):
                    continue
            else:
                if stretch > -variant.stretch_atr:
                    continue
                direction = "LONG"
                if variant.require_rejection_bar and not (float(bar.close) > float(bar.open)):
                    continue

            last = last_signal_time.get(symbol)
            if last is not None and (stamp-last).total_seconds() < variant.cooldown_hours*3600:
                continue
            candidates.append((abs(edge), abs(stretch), symbol, direction, i, edge, float(atr)))

        candidates.sort(key=lambda x:(-x[0],-x[1],x[2]))
        used_ccy=set(); chosen=0
        for _,_,symbol,direction,i,edge,atr in candidates:
            base,quote=PAIR_META[symbol]
            if base in used_ccy or quote in used_ccy:
                continue
            output.append(ReversionSignal(
                variant_id=variant.variant_id,
                symbol=symbol,
                direction=direction,
                signal_index=i,
                signal_at=stamp,
                edge=float(edge),
                atr=atr,
            ))
            last_signal_time[symbol]=stamp
            used_ccy.update((base,quote))
            chosen+=1
            if chosen>=variant.top_k_per_hour:
                break
    return tuple(output)


def evaluate_v29(
    datasets: Mapping[str, Sequence[Bar]],
    *,
    pip_sizes: Mapping[str,float],
    base_costs: Mapping[str,M15ResearchCosts],
    stressed_costs: Mapping[str,M15ResearchCosts],
) -> dict[str,Any]:
    all_times=sorted({ensure_utc(x.timestamp) for values in datasets.values() for x in values})
    split_time=all_times[int(len(all_times)*DEVELOPMENT_FRACTION)]
    dev_dates=sorted({x.date() for x in all_times if x<split_time})
    hold_dates=sorted({x.date() for x in all_times if x>=split_time})
    evaluations=[]

    for variant in VARIANTS:
        signals=extract_reversion_signals(datasets,variant=variant)
        by_symbol={}
        for s in signals:
            by_symbol.setdefault(s.symbol,[]).append(s)

        base_all=[]; stress_all=[]
        for symbol,sigs in by_symbol.items():
            base_all.extend(simulate_symbol(
                datasets[symbol],signals=sigs,variant=variant,
                pip_size=pip_sizes[symbol],costs=base_costs[symbol],
            ))
            stress_all.extend(simulate_symbol(
                datasets[symbol],signals=sigs,variant=variant,
                pip_size=pip_sizes[symbol],costs=stressed_costs[symbol],
            ))
        base_all=_cap_account(base_all)
        stress_all=_cap_account(stress_all)

        dev_base=tuple(t for t in base_all if ensure_utc(t.entry_at)<split_time and ensure_utc(t.exit_at)<split_time)
        dev_stress=tuple(t for t in stress_all if ensure_utc(t.entry_at)<split_time and ensure_utc(t.exit_at)<split_time)
        hold_base=tuple(t for t in base_all if ensure_utc(t.entry_at)>=split_time)
        hold_stress=tuple(t for t in stress_all if ensure_utc(t.entry_at)>=split_time)

        dm=compute_metrics(dev_base); dms=compute_metrics(dev_stress)
        hm=compute_metrics(hold_base); hms=compute_metrics(hold_stress)
        stability=_stability(dev_stress)
        df=_frequency(dev_base,dev_dates); hf=_frequency(hold_base,hold_dates)
        passed=bool(
            dms.completed_trades>=400
            and dms.profit_factor is not None and dms.profit_factor>=1.05
            and dms.expectancy_r is not None and dms.expectancy_r>=0.02
            and stability["positive_fraction"]>=2/3
        )
        evaluations.append({
            "variant":asdict(variant),
            "signals":len(signals),
            "development_base":dm.payload(),
            "development_stressed":dms.payload(),
            "development_frequency":df,
            "stability":stability,
            "development_passed":passed,
            "holdout_base":hm.payload(),
            "holdout_stressed":hms.payload(),
            "holdout_frequency":hf,
        })

    eligible=[x for x in evaluations if x["development_passed"]]
    eligible.sort(key=lambda x:(
        float(x["stability"]["positive_fraction"]),
        float(x["development_stressed"]["expectancy_r"]),
        float(x["development_stressed"]["profit_factor"]),
        float(x["development_frequency"]["mean_trades_per_day"]),
    ),reverse=True)
    selected=eligible[0] if eligible else None
    holdout_pass=False
    if selected is not None:
        h=selected["holdout_stressed"]; f=selected["holdout_frequency"]
        holdout_pass=bool(
            h["completed_trades"]>=200
            and h["profit_factor"] is not None and h["profit_factor"]>=1.10
            and h["expectancy_r"] is not None and h["expectancy_r"]>=0.05
            and f["mean_trades_per_day"]>=FREQUENCY_TARGET
            and f["days_ge_5_fraction"]>=0.50
        )

    return {
        "research_version":RESEARCH_VERSION,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "live_execution_enabled":False,
        "diagnostic_only":DIAGNOSTIC_ONLY,
        "promotion_eligible":False,
        "xau_untouched":True,
        "symbols":sorted(datasets),
        "split_time":str(split_time),
        "variants":evaluations,
        "selected_variant":None if selected is None else selected["variant"]["variant_id"],
        "holdout_pass":holdout_pass,
        "forward_shadow_candidate":bool(holdout_pass),
        "frequency_target_mean_trades_per_day":FREQUENCY_TARGET,
        "note":(
            "V29 is the bounded contrarian follow-up to failed V28 momentum. "
            "It fades only extreme cross-sectional strength when the traded pair "
            "is stretched from EMA20; XAU D1+M15 remains untouched."
        ),
    }
