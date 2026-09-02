from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Mapping, Sequence

from .config import ProjectConfig
from .decision import DecisionSnapshot, build_decision
from .exceptions import DataContractError
from .liquidity import FairValueGap, LiquidityMap, build_liquidity_map
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .sessions import active_sessions
from .technical import StructureSnapshot, atr, structure_snapshot


class SetupType(StrEnum):
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    TREND_CONTINUATION = "TREND_CONTINUATION"


@dataclass(frozen=True, slots=True)
class UniverseSelection:
    macro_compatible: tuple[PairRank, ...]
    deep_analysis: tuple[PairRank, ...]


@dataclass(frozen=True, slots=True)
class TradePlan:
    direction: str
    entry_low: float
    entry_high: float
    stop_loss: float
    tp1: float | None
    tp2: float | None
    rr1: float | None
    rr2: float | None
    chase_distance_atr: float

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise DataContractError("trade-plan direction must be LONG or SHORT")
        values = (self.entry_low, self.entry_high, self.stop_loss, self.chase_distance_atr)
        if not all(isfinite(float(x)) for x in values):
            raise DataContractError("trade-plan values must be finite")
        if not 0 < self.entry_low < self.entry_high:
            raise DataContractError("trade-plan entry zone is invalid")
        if self.chase_distance_atr < 0:
            raise DataContractError("chase distance cannot be negative")
        if self.direction == "LONG" and self.stop_loss >= self.entry_low:
            raise DataContractError("LONG stop must be below entry zone")
        if self.direction == "SHORT" and self.stop_loss <= self.entry_high:
            raise DataContractError("SHORT stop must be above entry zone")
        for name, value in (("tp1", self.tp1), ("tp2", self.tp2)):
            if value is not None and (
                isinstance(value, bool) or not isfinite(float(value)) or value <= 0
            ):
                raise DataContractError(f"{name} must be positive finite")
        for name, value in (("rr1", self.rr1), ("rr2", self.rr2)):
            if value is not None and (
                isinstance(value, bool) or not isfinite(float(value)) or value <= 0
            ):
                raise DataContractError(f"{name} must be positive finite")
        if (self.tp1 is None) != (self.rr1 is None):
            raise DataContractError("tp1 and rr1 must be supplied together")
        if (self.tp2 is None) != (self.rr2 is None):
            raise DataContractError("tp2 and rr2 must be supplied together")
        if self.direction == "LONG":
            if self.tp1 is not None and self.tp1 <= self.entry_high:
                raise DataContractError("LONG tp1 must be above entry zone")
            if self.tp2 is not None and self.tp2 <= self.entry_high:
                raise DataContractError("LONG tp2 must be above entry zone")
            if self.tp1 is not None and self.tp2 is not None and self.tp2 <= self.tp1:
                raise DataContractError("LONG tp2 must be beyond tp1")
        else:
            if self.tp1 is not None and self.tp1 >= self.entry_low:
                raise DataContractError("SHORT tp1 must be below entry zone")
            if self.tp2 is not None and self.tp2 >= self.entry_low:
                raise DataContractError("SHORT tp2 must be below entry zone")
            if self.tp1 is not None and self.tp2 is not None and self.tp2 >= self.tp1:
                raise DataContractError("SHORT tp2 must be beyond tp1")
        if self.rr1 is not None and self.rr2 is not None and self.rr2 <= self.rr1:
            raise DataContractError("rr2 must exceed rr1")


@dataclass(frozen=True, slots=True)
class MTFAnalysis:
    symbol: str
    direction: str
    setup_type: SetupType | None
    trigger_confirmed: bool
    d1: StructureSnapshot
    h4: StructureSnapshot
    h1: StructureSnapshot
    m15: StructureSnapshot
    m5: StructureSnapshot
    liquidity: LiquidityMap
    trade_plan: TradePlan | None
    conviction_components: Mapping[str, float | None]
    computed_guards: Mapping[str, bool]
    stale_timeframes: tuple[str, ...]
    decision: DecisionSnapshot


@dataclass(frozen=True, slots=True)
class DeepScanReport:
    selection: UniverseSelection
    analyses: tuple[MTFAnalysis, ...]
    skipped: Mapping[str, str]


def select_pair_candidates(
    ranked: Sequence[PairRank],
    *,
    macro_compatible_top: int = 8,
    deep_analysis_top: int = 5,
    compatibility_mode: str = "MACRO",
) -> UniverseSelection:
    if macro_compatible_top <= 0 or deep_analysis_top <= 0:
        raise DataContractError("selection limits must be positive")
    if deep_analysis_top > macro_compatible_top:
        raise DataContractError("deep-analysis limit cannot exceed macro-compatible limit")

    mode = str(compatibility_mode).upper()
    if mode not in {"MACRO", "TECHNICAL"}:
        raise DataContractError("compatibility_mode must be MACRO or TECHNICAL")
    compatible: list[PairRank] = []
    for item in ranked:
        edge = item.relative_technical_edge if mode == "TECHNICAL" else item.relative_macro_edge
        if item.direction == "LONG" and edge > 0:
            compatible.append(item)
        elif item.direction == "SHORT" and edge < 0:
            compatible.append(item)

    compatible.sort(key=lambda x: (-x.absolute_edge, -x.coverage, x.rank, x.symbol))
    macro = tuple(compatible[:macro_compatible_top])
    deep = tuple(macro[:deep_analysis_top])
    return UniverseSelection(macro, deep)


def _closed_bar_bundle(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    *,
    as_of: datetime,
    timeframe_seconds: Mapping[str, int],
) -> dict[str, tuple[Bar, ...]]:
    closed: dict[str, tuple[Bar, ...]] = {}
    for tf, bars in bars_by_timeframe.items():
        seconds = timeframe_seconds.get(tf)
        if seconds is None:
            continue
        close_cutoff = ensure_utc(as_of)
        closed[tf] = tuple(
            bar for bar in bars
            if bar.timestamp + timedelta(seconds=int(seconds)) <= close_cutoff
        )
    return closed


def _stale_timeframes(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    *,
    as_of: datetime,
    timeframe_seconds: Mapping[str, int],
    max_age_seconds: Mapping[str, int],
) -> tuple[str, ...]:
    now = ensure_utc(as_of)
    stale: list[str] = []
    for tf in ("D1", "H4", "H1", "M15", "M5"):
        bars = bars_by_timeframe.get(tf, ())
        if not bars:
            stale.append(tf)
            continue
        last_close = bars[-1].timestamp + timedelta(seconds=int(timeframe_seconds[tf]))
        age = (now - last_close).total_seconds()
        if age < -1:
            stale.append(tf)
            continue
        if age > float(max_age_seconds[tf]):
            stale.append(tf)
    return tuple(stale)


def _validate_bundle(
    symbol: str,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    minimum_bars: Mapping[str, int],
) -> None:
    required = ("D1", "H4", "H1", "M15", "M5")
    missing = [tf for tf in required if tf not in bars_by_timeframe]
    if missing:
        raise DataContractError(f"missing MTF bars: {missing}")
    for tf in required:
        bars = bars_by_timeframe[tf]
        minimum = int(minimum_bars[tf])
        if len(bars) < minimum:
            raise DataContractError(f"{symbol} {tf} requires at least {minimum} bars")
        if any(b.symbol != symbol for b in bars):
            raise DataContractError(f"{symbol} {tf} contains another symbol")
        if any(b.timeframe != tf for b in bars):
            raise DataContractError(f"{symbol} bundle has wrong timeframe in {tf}")
        if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
            raise DataContractError(f"{symbol} {tf} bars are not chronological")


def _directional_structure_score(snapshot: StructureSnapshot, direction: str) -> float | None:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    opposite = "BEARISH" if wanted == "BULLISH" else "BULLISH"
    if snapshot.trend == "UNKNOWN":
        return None
    score = 50.0
    if snapshot.trend == wanted:
        score += 30.0
    elif snapshot.trend == opposite:
        score -= 40.0
    if snapshot.bos == wanted:
        score += 15.0
    elif snapshot.bos == opposite:
        score -= 25.0
    if snapshot.mss == wanted:
        score += 20.0
    elif snapshot.mss == opposite:
        score -= 30.0
    return max(0.0, min(100.0, score))


def _htf_score(
    direction: str,
    d1: StructureSnapshot,
    h4: StructureSnapshot,
    h1: StructureSnapshot,
) -> float | None:
    scores = (
        _directional_structure_score(d1, direction),
        _directional_structure_score(h4, direction),
        _directional_structure_score(h1, direction),
    )
    if any(x is None for x in scores):
        return None
    return 0.30 * scores[0] + 0.40 * scores[1] + 0.30 * scores[2]


def _htf_conflict(direction: str, *snapshots: StructureSnapshot) -> bool:
    opposite = "BEARISH" if direction == "LONG" else "BULLISH"
    # A hard conflict requires an actual opposing trend; a range is degraded by
    # scoring but is not itself treated as an invalid structure.
    return any(snapshot.trend == opposite for snapshot in snapshots)


def _aligned(value: str | None, direction: str) -> bool:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    return value == wanted


def _favorable_dealing_zone(direction: str, liquidity: LiquidityMap) -> bool:
    dr = liquidity.dealing_range
    if dr is None:
        return False
    if direction == "LONG":
        return dr.zone in {"DISCOUNT", "EQUILIBRIUM"}
    return dr.zone in {"PREMIUM", "EQUILIBRIUM"}


def _scalp_structure_score(
    direction: str,
    h1: StructureSnapshot,
    m15: StructureSnapshot,
    m5: StructureSnapshot,
) -> float | None:
    scores = (
        _directional_structure_score(h1, direction),
        _directional_structure_score(m15, direction),
        _directional_structure_score(m5, direction),
    )
    if any(x is None for x in scores):
        return None
    return 0.25 * scores[0] + 0.35 * scores[1] + 0.40 * scores[2]


def _choose_scalp_setup(
    direction: str,
    h1: StructureSnapshot,
    m15: StructureSnapshot,
    liquidity: LiquidityMap,
) -> SetupType | None:
    sweep_reversal = (
        m15.sweep is not None
        and m15.sweep.valid
        and _aligned(m15.sweep.direction, direction)
        and _favorable_dealing_zone(direction, liquidity)
    )
    if sweep_reversal:
        return SetupType.LIQUIDITY_SWEEP_REVERSAL

    trend_continuation = (
        not _htf_conflict(direction, h1, m15)
        and (_directional_structure_score(h1, direction) or 0) >= 55
        and (_directional_structure_score(m15, direction) or 0) >= 55
        and m15.fvg is not None
        and m15.fvg.valid
        and _aligned(m15.fvg.direction, direction)
    )
    if trend_continuation:
        return SetupType.TREND_CONTINUATION
    return None


def _choose_setup(
    direction: str,
    d1: StructureSnapshot,
    h4: StructureSnapshot,
    h1: StructureSnapshot,
    m15: StructureSnapshot,
    liquidity: LiquidityMap,
) -> SetupType | None:
    sweep_reversal = (
        m15.sweep is not None
        and m15.sweep.valid
        and _aligned(m15.sweep.direction, direction)
        and _favorable_dealing_zone(direction, liquidity)
    )
    if sweep_reversal:
        return SetupType.LIQUIDITY_SWEEP_REVERSAL

    trend_continuation = (
        not _htf_conflict(direction, d1, h4, h1)
        and _directional_structure_score(d1, direction) is not None
        and (_directional_structure_score(d1, direction) or 0) >= 65
        and (_directional_structure_score(h4, direction) or 0) >= 65
        and (_directional_structure_score(h1, direction) or 0) >= 60
        and m15.fvg is not None
        and m15.fvg.valid
        and _aligned(m15.fvg.direction, direction)
    )
    if trend_continuation:
        return SetupType.TREND_CONTINUATION
    return None


def _m5_trigger_confirmed(direction: str, m5: StructureSnapshot) -> bool:
    return bool(
        m5.displacement is not None
        and m5.displacement.valid
        and _aligned(m5.displacement.direction, direction)
        and (_aligned(m5.mss, direction) or _aligned(m5.bos, direction))
    )


def _entry_fvg(direction: str, m5: StructureSnapshot, liquidity: LiquidityMap) -> FairValueGap | None:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    candidates = [
        gap for gap in liquidity.fvgs
        if gap.direction == wanted and gap.status in {"OPEN", "PARTIAL"}
    ]
    if candidates:
        return candidates[-1]
    if m5.fvg is not None and m5.fvg.valid and m5.fvg.direction == wanted:
        # This synthetic state only translates the deterministic v0.6 current
        # FVG into the richer v0.8 trade-plan shape.
        return FairValueGap(
            wanted,
            m5.fvg.lower,
            m5.fvg.upper,
            liquidity.observed_at,
            "OPEN",
            0.0,
        )
    return None


def _unique_target_prices(levels, *, tolerance: float) -> list[float]:
    output: list[float] = []
    for item in levels:
        if not output or abs(item.price - output[-1]) > tolerance:
            output.append(item.price)
    return output


def _build_trade_plan(
    *,
    direction: str,
    current_price: float,
    m15: StructureSnapshot,
    h1: StructureSnapshot,
    m5: StructureSnapshot,
    liquidity: LiquidityMap,
    m5_bars: Sequence[Bar],
    atr_period: int,
    sl_buffer_atr: float,
    minimum_entry_zone_atr: float,
) -> TradePlan | None:
    gap = _entry_fvg(direction, m5, liquidity)
    if gap is None:
        return None

    current_atr = atr(list(m5_bars), atr_period)
    entry_low, entry_high = gap.lower, gap.upper
    if entry_high - entry_low < current_atr * minimum_entry_zone_atr:
        return None

    buffer = current_atr * sl_buffer_atr
    if direction == "LONG":
        anchor = None
        if m15.sweep is not None and m15.sweep.valid and m15.sweep.direction == "BULLISH":
            anchor = m15.sweep.level
        if anchor is None:
            anchor = h1.last_swing_low
        if anchor is None:
            return None
        stop = min(float(anchor), entry_low) - buffer
        chase = max(0.0, current_price - entry_high) / current_atr
        target_levels = liquidity.levels_above(entry_high)
        targets = _unique_target_prices(target_levels, tolerance=current_atr * 0.05)
        risk = entry_high - stop
        valid_targets = [p for p in targets if p > entry_high and (p - entry_high) > 0]
        tp1 = valid_targets[0] if valid_targets else None
        tp2 = valid_targets[1] if len(valid_targets) > 1 else None
        rr1 = None if tp1 is None else (tp1 - entry_high) / risk
        rr2 = None if tp2 is None else (tp2 - entry_high) / risk
    else:
        anchor = None
        if m15.sweep is not None and m15.sweep.valid and m15.sweep.direction == "BEARISH":
            anchor = m15.sweep.level
        if anchor is None:
            anchor = h1.last_swing_high
        if anchor is None:
            return None
        stop = max(float(anchor), entry_high) + buffer
        chase = max(0.0, entry_low - current_price) / current_atr
        target_levels = liquidity.levels_below(entry_low)
        targets = _unique_target_prices(target_levels, tolerance=current_atr * 0.05)
        risk = stop - entry_low
        valid_targets = [p for p in targets if p < entry_low and (entry_low - p) > 0]
        tp1 = valid_targets[0] if valid_targets else None
        tp2 = valid_targets[1] if len(valid_targets) > 1 else None
        rr1 = None if tp1 is None else (entry_low - tp1) / risk
        rr2 = None if tp2 is None else (entry_low - tp2) / risk

    if risk <= 0:
        return None
    return TradePlan(
        direction,
        entry_low,
        entry_high,
        stop,
        tp1,
        tp2,
        rr1,
        rr2,
        chase,
    )


def _session_score(symbol: str, timestamp: datetime, session_config: Mapping) -> float:
    active = set(active_sessions(timestamp, session_config))
    if {"LONDON", "NEW_YORK"}.issubset(active):
        return 100.0
    if "LONDON" in active or "NEW_YORK" in active:
        return 90.0
    if "ASIA" in active:
        asian_sensitive = any(code in symbol for code in ("JPY", "AUD", "NZD"))
        return 85.0 if asian_sensitive else 65.0
    return 40.0


def _liquidity_score(direction: str, m15: StructureSnapshot, liquidity: LiquidityMap) -> float:
    score = 40.0
    if _favorable_dealing_zone(direction, liquidity):
        score += 25.0
    if m15.sweep is not None and m15.sweep.valid and _aligned(m15.sweep.direction, direction):
        score += 35.0
    return min(100.0, score)


def _smc_score(direction: str, m5: StructureSnapshot) -> float:
    if _aligned(m5.mss, direction):
        return 100.0
    if _aligned(m5.bos, direction) and m5.fvg is not None and m5.fvg.valid and _aligned(m5.fvg.direction, direction):
        return 90.0
    if _aligned(m5.bos, direction):
        return 75.0
    return 25.0


def _displacement_score(direction: str, m15: StructureSnapshot, m5: StructureSnapshot) -> float:
    if m5.displacement is not None and m5.displacement.valid and _aligned(m5.displacement.direction, direction):
        return 100.0
    if m15.displacement is not None and m15.displacement.valid and _aligned(m15.displacement.direction, direction):
        return 75.0
    return 20.0


def _edge_score(edge: float, direction: str, *, span: float) -> float:
    signed = edge if direction == "LONG" else -edge
    return max(0.0, min(100.0, 50.0 + 50.0 * signed / span))


def analyze_pair_mtf(
    *,
    rank: PairRank,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg: ProjectConfig,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
    positioning_score: float | None = None,
    execution_quality_score: float | None = None,
    technical_scalping: bool = False,
) -> MTFAnalysis:
    if rank.direction not in {"LONG", "SHORT"}:
        raise DataContractError("MTF analysis requires directional pair rank")
    as_of = ensure_utc(as_of)
    strategy = cfg.strategy
    mtf_cfg = strategy["mtf"]
    liquidity_cfg = strategy["liquidity"]
    plan_cfg = strategy["trade_plan"]
    closed_bars = _closed_bar_bundle(
        bars_by_timeframe,
        as_of=as_of,
        timeframe_seconds=cfg.timeframes,
    )
    _validate_bundle(rank.symbol, closed_bars, mtf_cfg["minimum_bars"])
    stale_tfs = _stale_timeframes(
        closed_bars,
        as_of=as_of,
        timeframe_seconds=cfg.timeframes,
        max_age_seconds=mtf_cfg["max_bar_age_seconds"],
    )

    swing = int(mtf_cfg["swing_lookback"])
    atr_period = int(mtf_cfg["atr_period"])
    reclaim_bars = int(liquidity_cfg["sweep_reclaim_bars"])
    d1 = structure_snapshot(
        list(closed_bars["D1"]),
        swing_lookback=swing,
        atr_period=atr_period,
        sweep_reclaim_bars=reclaim_bars,
    )
    h4 = structure_snapshot(
        list(closed_bars["H4"]),
        swing_lookback=swing,
        atr_period=atr_period,
        sweep_reclaim_bars=reclaim_bars,
    )
    h1 = structure_snapshot(
        list(closed_bars["H1"]),
        swing_lookback=swing,
        atr_period=atr_period,
        sweep_reclaim_bars=reclaim_bars,
    )
    m15 = structure_snapshot(
        list(closed_bars["M15"]),
        swing_lookback=swing,
        atr_period=atr_period,
        sweep_reclaim_bars=reclaim_bars,
    )
    m5 = structure_snapshot(
        list(closed_bars["M5"]),
        swing_lookback=swing,
        atr_period=atr_period,
        sweep_reclaim_bars=reclaim_bars,
    )

    current_price = float(closed_bars["M5"][-1].close)
    liquidity = build_liquidity_map(
        d1_bars=closed_bars["D1"],
        h1_bars=closed_bars["H1"],
        intraday_bars=closed_bars["M5"],
        as_of=as_of,
        current_price=current_price,
        session_config=cfg.sessions,
        pivot_lookback=swing,
        atr_period=atr_period,
        tolerance_atr=float(liquidity_cfg["equal_level_tolerance_atr"]),
        minimum_touches=int(liquidity_cfg["equal_level_min_touches"]),
        equal_scan_bars=int(liquidity_cfg["equal_level_lookback_bars"]),
        equilibrium_band=float(liquidity_cfg["equilibrium_band"]),
        fvg_scan_bars=int(liquidity_cfg["fvg_scan_bars"]),
        order_block_search_bars=int(liquidity_cfg["order_block_search_bars"]),
        order_block_origin_lookback=int(liquidity_cfg["order_block_origin_lookback"]),
    )
    setup_type = (
        _choose_scalp_setup(rank.direction, h1, m15, liquidity)
        if technical_scalping
        else _choose_setup(rank.direction, d1, h4, h1, m15, liquidity)
    )
    trigger_confirmed = _m5_trigger_confirmed(rank.direction, m5)
    plan = _build_trade_plan(
        direction=rank.direction,
        current_price=current_price,
        m15=m15,
        h1=h1,
        m5=m5,
        liquidity=liquidity,
        m5_bars=closed_bars["M5"],
        atr_period=atr_period,
        sl_buffer_atr=float(plan_cfg["sl_buffer_atr"]),
        minimum_entry_zone_atr=float(plan_cfg["minimum_entry_zone_atr"]),
    )

    cross_asset_score = None
    if rank.cross_asset_edge is not None:
        cross_asset_score = _edge_score(rank.cross_asset_edge, rank.direction, span=100.0)

    internal_execution_quality: float | None
    if plan is None:
        internal_execution_quality = 20.0 if trigger_confirmed else 10.0
    else:
        chase_ok = float(plan_cfg["chase_ok_atr"])
        chase_block = float(plan_cfg["chase_block_atr"])
        if plan.chase_distance_atr <= chase_ok:
            chase_quality = 100.0
        else:
            span = max(1e-12, chase_block - chase_ok)
            chase_quality = max(
                40.0,
                100.0 - 60.0 * (plan.chase_distance_atr - chase_ok) / span,
            )
        preferred_rr = float(plan_cfg["preferred_tp2_rr"])
        minimum_rr = float(plan_cfg["minimum_tp2_rr"])
        if plan.rr2 is None:
            rr_quality = 20.0
        elif plan.rr2 >= preferred_rr:
            rr_quality = 100.0
        elif plan.rr2 >= minimum_rr:
            rr_quality = 70.0 + 30.0 * (
                (plan.rr2 - minimum_rr) / max(1e-12, preferred_rr - minimum_rr)
            )
        else:
            rr_quality = max(0.0, 70.0 * plan.rr2 / minimum_rr)
        internal_execution_quality = min(chase_quality, rr_quality)

    if execution_quality_score is None:
        combined_execution_quality = internal_execution_quality
    else:
        if isinstance(execution_quality_score, bool) or not isfinite(float(execution_quality_score)):
            raise DataContractError("execution_quality_score must be finite numeric")
        if not 0 <= float(execution_quality_score) <= 100:
            raise DataContractError("execution_quality_score must be in [0,100]")
        combined_execution_quality = min(
            internal_execution_quality,
            float(execution_quality_score),
        )

    if positioning_score is not None:
        if isinstance(positioning_score, bool) or not isfinite(float(positioning_score)):
            raise DataContractError("positioning_score must be finite numeric")
        if not 0 <= float(positioning_score) <= 100:
            raise DataContractError("positioning_score must be in [0,100]")

    if technical_scalping:
        components = {
            "htf_structure": _scalp_structure_score(rank.direction, h1, m15, m5),
            "liquidity": _liquidity_score(rank.direction, m15, liquidity),
            "smc_structure": _smc_score(rank.direction, m5),
            "displacement": _displacement_score(rank.direction, m15, m5),
            "session": _session_score(rank.symbol, as_of, cfg.sessions),
            "execution_quality": combined_execution_quality,
        }
    else:
        components = {
            "relative_macro": _edge_score(rank.relative_macro_edge, rank.direction, span=200.0),
            "htf_structure": _htf_score(rank.direction, d1, h4, h1),
            "liquidity": _liquidity_score(rank.direction, m15, liquidity),
            "smc_structure": _smc_score(rank.direction, m5),
            "displacement": _displacement_score(rank.direction, m15, m5),
            "session": _session_score(rank.symbol, as_of, cfg.sessions),
            "cross_asset": cross_asset_score,
            "positioning": positioning_score,
            "execution_quality": combined_execution_quality,
        }

    computed = {
        "STRUCTURE_INVALID": (
            _htf_conflict(rank.direction, h1, m15)
            if technical_scalping
            else _htf_conflict(rank.direction, d1, h4, h1)
        ),
        "STALE_SIGNAL": bool(stale_tfs),
        "CHASE_BLOCK": bool(
            plan is not None
            and plan.chase_distance_atr > float(plan_cfg["chase_block_atr"])
        ),
        "RR_BLOCK": bool(
            plan is not None
            and (plan.rr2 is None or plan.rr2 < float(plan_cfg["minimum_tp2_rr"]))
        ),
    }
    guard_flags = dict(external_guard_flags)
    guard_flags.update(computed)

    decision = build_decision(
        rank=rank,
        timestamp=as_of,
        conviction_components=components,
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags=guard_flags,
        required_guards=cfg.scoring["hard_guards"],
        minimum_coverage=0.80,
        minimum_pair_coverage=0.85,
    )

    # Strategy phase caps prevent an incomplete pattern from skipping directly
    # to ARMED/EXECUTION_READY merely because upstream evidence scores are high.
    state = decision.state
    if not decision.guards:
        if setup_type is None and state not in {SignalState.NO_TRADE, SignalState.WATCH}:
            state = SignalState.WATCH
        elif setup_type is not None and not trigger_confirmed and state in {
            SignalState.ARMED,
            SignalState.EXECUTION_READY,
        }:
            state = SignalState.SETUP_FORMING
        elif trigger_confirmed and plan is None and state in {
            SignalState.ARMED,
            SignalState.EXECUTION_READY,
        }:
            state = SignalState.SETUP_FORMING
    if state != decision.state:
        decision = replace(decision, state=state)

    return MTFAnalysis(
        rank.symbol,
        rank.direction,
        setup_type,
        trigger_confirmed,
        d1,
        h4,
        h1,
        m15,
        m5,
        liquidity,
        plan,
        components,
        computed,
        stale_tfs,
        decision,
    )


def scan_deep_candidates_report(
    *,
    ranked: Sequence[PairRank],
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    cfg: ProjectConfig,
    as_of: datetime,
    external_guards_by_symbol: Mapping[str, Mapping[str, bool]],
    positioning_by_symbol: Mapping[str, float | None] | None = None,
    execution_quality_by_symbol: Mapping[str, float | None] | None = None,
    technical_scalping: bool = False,
) -> DeepScanReport:
    selection_cfg = cfg.strategy["selection"]
    selected = select_pair_candidates(
        ranked,
        macro_compatible_top=int(selection_cfg["macro_compatible_top"]),
        deep_analysis_top=int(selection_cfg["deep_analysis_top"]),
        compatibility_mode="TECHNICAL" if technical_scalping else "MACRO",
    )
    positioning_by_symbol = positioning_by_symbol or {}
    execution_quality_by_symbol = execution_quality_by_symbol or {}
    analyses: list[MTFAnalysis] = []
    skipped: dict[str, str] = {}
    for rank in selected.deep_analysis:
        bars = bars_by_symbol.get(rank.symbol)
        if bars is None:
            skipped[rank.symbol] = "MISSING_MTF_BUNDLE"
            continue
        try:
            analyses.append(
                analyze_pair_mtf(
                    rank=rank,
                    bars_by_timeframe=bars,
                    cfg=cfg,
                    as_of=as_of,
                    external_guard_flags=external_guards_by_symbol.get(rank.symbol, {}),
                    positioning_score=positioning_by_symbol.get(rank.symbol),
                    execution_quality_score=execution_quality_by_symbol.get(rank.symbol),
                    technical_scalping=technical_scalping,
                )
            )
        except DataContractError as exc:
            skipped[rank.symbol] = f"DATA_CONTRACT:{exc}"
    analyses.sort(
        key=lambda x: (
            0 if x.decision.state == SignalState.EXECUTION_READY else
            1 if x.decision.state == SignalState.ARMED else
            2 if x.decision.state == SignalState.SETUP_FORMING else
            3 if x.decision.state == SignalState.WATCH else 4,
            -(x.decision.conviction_score or -1),
            x.symbol,
        )
    )
    return DeepScanReport(selected, tuple(analyses), dict(sorted(skipped.items())))


def scan_deep_candidates(
    *,
    ranked: Sequence[PairRank],
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    cfg: ProjectConfig,
    as_of: datetime,
    external_guards_by_symbol: Mapping[str, Mapping[str, bool]],
    positioning_by_symbol: Mapping[str, float | None] | None = None,
    execution_quality_by_symbol: Mapping[str, float | None] | None = None,
    technical_scalping: bool = False,
) -> tuple[MTFAnalysis, ...]:
    """Compatibility wrapper returning analyses while report API preserves skips."""
    return scan_deep_candidates_report(
        ranked=ranked,
        bars_by_symbol=bars_by_symbol,
        cfg=cfg,
        as_of=as_of,
        external_guards_by_symbol=external_guards_by_symbol,
        positioning_by_symbol=positioning_by_symbol,
        execution_quality_by_symbol=execution_quality_by_symbol,
        technical_scalping=technical_scalping,
    ).analyses
