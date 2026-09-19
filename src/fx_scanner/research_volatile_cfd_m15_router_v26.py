from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    BreakoutVariant,
    _frequency,
    _walk_forward,
    extract_signals,
    simulate,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "VOLATILE_CFD_M15_ROUTER_V26"
ARTIFACT_CONTRACT = "VOLATILE_CFD_M15_ROUTER_V26_EVIDENCE_1"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
DIAGNOSTIC_ONLY = True

SYMBOLS = ("XAUUSD", "XTIUSD", "BTCUSD", "ETHUSD", "SOLUSD")
DEVELOPMENT_FRACTION = 0.70

VARIANTS = (
    BreakoutVariant("V26_L8_ADX10_NOD1_R100", 8, 10.0, False, 1.00, 0.40, 2),
    BreakoutVariant("V26_L8_ADX10_NOD1_R125", 8, 10.0, False, 1.25, 0.45, 2),
    BreakoutVariant("V26_L12_ADX12_NOD1_R150", 12, 12.0, False, 1.50, 0.50, 3),
    BreakoutVariant("V26_L8_ADX12_D1_R125", 8, 12.0, True, 1.25, 0.45, 2),
    BreakoutVariant("V26_L12_ADX12_D1_R150", 12, 12.0, True, 1.50, 0.50, 3),
    BreakoutVariant("V26_L20_ADX15_D1_R200", 20, 15.0, True, 2.00, 0.55, 4),
)

DEV_MIN_TRADES = 200
DEV_PF_MIN = 1.05
DEV_EXPECTANCY_MIN = 0.02
DEV_WF_FRACTION_MIN = 0.50

HOLDOUT_MIN_TRADES = 60
HOLDOUT_PF_MIN = 1.10
HOLDOUT_EXPECTANCY_MIN = 0.05

FREQUENCY_TARGET = {
    "mean_trades_per_day_min": 5.0,
    "days_ge_5_fraction_min": 0.50,
}


def _dev_pass(metrics, wf: Mapping[str, Any]) -> bool:
    return bool(
        metrics.completed_trades >= DEV_MIN_TRADES
        and metrics.profit_factor is not None
        and metrics.profit_factor >= DEV_PF_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= DEV_EXPECTANCY_MIN
        and float(wf["pass_fraction"]) >= DEV_WF_FRACTION_MIN
    )


def _hold_pass(metrics) -> bool:
    return bool(
        metrics.completed_trades >= HOLDOUT_MIN_TRADES
        and metrics.profit_factor is not None
        and metrics.profit_factor >= HOLDOUT_PF_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= HOLDOUT_EXPECTANCY_MIN
    )


def _select(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [x for x in rows if x["development_passed"]]
    eligible.sort(
        key=lambda x: (
            float(x["walk_forward"]["pass_fraction"]),
            float(x["development_stressed"]["expectancy_r"]),
            float(x["development_stressed"]["profit_factor"]),
            int(x["development_stressed"]["completed_trades"]),
        ),
        reverse=True,
    )
    return eligible[0] if eligible else None


def evaluate_v26(
    datasets: Mapping[
        str,
        tuple[Sequence[Bar], float, M15ResearchCosts, M15ResearchCosts],
    ],
    *,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    symbol_results: dict[str, Any] = {}
    selected_holdout_base = []
    selected_holdout_stress = []
    all_holdout_dates = set()

    for symbol, (bars, pip_size, costs, stressed_costs) in datasets.items():
        values = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
        split = max(5_000, min(len(values) - 1, int(len(values) * DEVELOPMENT_FRACTION)))
        dev_dates = sorted({
            ensure_utc(x.timestamp).date()
            for x in values[220:split]
        })
        hold_dates = sorted({
            ensure_utc(x.timestamp).date()
            for x in values[split:]
        })
        all_holdout_dates.update(hold_dates)

        rows = []
        trade_sets = {}
        for variant in VARIANTS:
            signals = extract_signals(values, variant=variant)
            base = simulate(
                values,
                signals=signals,
                costs=costs,
                pip_size=pip_size,
            )
            stress = simulate(
                values,
                signals=signals,
                costs=stressed_costs,
                pip_size=pip_size,
            )
            dev_base = tuple(
                t for t in base
                if t.signal_index < split and t.exit_index < split
            )
            dev_stress = tuple(
                t for t in stress
                if t.signal_index < split and t.exit_index < split
            )
            hold_base = tuple(t for t in base if t.signal_index >= split)
            hold_stress = tuple(t for t in stress if t.signal_index >= split)

            dm = compute_metrics(dev_base)
            dms = compute_metrics(dev_stress)
            hm = compute_metrics(hold_base)
            hms = compute_metrics(hold_stress)
            wf = _walk_forward(dev_base, validation_cfg)
            dev_freq = _frequency(dev_base, dev_dates)
            hold_freq = _frequency(hold_base, hold_dates)

            row = {
                "variant": asdict(variant),
                "signals": len(signals),
                "development_base": dm.payload(),
                "development_stressed": dms.payload(),
                "development_frequency": dev_freq,
                "walk_forward": wf,
                "development_passed": _dev_pass(dms, wf),
                "holdout_base": hm.payload(),
                "holdout_stressed": hms.payload(),
                "holdout_frequency": hold_freq,
                "holdout_passed": _hold_pass(hms),
            }
            rows.append(row)
            trade_sets[variant.variant_id] = {
                "hold_base": hold_base,
                "hold_stress": hold_stress,
            }

        selected = _select(rows)
        selected_payload = None
        if selected is not None:
            vid = str(selected["variant"]["variant_id"])
            selected_holdout_base.extend(trade_sets[vid]["hold_base"])
            selected_holdout_stress.extend(trade_sets[vid]["hold_stress"])
            selected_payload = {
                "variant_id": vid,
                "development_stressed": selected["development_stressed"],
                "development_frequency": selected["development_frequency"],
                "walk_forward": selected["walk_forward"],
                "holdout_stressed": selected["holdout_stressed"],
                "holdout_frequency": selected["holdout_frequency"],
                "holdout_passed": selected["holdout_passed"],
            }

        symbol_results[symbol] = {
            "bars": len(values),
            "split_index": split,
            "variants": rows,
            "selected": selected_payload,
        }

    aggregate_base = compute_metrics(tuple(selected_holdout_base))
    aggregate_stress = compute_metrics(tuple(selected_holdout_stress))
    aggregate_freq = _frequency(
        tuple(selected_holdout_base),
        sorted(all_holdout_dates),
    )

    selected_symbols = [
        symbol for symbol, row in symbol_results.items()
        if row["selected"] is not None
    ]
    positive_symbols = [
        symbol for symbol, row in symbol_results.items()
        if row["selected"] is not None
        and bool(row["selected"]["holdout_passed"])
    ]
    breadth_pass = bool(
        len(selected_symbols) >= 2
        and len(positive_symbols) / max(1, len(selected_symbols)) >= 0.60
    )
    aggregate_quality_pass = bool(
        aggregate_stress.completed_trades >= 150
        and aggregate_stress.profit_factor is not None
        and aggregate_stress.profit_factor >= HOLDOUT_PF_MIN
        and aggregate_stress.expectancy_r is not None
        and aggregate_stress.expectancy_r >= HOLDOUT_EXPECTANCY_MIN
    )
    frequency_pass = bool(
        aggregate_freq["mean_trades_per_day"] >= FREQUENCY_TARGET["mean_trades_per_day_min"]
        and aggregate_freq["days_ge_5_fraction"] >= FREQUENCY_TARGET["days_ge_5_fraction_min"]
    )

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbols": list(datasets),
        "selection_contract": {
            "development_only": True,
            "development_fraction": DEVELOPMENT_FRACTION,
            "dev_min_trades": DEV_MIN_TRADES,
            "dev_pf_min": DEV_PF_MIN,
            "dev_expectancy_r_min": DEV_EXPECTANCY_MIN,
            "dev_wf_fraction_min": DEV_WF_FRACTION_MIN,
            "holdout_min_trades": HOLDOUT_MIN_TRADES,
            "holdout_pf_min": HOLDOUT_PF_MIN,
            "holdout_expectancy_r_min": HOLDOUT_EXPECTANCY_MIN,
        },
        "symbol_results": symbol_results,
        "selected_symbols": selected_symbols,
        "positive_holdout_symbols": positive_symbols,
        "aggregate_holdout_base": aggregate_base.payload(),
        "aggregate_holdout_stressed": aggregate_stress.payload(),
        "aggregate_holdout_frequency": aggregate_freq,
        "breadth_pass": breadth_pass,
        "aggregate_quality_pass": aggregate_quality_pass,
        "frequency_pass": frequency_pass,
        "five_per_day_target": FREQUENCY_TARGET,
        "forward_shadow_candidate": bool(
            breadth_pass and aggregate_quality_pass and frequency_pass
        ),
        "note": (
            "V26 tests volatile cTrader CFD instruments separately. Each symbol selects "
            "one preregistered M15 trend-breakout variant using development only. "
            "Historical families have already been partially exposed in prior research, "
            "therefore all results remain diagnostic-only."
        ),
    }
