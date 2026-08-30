from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
            if value is not None and (not isfinite(float(value)) or value <= 0):
                raise DataContractError(f"{name} must be positive finite")
        for name, value in (("rr1", self.rr1), ("rr2", self.rr2)):
            if value is not None and (not isfinite(float(value)) or value <= 0):
                raise DataContractError(f"{name} must be positive finite")


@dataclass(frozen=True, slots=True)
class MTFAnalysis:
    symbol: str
    direction: str
    setup_type: SetupType | None
    d1: StructureSnapshot
    h4: StructureSnapshot
    h1: StructureSnapshot
    m15: StructureSnapshot
    m5: StructureSnapshot
    liquidity: LiquidityMap
    trade_plan: TradePlan | None
    conviction_components: Mapping[str, float | None]
    computed_guards: Mapping[str, bool]
    decision: DecisionSnapshot


def select_pair_candidates(
    ranked: Sequence[PairRank],
    *,
    macro_compatible_top: int = 8,
    deep_analysis_top: int = 5,
) -> UniverseSelection:
    if macro_compatible_top <= 0 or deep_analysis_top <= 0:
        raise DataContractError("selection limits must be positive")
    if deep_analysis_top > macro_compatible_top:
        raise DataContractError("deep-analysis limit cannot exceed macro-compatible limit")

    compatible: list[PairRank] = []
    for item in ranked:
        if item.direction == "LONG" and item.relative_macro_edge > 0:
            compatible.append(item)
        elif item.direction == "SHORT" and item.relative_macro_edge < 0:
            compatible.append(item)

    compatible.sort(key=lambda x: (-x.absolute_edge, -x.coverage, x.rank, x.symbol))
    macro = tuple(compatible[:macro_compatible_top])
    deep = tuple(macro[:deep_analysis_top])
    return UniverseSelection(macro, deep)


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


def _choose_setup(
    direction: str,
    d1: StructureSnapshot,
    h4: StructureSnapshot,
    h1: StructureSnapshot,
    m15: StructureSnapshot,
    m5: StructureSnapshot,
    liquidity: LiquidityMap,
) -> SetupType | None:
    sweep_reversal = (
        m15.sweep is not None
        and m15.sweep.valid
        and _aligned(m15.sweep.direction, direction)
        and m5.displacement is not None
        and m5.displacement.valid
        and _aligned(m5.displacement.direction, direction)
        and (_aligned(m5.mss, direction) or _aligned(m5.bos, direction))
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
        and m5.displacement is not None
        and m5.displacement.valid
        and _aligned(m5.displacement.direction, direction)
        and (_aligned(m5.bos, direction) or _aligned(m5.mss, direction))
    )
    if trend_continuation:
        return SetupType.TREND_CONTINUATION
    return None


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
) -> MTFAnalysis:
    if rank.direction not in {"LONG", "SHORT"}:
        raise DataContractError("MTF analysis requires directional pair rank")
    as_of = ensure_utc(as_of)
    strategy = cfg.strategy
    mtf_cfg = strategy["mtf"]
    liquidity_cfg = strategy["liquidity"]
    plan_cfg = strategy["trade_plan"]
    _validate_bundle(rank.symbol, bars_by_timeframe, mtf_cfg["minimum_bars"])

    swing = int(mtf_cfg["swing_lookback"])
    atr_period = int(mtf_cfg["atr_period"])
    d1 = structure_snapshot(list(bars_by_timeframe["D1"]), swing_lookback=swing, atr_period=atr_period)
    h4 = structure_snapshot(list(bars_by_timeframe["H4"]), swing_lookback=swing, atr_period=atr_period)
    h1 = structure_snapshot(list(bars_by_timeframe["H1"]), swing_lookback=swing, atr_period=atr_period)
    m15 = structure_snapshot(list(bars_by_timeframe["M15"]), swing_lookback=swing, atr_period=atr_period)
    m5 = structure_snapshot(list(bars_by_timeframe["M5"]), swing_lookback=swing, atr_period=atr_period)

    current_price = float(bars_by_timeframe["M5"][-1].close)
    liquidity = build_liquidity_map(
        d1_bars=bars_by_timeframe["D1"],
        h1_bars=bars_by_timeframe["H1"],
        intraday_bars=bars_by_timeframe["M5"],
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
    setup_type = _choose_setup(rank.direction, d1, h4, h1, m15, m5, liquidity)
    plan = _build_trade_plan(
        direction=rank.direction,
        current_price=current_price,
        m15=m15,
        h1=h1,
        m5=m5,
        liquidity=liquidity,
        m5_bars=bars_by_timeframe["M5"],
        atr_period=atr_period,
        sl_buffer_atr=float(plan_cfg["sl_buffer_atr"]),
        minimum_entry_zone_atr=float(plan_cfg["minimum_entry_zone_atr"]),
    )

    cross_asset_score = None
    if rank.cross_asset_edge is not None:
        cross_asset_score = _edge_score(rank.cross_asset_edge, rank.direction, span=100.0)

    components = {
        "relative_macro": _edge_score(rank.relative_macro_edge, rank.direction, span=200.0),
        "htf_structure": _htf_score(rank.direction, d1, h4, h1),
        "liquidity": _liquidity_score(rank.direction, m15, liquidity),
        "smc_structure": _smc_score(rank.direction, m5),
        "displacement": _displacement_score(rank.direction, m15, m5),
        "session": _session_score(rank.symbol, as_of, cfg.sessions),
        "cross_asset": cross_asset_score,
        "positioning": positioning_score,
        "execution_quality": execution_quality_score,
    }

    computed = {
        "STRUCTURE_INVALID": _htf_conflict(rank.direction, d1, h4, h1) or setup_type is None,
        "CHASE_BLOCK": plan is None or plan.chase_distance_atr > float(plan_cfg["chase_block_atr"]),
        "RR_BLOCK": plan is None or plan.rr2 is None or plan.rr2 < float(plan_cfg["minimum_tp2_rr"]),
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
    return MTFAnalysis(
        rank.symbol,
        rank.direction,
        setup_type,
        d1,
        h4,
        h1,
        m15,
        m5,
        liquidity,
        plan,
        components,
        computed,
        decision,
    )


def scan_deep_candidates(
    *,
    ranked: Sequence[PairRank],
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    cfg: ProjectConfig,
    as_of: datetime,
    external_guards_by_symbol: Mapping[str, Mapping[str, bool]],
    positioning_by_symbol: Mapping[str, float | None] | None = None,
    execution_quality_by_symbol: Mapping[str, float | None] | None = None,
) -> tuple[MTFAnalysis, ...]:
    selection_cfg = cfg.strategy["selection"]
    selected = select_pair_candidates(
        ranked,
        macro_compatible_top=int(selection_cfg["macro_compatible_top"]),
        deep_analysis_top=int(selection_cfg["deep_analysis_top"]),
    )
    positioning_by_symbol = positioning_by_symbol or {}
    execution_quality_by_symbol = execution_quality_by_symbol or {}
    analyses: list[MTFAnalysis] = []
    for rank in selected.deep_analysis:
        bars = bars_by_symbol.get(rank.symbol)
        if bars is None:
            continue
        analyses.append(
            analyze_pair_mtf(
                rank=rank,
                bars_by_timeframe=bars,
                cfg=cfg,
                as_of=as_of,
                external_guard_flags=external_guards_by_symbol.get(rank.symbol, {}),
                positioning_score=positioning_by_symbol.get(rank.symbol),
                execution_quality_score=execution_quality_by_symbol.get(rank.symbol),
            )
        )
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
    return tuple(analyses)
