from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import extract_signals as extract_m15_breakout, simulate as simulate_m15
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _period,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_HIERARCHICAL_REGIME_ROUTER_V35"
ARTIFACT_CONTRACT = "XAU_HIERARCHICAL_REGIME_ROUTER_V35_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGE = 100.0
MARGIN_FLOOR_PCT = 150.0

L12_ID = "V20_M15_L12_ADX12_D1_R150"
L20_ID = "V20_M15_L20_ADX15_D1_R200"

PRIMARY_VARIANTS = (
    "D1_CLASSIC_ONLY",
    "D1_CLASSIC_PLUS_UNRESTRICTED_L20",
    "D1_CLASSIC_PLUS_UNRESTRICTED_L12_L20",
    "D1_CLASSIC_PLUS_D1_GATE_L20",
    "D1_CLASSIC_PLUS_D1_GATE_L12_L20",
    "D1_CLASSIC_PLUS_D1_H1_SOFT",
    "D1_CLASSIC_PLUS_D1_H1_NORMAL",
    "D1_CLASSIC_PLUS_D1_H1_STRICT",
    "D1_CLASSIC_PLUS_STRONG_D1_H1_NORMAL",
    "D1_CLASSIC_PLUS_MATURITY_ROUTED_NORMAL",
    "D1_CLASSIC_PLUS_TRANSITION_EARLY_L12",
)


def _bars_frame(rows: Sequence[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [ensure_utc(x.timestamp) for x in rows],
            "open": [float(x.open) for x in rows],
            "high": [float(x.high) for x in rows],
            "low": [float(x.low) for x in rows],
            "close": [float(x.close) for x in rows],
        }
    ).sort_values("time").drop_duplicates("time").reset_index(drop=True)


def _wilder_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - prev).abs(),
            (frame["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _adx(frame: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = frame["high"].diff()
    down = -frame["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    atr = _wilder_atr(frame, period)
    plus_sm = plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    minus_sm = minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_sm / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_sm / atr.replace(0.0, np.nan)
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx, plus_di, minus_di


def _resample_completed(rows: Sequence[Bar], rule: str) -> pd.DataFrame:
    x = _bars_frame(rows).set_index("time")
    # label=right + closed=left means the timestamp is the END of the completed
    # bucket. An as-of lookup at signal time can therefore never use an
    # unfinished H1/D1 candle.
    out = x.resample(rule, label="right", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna().reset_index()
    return out


def build_d1_context(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = _resample_completed(rows, "1D")
    d1["atr14"] = _wilder_atr(d1, 14)
    d1["ema200"] = d1["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    d1["ret60"] = d1["close"] / d1["close"].shift(60) - 1.0
    d1["ema200_slope20"] = d1["ema200"] - d1["ema200"].shift(20)

    trend = np.where(d1["close"] > d1["ema200"], 1, np.where(d1["close"] < d1["ema200"], -1, 0))
    mom = np.where(d1["ret60"] > 0, 1, np.where(d1["ret60"] < 0, -1, 0))
    slope = np.where(d1["ema200_slope20"] > 0, 1, np.where(d1["ema200_slope20"] < 0, -1, 0))
    side = np.where((trend == 1) & (mom == 1), 1, np.where((trend == -1) & (mom == -1), -1, 0))

    regime = np.full(len(d1), "TRANSITION", dtype=object)
    regime[(side == 1) & (slope == 1)] = "STRONG_BULL"
    regime[(side == 1) & (slope != 1)] = "BULL"
    regime[(side == -1) & (slope == -1)] = "STRONG_BEAR"
    regime[(side == -1) & (slope != -1)] = "BEAR"

    run_lengths: list[int] = []
    opposite_transition: list[bool] = []
    current_side = 0
    run = 0
    last_nonzero = 0
    run_started_from_opposite = False
    for raw_side in side:
        s = int(raw_side)
        if s == 0:
            current_side = 0
            run = 0
            run_started_from_opposite = False
            run_lengths.append(0)
            opposite_transition.append(False)
            continue
        if s != current_side:
            run = 1
            run_started_from_opposite = bool(last_nonzero != 0 and last_nonzero != s)
            current_side = s
        else:
            run += 1
        run_lengths.append(run)
        opposite_transition.append(run_started_from_opposite)
        last_nonzero = s

    distance = (d1["close"] - d1["ema200"]).abs() / d1["atr14"].replace(0.0, np.nan)
    maturity: list[str] = []
    for s, run_len, dist in zip(side, run_lengths, distance):
        if int(s) == 0 or not np.isfinite(float(dist)):
            maturity.append("TRANSITION")
        elif float(dist) >= 3.0:
            maturity.append("EXTENDED")
        elif int(run_len) <= 10:
            maturity.append("EARLY")
        elif int(run_len) <= 60:
            maturity.append("ESTABLISHED")
        else:
            maturity.append("MATURE")

    d1["regime_side"] = side.astype(int)
    d1["regime"] = regime
    d1["days_in_regime"] = run_lengths
    d1["transition_from_opposite"] = opposite_transition
    d1["distance_ema200_atr"] = distance
    d1["maturity"] = maturity
    return d1


def build_h1_context(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = _resample_completed(rows, "1h")
    h1["ema20"] = h1["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    h1["ema50"] = h1["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    h1["ema200"] = h1["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    h1["ema20_slope5"] = h1["ema20"] - h1["ema20"].shift(5)
    adx, plus_di, minus_di = _adx(h1, 14)
    h1["adx14"] = adx
    h1["plus_di14"] = plus_di
    h1["minus_di14"] = minus_di
    return h1


class _Asof:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.reset_index(drop=True)
        self.times = [ensure_utc(x.to_pydatetime() if hasattr(x, "to_pydatetime") else x) for x in self.frame["time"]]

    def row(self, timestamp) -> Mapping[str, Any] | None:
        t = ensure_utc(timestamp)
        i = bisect_right(self.times, t) - 1
        if i < 0:
            return None
        return self.frame.iloc[i].to_dict()


def _family(strategy_id: str) -> str:
    if strategy_id == L12_ID:
        return "L12"
    if strategy_id == L20_ID:
        return "L20"
    return "OTHER"


def _trade_side(direction: str) -> int:
    return 1 if str(direction).upper() == "LONG" else -1


def annotate_m15(
    trades: Sequence[TournamentTrade],
    *,
    d1_context: pd.DataFrame,
    h1_context: pd.DataFrame,
) -> tuple[dict[str, Any], ...]:
    d1_lookup = _Asof(d1_context)
    h1_lookup = _Asof(h1_context)
    out: list[dict[str, Any]] = []

    for trade in trades:
        d1 = d1_lookup.row(trade.signal_at)
        h1 = h1_lookup.row(trade.signal_at)
        if d1 is None or h1 is None:
            continue

        side = _trade_side(trade.direction)
        d1_side = int(d1.get("regime_side") or 0)
        match = d1_side == side
        countertrend = d1_side == -side and d1_side != 0

        close = float(h1.get("close", np.nan))
        ema20 = float(h1.get("ema20", np.nan))
        ema50 = float(h1.get("ema50", np.nan))
        ema200 = float(h1.get("ema200", np.nan))
        slope5 = float(h1.get("ema20_slope5", np.nan))
        adx = float(h1.get("adx14", np.nan))
        plus_di = float(h1.get("plus_di14", np.nan))
        minus_di = float(h1.get("minus_di14", np.nan))

        valid_core = all(np.isfinite(v) for v in (close, ema20, ema50, ema200))
        h1_soft = bool(valid_core and ((side > 0 and close > ema200) or (side < 0 and close < ema200)))
        h1_normal = bool(
            h1_soft
            and ((side > 0 and ema20 > ema50) or (side < 0 and ema20 < ema50))
        )
        strict_numeric = all(np.isfinite(v) for v in (slope5, adx, plus_di, minus_di))
        h1_strict = bool(
            h1_normal
            and strict_numeric
            and adx >= 15.0
            and (
                (side > 0 and ema50 > ema200 and slope5 > 0 and plus_di > minus_di)
                or (side < 0 and ema50 < ema200 and slope5 < 0 and minus_di > plus_di)
            )
        )

        out.append(
            {
                "trade": trade,
                "family": _family(trade.strategy_id),
                "trade_side": side,
                "d1_side": d1_side,
                "d1_match": match,
                "countertrend": countertrend,
                "regime": str(d1.get("regime")),
                "maturity": str(d1.get("maturity")),
                "days_in_regime": int(d1.get("days_in_regime") or 0),
                "transition_from_opposite": bool(d1.get("transition_from_opposite")),
                "distance_ema200_atr": float(d1.get("distance_ema200_atr", np.nan)),
                "h1_soft": h1_soft,
                "h1_normal": h1_normal,
                "h1_strict": h1_strict,
                "h1_adx14": adx,
            }
        )
    return tuple(out)


def _select(annotated: Sequence[Mapping[str, Any]], variant: str) -> tuple[TournamentTrade, ...]:
    chosen: list[TournamentTrade] = []
    for row in annotated:
        family = str(row["family"])
        match = bool(row["d1_match"])
        maturity = str(row["maturity"])
        regime = str(row["regime"])

        keep = False
        if variant == "UNRESTRICTED_L20":
            keep = family == "L20"
        elif variant == "UNRESTRICTED_L12_L20":
            keep = family in {"L12", "L20"}
        elif variant == "D1_GATE_L20":
            keep = match and family == "L20"
        elif variant == "D1_GATE_L12_L20":
            keep = match and family in {"L12", "L20"}
        elif variant == "D1_H1_SOFT":
            keep = match and bool(row["h1_soft"]) and family in {"L12", "L20"}
        elif variant == "D1_H1_NORMAL":
            keep = match and bool(row["h1_normal"]) and family in {"L12", "L20"}
        elif variant == "D1_H1_STRICT":
            keep = match and bool(row["h1_strict"]) and family in {"L12", "L20"}
        elif variant == "STRONG_D1_H1_NORMAL":
            keep = match and regime in {"STRONG_BULL", "STRONG_BEAR"} and bool(row["h1_normal"]) and family in {"L12", "L20"}
        elif variant == "MATURITY_ROUTED_NORMAL":
            keep = (
                match
                and bool(row["h1_normal"])
                and (
                    (maturity == "EARLY" and family in {"L12", "L20"})
                    or (maturity in {"ESTABLISHED", "MATURE"} and family == "L20")
                )
            )
        elif variant == "TRANSITION_EARLY_L12":
            keep = (
                match
                and bool(row["h1_normal"])
                and family == "L12"
                and maturity == "EARLY"
                and bool(row["transition_from_opposite"])
                and int(row["days_in_regime"]) <= 10
            )
        else:
            raise ValueError(f"V35_UNKNOWN_ROUTE:{variant}")

        if keep:
            chosen.append(row["trade"])
    return tuple(chosen)


def _countertrend_subset(annotated: Sequence[Mapping[str, Any]]) -> tuple[TournamentTrade, ...]:
    # One bounded diagnostic only: countertrend is considered only when D1 is
    # extended, while H1 gives strict opposite-direction tactical alignment.
    return tuple(
        row["trade"]
        for row in annotated
        if bool(row["countertrend"])
        and str(row["maturity"]) == "EXTENDED"
        and bool(row["h1_strict"])
        and str(row["family"]) in {"L12", "L20"}
    )


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _max_losing_streak(trades: Sequence[TournamentTrade]) -> int:
    streak = 0
    maximum = 0
    for trade in sorted(trades, key=lambda x: (ensure_utc(x.exit_at), ensure_utc(x.entry_at))):
        if float(trade.net_r) < 0.0:
            streak += 1
            maximum = max(maximum, streak)
        else:
            streak = 0
    return int(maximum)


def _trade_stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
    }


def _cross_breakdown(
    annotated: Sequence[Mapping[str, Any]],
    *,
    first: str,
    second: str,
    trading_days: int,
) -> dict[str, Any]:
    keys = sorted({(str(row[first]), str(row[second])) for row in annotated})
    return {
        f"{a}|{b}": _trade_stats(
            tuple(
                row["trade"]
                for row in annotated
                if str(row[first]) == a and str(row[second]) == b
            ),
            trading_days,
        )
        for a, b in keys
    }


def _breakdown(annotated: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    values = sorted({str(row[key]) for row in annotated})
    return {
        value: _metrics(tuple(row["trade"] for row in annotated if str(row[key]) == value))
        for value in values
    }


def _direction_metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return {
        "long": _metrics(tuple(x for x in trades if str(x.direction).upper() == "LONG")),
        "short": _metrics(tuple(x for x in trades if str(x.direction).upper() == "SHORT")),
    }


def evaluate_v35(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V35_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_d1_context(rows)
    h1_context = build_h1_context(rows)

    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in M15_VARIANTS
    }
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic_all = _simulate_d1_classic(rows, costs=costs, pip_size=pip_size)
        classic = _period(classic_all, start=start, end=end)

        m15_all: list[TournamentTrade] = []
        for variant in M15_VARIANTS:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        annotated = annotate_m15(m15, d1_context=d1_context, h1_context=h1_context)

        routed = {
            "UNRESTRICTED_L20": _select(annotated, "UNRESTRICTED_L20"),
            "UNRESTRICTED_L12_L20": _select(annotated, "UNRESTRICTED_L12_L20"),
            "D1_GATE_L20": _select(annotated, "D1_GATE_L20"),
            "D1_GATE_L12_L20": _select(annotated, "D1_GATE_L12_L20"),
            "D1_H1_SOFT": _select(annotated, "D1_H1_SOFT"),
            "D1_H1_NORMAL": _select(annotated, "D1_H1_NORMAL"),
            "D1_H1_STRICT": _select(annotated, "D1_H1_STRICT"),
            "STRONG_D1_H1_NORMAL": _select(annotated, "STRONG_D1_H1_NORMAL"),
            "MATURITY_ROUTED_NORMAL": _select(annotated, "MATURITY_ROUTED_NORMAL"),
            "TRANSITION_EARLY_L12": _select(annotated, "TRANSITION_EARLY_L12"),
        }

        portfolios: dict[str, tuple[TournamentTrade, ...]] = {
            "D1_CLASSIC_ONLY": tuple(classic),
        }
        for route_id, selected in routed.items():
            portfolios[f"D1_CLASSIC_PLUS_{route_id}"] = _limit_concurrency(
                _dedupe_with_classic((*classic, *selected))
            )

        portfolio_payload: dict[str, Any] = {}
        for portfolio_id, trades in portfolios.items():
            payload = {
                "available_trades": len(trades),
                "trading_days": trading_days,
                "trades_per_day": 0.0 if trading_days <= 0 else len(trades) / float(trading_days),
                "max_losing_streak": _max_losing_streak(trades),
                "metrics": _metrics(trades),
                "direction_metrics": _direction_metrics(trades),
            }
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    trades,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolio_payload[portfolio_id] = payload

        counter = _countertrend_subset(annotated)
        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "m15_raw_trades": len(m15),
            "m15_context_annotated": len(annotated),
            "portfolio_results": portfolio_payload,
            "routed_m15_metrics": {
                key: {
                    **_trade_stats(value, trading_days),
                    "direction_metrics": _direction_metrics(value),
                }
                for key, value in routed.items()
            },
            "diagnostics": {
                "all_m15_by_family": _breakdown(annotated, "family"),
                "d1_matched_by_regime": _breakdown(tuple(x for x in annotated if bool(x["d1_match"])), "regime"),
                "d1_matched_by_maturity": _breakdown(tuple(x for x in annotated if bool(x["d1_match"])), "maturity"),
                "d1_matched_family_x_maturity": _cross_breakdown(
                    tuple(x for x in annotated if bool(x["d1_match"])),
                    first="family",
                    second="maturity",
                    trading_days=trading_days,
                ),
                "d1_matched_family_x_h1_permission": {
                    "SOFT": _cross_breakdown(
                        tuple(x for x in annotated if bool(x["d1_match"]) and bool(x["h1_soft"])),
                        first="family",
                        second="regime",
                        trading_days=trading_days,
                    ),
                    "NORMAL": _cross_breakdown(
                        tuple(x for x in annotated if bool(x["d1_match"]) and bool(x["h1_normal"])),
                        first="family",
                        second="regime",
                        trading_days=trading_days,
                    ),
                    "STRICT": _cross_breakdown(
                        tuple(x for x in annotated if bool(x["d1_match"]) and bool(x["h1_strict"])),
                        first="family",
                        second="regime",
                        trading_days=trading_days,
                    ),
                },
                "countertrend_extended_h1_strict": {
                    "trades": len(counter),
                    "metrics": _metrics(counter),
                },
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
        "history_rows": len(rows),
        "trading_days": trading_days,
        "history_start": ensure_utc(rows[0].timestamp).isoformat(),
        "history_end": ensure_utc(rows[-1].timestamp).isoformat(),
        "causal_contract": {
            "d1_and_h1_use_completed_bars_only": True,
            "context_lookup_uses_signal_at": True,
            "d1_direction_rule": "close_vs_ema200 AND ret60_sign; ema200_slope20 upgrades to STRONG",
            "trend_maturity": {
                "EARLY": "days_in_regime<=10 and distance<3ATR",
                "ESTABLISHED": "11..60 days and distance<3ATR",
                "MATURE": ">60 days and distance<3ATR",
                "EXTENDED": "abs(close-ema200)/ATR14>=3",
            },
            "h1_soft": "close on directional side of EMA200",
            "h1_normal": "SOFT plus EMA20/EMA50 directional alignment",
            "h1_strict": "NORMAL plus EMA50/EMA200 stack, EMA20 slope5, ADX>=15, DI alignment",
            "selection_uses_future_outcomes": False,
        },
        "primary_variants": list(PRIMARY_VARIANTS),
        "cost_scenarios": list(cost_scenarios),
        "scenario_results": scenario_results,
        "interpretation_contract": (
            "V35 tests routing/context only. Frozen V20 L12/L20 entry rules and V31 D1 CLASSIC "
            "remain unchanged. No route becomes production authority from historical evidence alone."
        ),
    }
