from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import _cost_r
from .research_xau_afic_htf_reconstruction_v152 import (
    AficVariant,
    _capital,
    _filter_trades,
    _period,
    _states,
)
from .research_xau_m15_continuation_tournament import _indicator_series
from .research_xau_v134_h3_robustness_v135 import RECENT, START

UTC = timezone.utc
RESEARCH_VERSION = "XAU_AFIC_MITIGATION_STRUCTURE_V154"
ARTIFACT_CONTRACT = "XAU_AFIC_MITIGATION_STRUCTURE_V154_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

SWING_LOOKBACK = 2
ORIGIN_LOOKBACK = 8
RETEST_WINDOW = 32
BODY_ATR_MIN = 0.80
RANGE_ATR_MIN = 1.20
CLOSE_LOCATION_MIN = 0.70
STOP_BUFFER_ATR = 0.15
TARGET_R = 1.50
MAX_HOLD_BARS = 32
PIP_SIZE = 0.01

ERA_2012_2018_END = datetime(2019, 1, 1, tzinfo=UTC)
ERA_2019_2024_END = datetime(2025, 1, 1, tzinfo=UTC)

ENTRY_MODES = ("MID_LIMIT", "REJECTION_CLOSE")
HTF_VARIANTS = (
    AficVariant("NONE", "NONE", "NONE", selection_eligible=False),
    AficVariant("H4_MATCH", "NONE", "MATCH"),
    AficVariant("D1_H4_NOT_OPPOSED", "NOT_OPPOSED", "NOT_OPPOSED"),
    AficVariant("D1_H4_MATCH", "MATCH", "MATCH"),
)


@dataclass(frozen=True, slots=True)
class Pivot:
    pivot_index: int
    confirm_index: int
    price: float


@dataclass(frozen=True, slots=True)
class ZoneSetup:
    signal_index: int
    signal_at: Any
    direction: str
    atr: float
    zone_low: float
    zone_high: float
    protected_level: float
    stop: float


def _pivots(rows: Sequence[Bar], *, high: bool) -> tuple[Pivot, ...]:
    out: list[Pivot] = []
    k = SWING_LOOKBACK
    for i in range(k, len(rows) - k):
        value = float(rows[i].high if high else rows[i].low)
        hood = [
            float((x.high if high else x.low))
            for x in rows[i - k : i + k + 1]
        ]
        extreme = max(hood) if high else min(hood)
        if value == extreme and hood.count(value) == 1:
            out.append(Pivot(i, i + k, value))
    return tuple(out)


def _origin_zone(rows: Sequence[Bar], index: int, direction: str):
    start = max(0, index - ORIGIN_LOOKBACK)
    for j in range(index - 1, start - 1, -1):
        row = rows[j]
        bullish = float(row.close) > float(row.open)
        bearish = float(row.close) < float(row.open)
        if direction == "SHORT" and bullish:
            low = min(float(row.open), float(row.close))
            high = float(row.high)
            if high > low:
                return low, high, j
        if direction == "LONG" and bearish:
            low = float(row.low)
            high = max(float(row.open), float(row.close))
            if high > low:
                return low, high, j
    return None


def extract_setups(rows: Sequence[Bar]) -> tuple[ZoneSetup, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    indicators = _indicator_series(bars)
    highs = _pivots(bars, high=True)
    lows = _pivots(bars, high=False)

    hi_ptr = lo_ptr = 0
    recent_highs: deque[Pivot] = deque(maxlen=2)
    recent_lows: deque[Pivot] = deque(maxlen=2)
    output: list[ZoneSetup] = []

    for i in range(40, len(bars) - RETEST_WINDOW - MAX_HOLD_BARS - 2):
        known_at = i - 1
        while hi_ptr < len(highs) and highs[hi_ptr].confirm_index <= known_at:
            recent_highs.append(highs[hi_ptr])
            hi_ptr += 1
        while lo_ptr < len(lows) and lows[lo_ptr].confirm_index <= known_at:
            recent_lows.append(lows[lo_ptr])
            lo_ptr += 1
        if len(recent_highs) < 2 or len(recent_lows) < 2:
            continue

        atr_raw = indicators["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if not isfinite(atr) or atr <= 0:
            continue

        row = bars[i]
        prev = bars[i - 1]
        body = abs(float(row.close) - float(row.open))
        rng = float(row.high) - float(row.low)
        if rng <= 0 or body < BODY_ATR_MIN * atr or rng < RANGE_ATR_MIN * atr:
            continue

        bearish_structure = (
            recent_highs[-1].price < recent_highs[-2].price
            and recent_lows[-1].price < recent_lows[-2].price
        )
        bullish_structure = (
            recent_highs[-1].price > recent_highs[-2].price
            and recent_lows[-1].price > recent_lows[-2].price
        )
        close_short_location = (float(row.high) - float(row.close)) / rng
        close_long_location = (float(row.close) - float(row.low)) / rng

        direction = None
        protected = None
        if (
            bearish_structure
            and float(row.close) < recent_lows[-1].price
            and float(prev.close) >= recent_lows[-1].price
            and float(row.close) < float(row.open)
            and close_short_location >= CLOSE_LOCATION_MIN
        ):
            direction = "SHORT"
            protected = recent_highs[-1].price
        elif (
            bullish_structure
            and float(row.close) > recent_highs[-1].price
            and float(prev.close) <= recent_highs[-1].price
            and float(row.close) > float(row.open)
            and close_long_location >= CLOSE_LOCATION_MIN
        ):
            direction = "LONG"
            protected = recent_lows[-1].price
        if direction is None or protected is None:
            continue

        origin = _origin_zone(bars, i, direction)
        if origin is None:
            continue
        zone_low, zone_high, _ = origin
        if direction == "SHORT":
            stop = max(float(protected), float(zone_high)) + STOP_BUFFER_ATR * atr
            if stop <= float(row.close):
                continue
        else:
            stop = min(float(protected), float(zone_low)) - STOP_BUFFER_ATR * atr
            if stop >= float(row.close) or stop <= 0:
                continue

        output.append(
            ZoneSetup(
                signal_index=i,
                signal_at=ensure_utc(row.timestamp),
                direction=direction,
                atr=atr,
                zone_low=float(zone_low),
                zone_high=float(zone_high),
                protected_level=float(protected),
                stop=float(stop),
            )
        )
    return tuple(output)


def _simulate(
    rows: Sequence[Bar],
    setups: Sequence[ZoneSetup],
    *,
    mode: str,
    costs,
    pip_size: float,
):
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    out: list[TournamentTrade] = []
    touched = 0
    filled = 0

    for setup in setups:
        mid = 0.5 * (setup.zone_low + setup.zone_high)
        fill_i = None
        entry = None

        for j in range(
            setup.signal_index + 1,
            min(len(bars) - 1, setup.signal_index + 1 + RETEST_WINDOW),
        ):
            bar = bars[j]
            overlap = float(bar.low) <= setup.zone_high and float(bar.high) >= setup.zone_low
            if not overlap:
                continue
            touched += 1
            if mode == "MID_LIMIT":
                if float(bar.low) <= mid <= float(bar.high):
                    fill_i = j
                    entry = mid
                    break
            elif mode == "REJECTION_CLOSE":
                if setup.direction == "SHORT":
                    rejected = (
                        float(bar.high) >= setup.zone_low
                        and float(bar.close) < mid
                        and float(bar.close) < float(bar.open)
                    )
                else:
                    rejected = (
                        float(bar.low) <= setup.zone_high
                        and float(bar.close) > mid
                        and float(bar.close) > float(bar.open)
                    )
                if rejected:
                    fill_i = j + 1
                    entry = float(bars[fill_i].open)
                    break
            else:
                raise ValueError(f"AFIC_V154_ENTRY_MODE_INVALID:{mode}")

        if fill_i is None or entry is None or fill_i >= len(bars):
            continue
        filled += 1
        stop = float(setup.stop)
        risk = entry - stop if setup.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0:
            continue
        if risk < 0.50 * setup.atr:
            continue
        target = (
            entry + TARGET_R * risk
            if setup.direction == "LONG"
            else entry - TARGET_R * risk
        )
        if target <= 0:
            continue

        last_i = min(len(bars) - 1, fill_i + MAX_HOLD_BARS)
        trade = None
        for j in range(fill_i, last_i + 1):
            bar = bars[j]
            if setup.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            raw_target = target_hit
            if j == fill_i:
                target_hit = False
            held = j - fill_i
            cost = _cost_r(
                risk_pips=risk / float(pip_size),
                bars_held=held,
                costs=costs,
            )
            if stop_hit:
                gross = -1.0
                trade = TournamentTrade(
                    f"AFIC_V154_{mode}",
                    "XAUUSD",
                    setup.direction,
                    setup.signal_at,
                    ensure_utc(bars[fill_i].timestamp),
                    ensure_utc(bar.timestamp),
                    setup.signal_index,
                    j,
                    entry,
                    stop,
                    setup.atr,
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
                gross = TARGET_R
                trade = TournamentTrade(
                    f"AFIC_V154_{mode}",
                    "XAUUSD",
                    setup.direction,
                    setup.signal_at,
                    ensure_utc(bars[fill_i].timestamp),
                    ensure_utc(bar.timestamp),
                    setup.signal_index,
                    j,
                    entry,
                    target,
                    setup.atr,
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
                if setup.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost = _cost_r(
                risk_pips=risk / float(pip_size),
                bars_held=MAX_HOLD_BARS,
                costs=costs,
            )
            trade = TournamentTrade(
                f"AFIC_V154_{mode}",
                "XAUUSD",
                setup.direction,
                setup.signal_at,
                ensure_utc(bars[fill_i].timestamp),
                ensure_utc(bar.timestamp),
                setup.signal_index,
                last_i,
                entry,
                exit_price,
                setup.atr,
                stop,
                target,
                gross,
                cost,
                gross - cost,
                MAX_HOLD_BARS,
                "TIME_EXIT",
            )
        out.append(trade)

    return tuple(out), {
        "setups": len(setups),
        "touched_events": touched,
        "filled": filled,
        "completed": len(out),
    }


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _by_direction(trades):
    return {
        side: _metrics(tuple(x for x in trades if x.direction == side))
        for side in ("LONG", "SHORT")
    }


def evaluate_v154(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    costs,
    broker_spec,
    leverage_tiers,
    pip_size: float = PIP_SIZE,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    setups = extract_setups(bars)
    d1_states = _states(bars, "D1")
    h4_states = _states(bars, "H4")

    results: dict[str, Any] = {}
    for mode in ENTRY_MODES:
        raw, fill_stats = _simulate(
            bars,
            setups,
            mode=mode,
            costs=costs,
            pip_size=pip_size,
        )
        raw = _period(raw, START, end)
        for htf in HTF_VARIANTS:
            trades, filter_counts = _filter_trades(
                raw,
                variant=htf,
                d1_states=d1_states,
                h4_states=h4_states,
            )
            key = f"{mode}__{htf.variant_id}"
            era_a = _period(trades, START, ERA_2012_2018_END)
            era_b = _period(trades, ERA_2012_2018_END, ERA_2019_2024_END)
            era_c = _period(trades, ERA_2019_2024_END, end)
            recent = _period(trades, RECENT, end)
            results[key] = {
                "entry_mode": mode,
                "htf": asdict(htf),
                "fill_stats": fill_stats,
                "filter_counts": filter_counts,
                "full_metrics": _metrics(trades),
                "full_by_direction": _by_direction(trades),
                "era_2012_2018": _metrics(era_a),
                "era_2019_2024": _metrics(era_b),
                "era_2025_2026": _metrics(era_c),
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
            "identity": "AFIC-inspired M15 mitigation-zone reconstruction; not AFIC proprietary rules",
            "m15_structure": "confirmed 2-left/2-right LH+LL or HH+HL before a fresh BOS",
            "displacement": {
                "body_atr_min": BODY_ATR_MIN,
                "range_atr_min": RANGE_ATR_MIN,
                "close_location_min": CLOSE_LOCATION_MIN,
            },
            "zone": "last opposite candle within 8 M15 bars before displacement; supply=open-to-high, demand=low-to-open",
            "retest_window_m15_bars": RETEST_WINDOW,
            "entries": list(ENTRY_MODES),
            "stop": "protected M15 swing beyond zone + 0.15 ATR",
            "target_r": TARGET_R,
            "max_hold_bars": MAX_HOLD_BARS,
            "htf_filters": [x.variant_id for x in HTF_VARIANTS],
            "causality": "confirmed pivots and completed H4/D1 buckets only",
            "no_parameter_grid": True,
            "execution_authority": False,
        },
        "setup_count": len(setups),
        "setup_long": sum(1 for x in setups if x.direction == "LONG"),
        "setup_short": sum(1 for x in setups if x.direction == "SHORT"),
        "results": results,
        "note": (
            "V154 moves beyond V153's breakout-line retest. It reconstructs the screenshot's "
            "LH/LL -> bearish displacement/BOS -> return-to-supply idea symmetrically for LONG/SHORT."
        ),
    }
