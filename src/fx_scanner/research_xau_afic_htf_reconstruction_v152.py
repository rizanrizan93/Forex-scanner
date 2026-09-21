from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_xau_v134_h3_robustness_v135 import START, RECENT
from .research_xau_v142_retest_entry_v143 import _capital, _h3_retest

UTC = timezone.utc
RESEARCH_VERSION = "XAU_AFIC_HTF_RECONSTRUCTION_V152"
ARTIFACT_CONTRACT = "XAU_AFIC_HTF_RECONSTRUCTION_V152_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

BASE_ENTRY_MODE = "BREAKOUT_LEVEL_RETEST_2BAR"
STATE_WINDOW = 80
SWING_LOOKBACK = 2
H4_PD_LOOKBACK = 20

ERA_2012_2018_END = datetime(2019, 1, 1, tzinfo=UTC)
ERA_2019_2024_END = datetime(2025, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AficVariant:
    variant_id: str
    d1_mode: str
    h4_mode: str
    require_h4_pd: bool = False
    selection_eligible: bool = True


VARIANTS = (
    AficVariant("AFIC_V152_CONTROL", "NONE", "NONE", selection_eligible=False),
    AficVariant("AFIC_V152_D1_MATCH", "MATCH", "NONE"),
    AficVariant("AFIC_V152_H4_MATCH", "NONE", "MATCH"),
    AficVariant("AFIC_V152_D1_H4_MATCH", "MATCH", "MATCH"),
    AficVariant("AFIC_V152_D1_H4_NOT_OPPOSED", "NOT_OPPOSED", "NOT_OPPOSED"),
    AficVariant("AFIC_V152_D1_H4_MATCH_PD", "MATCH", "MATCH", require_h4_pd=True),
)


@dataclass(frozen=True, slots=True)
class HtfState:
    close_at: datetime
    direction: str | None
    trend: str
    bos: str | None
    mss: str | None
    swing_high: float | None
    swing_low: float | None
    pd_mid: float | None


def _validate_rows(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        raise ValueError("AFIC_V152_BARS_EMPTY")
    if any(str(x.symbol).upper() != "XAUUSD" or str(x.timeframe).upper() != "M15" for x in bars):
        raise ValueError("AFIC_V152_REQUIRES_XAUUSD_M15")
    return bars


def _aggregate(rows: Sequence[Bar], timeframe: str) -> tuple[Bar, ...]:
    tf = str(timeframe).upper()
    if tf not in {"H4", "D1"}:
        raise ValueError(f"AFIC_V152_HTF_INVALID:{tf}")
    buckets: dict[datetime, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        if tf == "H4":
            bucket = stamp.replace(hour=(stamp.hour // 4) * 4, minute=0, second=0, microsecond=0)
        else:
            bucket = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)
    output: list[Bar] = []
    duration = timedelta(hours=4) if tf == "H4" else timedelta(days=1)
    for bucket in sorted(buckets):
        group = sorted(buckets[bucket], key=lambda x: ensure_utc(x.timestamp))
        if not group:
            continue
        output.append(
            Bar(
                symbol="XAUUSD",
                timeframe=tf,
                timestamp=bucket,
                open=float(group[0].open),
                high=max(float(x.high) for x in group),
                low=min(float(x.low) for x in group),
                close=float(group[-1].close),
                tick_count=sum(int(x.tick_count) for x in group),
                spread_avg=sum(float(x.spread_avg) for x in group) / len(group),
                spread_max=max(float(x.spread_max) for x in group),
            )
        )
    return tuple(output)


def _pivot_highs(bars: Sequence[Bar], lookback: int = SWING_LOOKBACK) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i in range(lookback, len(bars) - lookback):
        value = float(bars[i].high)
        hood = [float(x.high) for x in bars[i - lookback : i + lookback + 1]]
        if value == max(hood) and hood.count(value) == 1:
            out.append((i, value))
    return out


def _pivot_lows(bars: Sequence[Bar], lookback: int = SWING_LOOKBACK) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i in range(lookback, len(bars) - lookback):
        value = float(bars[i].low)
        hood = [float(x.low) for x in bars[i - lookback : i + lookback + 1]]
        if value == min(hood) and hood.count(value) == 1:
            out.append((i, value))
    return out


def _snapshot(window: Sequence[Bar]) -> tuple[str, str | None, str | None, float | None, float | None]:
    highs = _pivot_highs(window)
    lows = _pivot_lows(window)
    last_high = highs[-1][1] if highs else None
    last_low = lows[-1][1] if lows else None
    close = float(window[-1].close)

    bos: str | None = None
    if last_high is not None and close > last_high:
        bos = "BULLISH"
    elif last_low is not None and close < last_low:
        bos = "BEARISH"

    trend = "UNKNOWN"
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1] > lows[-2][1]
        lh = highs[-1][1] < highs[-2][1]
        ll = lows[-1][1] < lows[-2][1]
        if hh and hl:
            trend = "BULLISH"
        elif lh and ll:
            trend = "BEARISH"
        else:
            trend = "RANGE"

    mss: str | None = None
    if trend == "BEARISH" and bos == "BULLISH":
        mss = "BULLISH"
    elif trend == "BULLISH" and bos == "BEARISH":
        mss = "BEARISH"
    return trend, bos, mss, last_high, last_low


def _direction(trend: str, bos: str | None, mss: str | None) -> str | None:
    if mss in {"BULLISH", "BEARISH"}:
        return mss
    if bos in {"BULLISH", "BEARISH"}:
        return bos
    if trend in {"BULLISH", "BEARISH"}:
        return trend
    return None


def _states(rows: Sequence[Bar], timeframe: str) -> tuple[HtfState, ...]:
    bars = _aggregate(rows, timeframe)
    duration = timedelta(hours=4) if timeframe.upper() == "H4" else timedelta(days=1)
    output: list[HtfState] = []
    for i in range(len(bars)):
        start = max(0, i - STATE_WINDOW + 1)
        window = bars[start : i + 1]
        if len(window) < 7:
            trend, bos, mss, high, low = "UNKNOWN", None, None, None, None
        else:
            trend, bos, mss, high, low = _snapshot(window)
        pd_start = max(0, i - H4_PD_LOOKBACK + 1)
        pd_window = bars[pd_start : i + 1]
        pd_mid = None
        if pd_window:
            hi = max(float(x.high) for x in pd_window)
            lo = min(float(x.low) for x in pd_window)
            pd_mid = (hi + lo) / 2.0 if hi > lo else None
        output.append(
            HtfState(
                close_at=ensure_utc(bars[i].timestamp) + duration,
                direction=_direction(trend, bos, mss),
                trend=trend,
                bos=bos,
                mss=mss,
                swing_high=high,
                swing_low=low,
                pd_mid=pd_mid,
            )
        )
    return tuple(output)


def _state_at(states: Sequence[HtfState], closes: Sequence[datetime], stamp: datetime) -> HtfState | None:
    n = bisect_right(closes, ensure_utc(stamp))
    return states[n - 1] if n > 0 else None


def _match(mode: str, state: HtfState | None, trade_direction: str) -> bool:
    value = str(mode).upper()
    if value == "NONE":
        return True
    if state is None:
        return False
    wanted = "BULLISH" if trade_direction == "LONG" else "BEARISH"
    opposite = "BEARISH" if wanted == "BULLISH" else "BULLISH"
    if value == "MATCH":
        return state.direction == wanted
    if value == "NOT_OPPOSED":
        return state.direction != opposite
    raise ValueError(f"AFIC_V152_MODE_INVALID:{value}")


def _pd_ok(state: HtfState | None, trade_direction: str, entry_price: float) -> bool:
    if state is None or state.pd_mid is None:
        return False
    if trade_direction == "SHORT":
        return float(entry_price) >= float(state.pd_mid)
    return float(entry_price) <= float(state.pd_mid)


def _period(trades, start: datetime, end: datetime):
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _filter_trades(trades, *, variant: AficVariant, d1_states, h4_states):
    d1_closes = tuple(x.close_at for x in d1_states)
    h4_closes = tuple(x.close_at for x in h4_states)
    kept = []
    counts = {
        "considered": 0,
        "passed": 0,
        "d1_rejected": 0,
        "h4_rejected": 0,
        "pd_rejected": 0,
        "long_passed": 0,
        "short_passed": 0,
    }
    for trade in trades:
        counts["considered"] += 1
        stamp = ensure_utc(trade.signal_at)
        d1 = _state_at(d1_states, d1_closes, stamp)
        h4 = _state_at(h4_states, h4_closes, stamp)
        if not _match(variant.d1_mode, d1, trade.direction):
            counts["d1_rejected"] += 1
            continue
        if not _match(variant.h4_mode, h4, trade.direction):
            counts["h4_rejected"] += 1
            continue
        if variant.require_h4_pd and not _pd_ok(h4, trade.direction, float(trade.entry_price)):
            counts["pd_rejected"] += 1
            continue
        kept.append(trade)
        counts["passed"] += 1
        counts["long_passed" if trade.direction == "LONG" else "short_passed"] += 1
    return tuple(kept), counts


def evaluate_v152(
    rows: Sequence[Bar],
    *,
    evaluation_end: datetime,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    bars = _validate_rows(rows)
    end = ensure_utc(evaluation_end)
    base_trades, fill_stats = _h3_retest(
        bars,
        mode=BASE_ENTRY_MODE,
        evaluation_end=end,
        pip_size=pip_size,
        costs=costs,
    )
    base_trades = _period(base_trades, START, end)
    d1_states = _states(bars, "D1")
    h4_states = _states(bars, "H4")

    variants: dict[str, Any] = {}
    for variant in VARIANTS:
        trades, filter_counts = _filter_trades(
            base_trades,
            variant=variant,
            d1_states=d1_states,
            h4_states=h4_states,
        )
        era_a = _period(trades, START, ERA_2012_2018_END)
        era_b = _period(trades, ERA_2012_2018_END, ERA_2019_2024_END)
        era_c = _period(trades, ERA_2019_2024_END, end)
        recent = _period(trades, RECENT, end)
        capital = _capital(trades, broker_spec=broker_spec, leverage_tiers=leverage_tiers)
        variants[variant.variant_id] = {
            "variant": asdict(variant),
            "filter_counts": filter_counts,
            "full_metrics": _metrics(trades),
            "era_2012_2018": _metrics(era_a),
            "era_2019_2024": _metrics(era_b),
            "era_2025_2026": _metrics(era_c),
            "recent_metrics": _metrics(recent),
            "live100": capital,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "identity": "AFIC-inspired reconstruction hypothesis; not claimed as AFIC proprietary rules",
            "base_signal_family": "V143 BREAKOUT_LEVEL_RETEST_2BAR",
            "existing_h1_permission": "V134 STRICT inside V143 lineage",
            "new_higher_timeframe_tests": ["D1", "H4", "D1+H4", "D1+H4 not-opposed", "D1+H4+premium/discount"],
            "causality": "only completed H4/D1 buckets are visible at each M15 signal",
            "structure": "confirmed 2-left/2-right pivots inside trailing 80 HTF bars; MSS>BOS>trend direction priority",
            "premium_discount": "20 completed H4 bars midpoint; SHORT requires entry >= midpoint, LONG <= midpoint",
            "entry": BASE_ENTRY_MODE,
            "execution_authority": False,
            "no_parameter_grid": True,
        },
        "base_fill_stats": fill_stats,
        "base_trade_count": len(base_trades),
        "h4_states": len(h4_states),
        "d1_states": len(d1_states),
        "variants": variants,
        "note": (
            "V152 isolates the user's AFIC hypothesis: higher-timeframe D1/H4 context may decide "
            "direction, while an already-frozen M15 retest engine handles timing. The control is "
            "non-selecting and no result is allowed to change DEMO/LIVE execution."
        ),
    }
