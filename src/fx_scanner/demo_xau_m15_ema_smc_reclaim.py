from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Sequence

from .models import Bar
from .technical import atr, structure_snapshot

STRATEGY_ID = "XAU_M15_EMA_SMC_RECLAIM_V1"
STRATEGY_PROFILE = "EMA_SMC_RECLAIM_M15_V1"
SYMBOL = "XAUUSD"
EMA_PERIODS = (20, 50, 200)
ADX_PERIOD = 14
ATR_PERIOD = 14
MIN_M15_BARS = 220
MIN_H1_BARS = 40
SWING_LOOKBACK = 2
SWEEP_RECLAIM_BARS = 3
STRUCTURAL_STOP_BUFFER_ATR = 0.15
RECENT_RECLAIM_BARS = 4
SLOPE_LOOKBACK = 5

SCORE_WEIGHTS = {
    "trend_regime": 20.0,
    "ema_alignment": 15.0,
    "h1_alignment": 10.0,
    "liquidity_sweep": 10.0,
    "choch_bos": 15.0,
    "displacement_fvg": 10.0,
    "adx_di": 10.0,
    "atr_geometry_rr": 10.0,
}


@dataclass(frozen=True, slots=True)
class DirectionalAssessment:
    direction: str
    score: float
    state: str
    active: bool
    components: dict[str, float]
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EmaSmcReclaimEvaluation:
    strategy_id: str
    profile: str
    symbol: str
    available: bool
    selected_direction: str | None
    score: float
    state: str
    active: bool
    execution_eligible: bool
    policy_effect: str
    components: dict[str, float]
    evidence: dict[str, Any]
    long: DirectionalAssessment | None = None
    short: DirectionalAssessment | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def _ema_series(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 1:
        raise ValueError("EMA period must be greater than one")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(value) for value in values[:period]) / float(period)
    output: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (float(period) + 1.0)
    previous = seed
    for value in values[period:]:
        previous = alpha * float(value) + (1.0 - alpha) * previous
        output.append(previous)
    return tuple(output)


def _rma(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("RMA period must be positive")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(value) for value in values[:period]) / float(period)
    output: list[float | None] = [None] * (period - 1) + [seed]
    previous = seed
    for value in values[period:]:
        previous = ((previous * (period - 1)) + float(value)) / float(period)
        output.append(previous)
    return tuple(output)


def _adx_di(
    bars: Sequence[Bar],
    *,
    period: int = ADX_PERIOD,
) -> tuple[float | None, float | None, float | None, bool]:
    rows = tuple(bars)
    if len(rows) < period * 2 + 2:
        return None, None, None, False

    trs: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    previous = rows[0]
    for current in rows[1:]:
        up_move = float(current.high) - float(previous.high)
        down_move = float(previous.low) - float(current.low)
        plus_dm.append(up_move if up_move > down_move and up_move > 0.0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0.0 else 0.0)
        trs.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
        )
        previous = current

    tr_rma = _rma(trs, period)
    plus_rma = _rma(plus_dm, period)
    minus_rma = _rma(minus_dm, period)
    dx_values: list[float] = []
    for tr_value, plus_value, minus_value in zip(tr_rma, plus_rma, minus_rma):
        if tr_value is None or plus_value is None or minus_value is None or tr_value <= 0.0:
            continue
        plus_di = 100.0 * plus_value / tr_value
        minus_di = 100.0 * minus_value / tr_value
        denominator = plus_di + minus_di
        dx_values.append(
            0.0 if denominator <= 1e-12 else 100.0 * abs(plus_di - minus_di) / denominator
        )

    if len(dx_values) < period:
        return None, None, None, False

    adx_values = _rma(dx_values, period)
    finite_adx = [float(value) for value in adx_values if value is not None]
    latest_tr = next((float(v) for v in reversed(tr_rma) if v is not None), None)
    latest_plus = next((float(v) for v in reversed(plus_rma) if v is not None), None)
    latest_minus = next((float(v) for v in reversed(minus_rma) if v is not None), None)
    if (
        not finite_adx
        or latest_tr is None
        or latest_plus is None
        or latest_minus is None
        or latest_tr <= 0.0
    ):
        return None, None, None, False

    adx = finite_adx[-1]
    plus_di = 100.0 * latest_plus / latest_tr
    minus_di = 100.0 * latest_minus / latest_tr
    rising = len(finite_adx) >= 2 and finite_adx[-1] > finite_adx[-2]
    return adx, plus_di, minus_di, rising


def _recent_cross(
    closes: Sequence[float],
    ema: Sequence[float | None],
    *,
    direction: str,
    bars: int = RECENT_RECLAIM_BARS,
) -> bool:
    if len(closes) != len(ema) or len(closes) < 2:
        return False
    start = max(1, len(closes) - int(bars))
    for index in range(start, len(closes)):
        prev_ema = ema[index - 1]
        current_ema = ema[index]
        if prev_ema is None or current_ema is None:
            continue
        previous_close = float(closes[index - 1])
        current_close = float(closes[index])
        if direction == "LONG":
            if previous_close <= float(prev_ema) and current_close > float(current_ema):
                return True
        else:
            if previous_close >= float(prev_ema) and current_close < float(current_ema):
                return True
    return False


def _ema_slope(
    series: Sequence[float | None],
    *,
    lookback: int = SLOPE_LOOKBACK,
) -> float | None:
    finite_indexes = [index for index, value in enumerate(series) if value is not None]
    if len(finite_indexes) < lookback + 1:
        return None
    current_index = finite_indexes[-1]
    prior_index = current_index - lookback
    if prior_index < 0 or series[prior_index] is None:
        return None
    return float(series[current_index]) - float(series[prior_index])


def _directional_token(direction: str) -> str:
    if direction == "LONG":
        return "BULLISH"
    if direction == "SHORT":
        return "BEARISH"
    raise ValueError("direction must be LONG or SHORT")


def _score_state(score: float) -> tuple[str, bool]:
    if score >= 85.0:
        return "A_PLUS_SETUP", True
    if score >= 75.0:
        return "VALID_SETUP", True
    if score >= 65.0:
        return "WATCH", False
    return "NO_TRADE", False


def _component_sum(components: dict[str, float]) -> float:
    score = sum(float(value) for value in components.values())
    return max(0.0, min(100.0, score))


def _recent_smc_sequence(
    m15: Sequence[Bar],
    *,
    direction: str,
    ema20_value: float,
    ema50_value: float,
    current_atr: float,
    window: int = 10,
) -> dict[str, Any]:
    wanted = _directional_token(direction)
    current_index = len(m15) - 1
    start = max(6, len(m15) - int(window))
    sweep_index: int | None = None
    bos_index: int | None = None
    mss_index: int | None = None
    displacement_index: int | None = None
    fvg_index: int | None = None
    latest_fvg: tuple[float, float] | None = None

    for end in range(start, len(m15)):
        snapshot = structure_snapshot(
            list(m15[: end + 1]),
            swing_lookback=SWING_LOOKBACK,
            atr_period=ATR_PERIOD,
            sweep_reclaim_bars=SWEEP_RECLAIM_BARS,
        )
        sweep = snapshot.sweep
        if sweep is not None and sweep.valid and sweep.direction == wanted:
            sweep_index = end
        if snapshot.bos == wanted:
            bos_index = end
        if snapshot.mss == wanted:
            mss_index = end
        displacement = snapshot.displacement
        if displacement is not None and displacement.valid and displacement.direction == wanted:
            displacement_index = end
        fvg = snapshot.fvg
        if fvg is not None and fvg.valid and fvg.direction == wanted:
            fvg_index = end
            latest_fvg = (float(fvg.lower), float(fvg.upper))

    structure_index = mss_index if mss_index is not None else bos_index
    impulse_indexes = [index for index in (displacement_index, fvg_index) if index is not None]
    impulse_index = max(impulse_indexes) if impulse_indexes else None
    ordered = bool(
        sweep_index is not None
        and structure_index is not None
        and impulse_index is not None
        and sweep_index <= structure_index
        and sweep_index <= impulse_index
        and abs(structure_index - impulse_index) <= 2
    )
    event_index = max(sweep_index, structure_index, impulse_index) if ordered else None
    retracement_after_event = event_index is not None and current_index > event_index

    current = m15[-1]
    zone_low = min(float(ema20_value), float(ema50_value))
    zone_high = max(float(ema20_value), float(ema50_value))
    ema_retrace = bool(
        float(current.low) <= zone_high + 0.25 * current_atr
        and float(current.high) >= zone_low - 0.10 * current_atr
    )
    fvg_retrace = bool(
        latest_fvg is not None
        and float(current.low) <= latest_fvg[1]
        and float(current.high) >= latest_fvg[0]
    )
    retracement_ok = bool(retracement_after_event and (ema_retrace or fvg_retrace))
    return {
        "sweep_index": sweep_index,
        "bos_index": bos_index,
        "mss_index": mss_index,
        "displacement_index": displacement_index,
        "fvg_index": fvg_index,
        "ordered": ordered,
        "event_index": event_index,
        "retrace_after_event": retracement_after_event,
        "ema_retrace": ema_retrace,
        "fvg_retrace": fvg_retrace,
        "retracement_ok": retracement_ok,
        "latest_fvg": latest_fvg,
    }


def _directional_assessment(
    *,
    direction: str,
    m15: Sequence[Bar],
    h1: Sequence[Bar],
    ema20: Sequence[float | None],
    ema50: Sequence[float | None],
    ema200: Sequence[float | None],
    m15_atr: float,
    adx: float | None,
    plus_di: float | None,
    minus_di: float | None,
    adx_rising: bool,
) -> DirectionalAssessment:
    wanted = _directional_token(direction)
    latest = m15[-1]
    close = float(latest.close)
    current_20 = float(ema20[-1])
    current_50 = float(ema50[-1])
    current_200 = float(ema200[-1])
    slope20 = _ema_slope(ema20) or 0.0
    slope50 = _ema_slope(ema50) or 0.0
    recent_reclaim = _recent_cross(
        [float(row.close) for row in m15],
        ema200,
        direction=direction,
    )

    m15_snapshot = structure_snapshot(
        list(m15),
        swing_lookback=SWING_LOOKBACK,
        atr_period=ATR_PERIOD,
        sweep_reclaim_bars=SWEEP_RECLAIM_BARS,
    )
    h1_snapshot = structure_snapshot(
        list(h1),
        swing_lookback=SWING_LOOKBACK,
        atr_period=ATR_PERIOD,
        sweep_reclaim_bars=SWEEP_RECLAIM_BARS,
    )

    if direction == "LONG":
        price_regime = close > current_200
        full_alignment = close > current_20 > current_50 > current_200
        momentum_alignment = current_20 > current_50 and slope20 > 0.0 and slope50 >= 0.0
        directional_di = plus_di is not None and minus_di is not None and plus_di > minus_di
    else:
        price_regime = close < current_200
        full_alignment = close < current_20 < current_50 < current_200
        momentum_alignment = current_20 < current_50 and slope20 < 0.0 and slope50 <= 0.0
        directional_di = plus_di is not None and minus_di is not None and minus_di > plus_di

    transition = bool(recent_reclaim and price_regime and momentum_alignment)

    components = {key: 0.0 for key in SCORE_WEIGHTS}

    if price_regime and m15_snapshot.trend == wanted:
        components["trend_regime"] = 20.0
    elif transition:
        components["trend_regime"] = 16.0
    elif price_regime:
        components["trend_regime"] = 10.0

    if full_alignment:
        components["ema_alignment"] = 15.0
    elif transition:
        components["ema_alignment"] = 12.0
    elif price_regime and momentum_alignment:
        components["ema_alignment"] = 8.0

    if h1_snapshot.trend == wanted:
        components["h1_alignment"] = 10.0
    elif h1_snapshot.bos == wanted or h1_snapshot.mss == wanted:
        components["h1_alignment"] = 7.0
    elif h1_snapshot.trend in {"RANGE", "UNKNOWN"}:
        components["h1_alignment"] = 3.0

    smc_sequence = _recent_smc_sequence(
        m15,
        direction=direction,
        ema20_value=current_20,
        ema50_value=current_50,
        current_atr=m15_atr,
    )
    sweep_valid = smc_sequence["sweep_index"] is not None
    if sweep_valid:
        components["liquidity_sweep"] = 10.0

    if smc_sequence["mss_index"] is not None:
        components["choch_bos"] = 15.0
    elif smc_sequence["bos_index"] is not None:
        components["choch_bos"] = 11.0
    elif h1_snapshot.bos == wanted or h1_snapshot.mss == wanted:
        components["choch_bos"] = 5.0

    displacement_valid = smc_sequence["displacement_index"] is not None
    fvg_valid = smc_sequence["fvg_index"] is not None
    if displacement_valid and fvg_valid:
        components["displacement_fvg"] = 10.0
    elif displacement_valid or fvg_valid:
        components["displacement_fvg"] = 6.0

    if directional_di and adx is not None:
        if adx >= 25.0:
            components["adx_di"] = 10.0
        elif adx >= 20.0:
            components["adx_di"] = 8.0
        elif adx >= 15.0 and adx_rising:
            components["adx_di"] = 5.0
        else:
            components["adx_di"] = 3.0

    structural_stop: float | None = None
    liquidity_target: float | None = None
    projected_rr: float | None = None
    if direction == "LONG":
        if m15_snapshot.last_swing_low is not None:
            structural_stop = float(m15_snapshot.last_swing_low) - STRUCTURAL_STOP_BUFFER_ATR * m15_atr
        if m15_snapshot.last_swing_high is not None and float(m15_snapshot.last_swing_high) > close:
            liquidity_target = float(m15_snapshot.last_swing_high)
        if structural_stop is not None and structural_stop < close and liquidity_target is not None:
            risk = close - structural_stop
            if risk > 0:
                projected_rr = (liquidity_target - close) / risk
    else:
        if m15_snapshot.last_swing_high is not None:
            structural_stop = float(m15_snapshot.last_swing_high) + STRUCTURAL_STOP_BUFFER_ATR * m15_atr
        if m15_snapshot.last_swing_low is not None and float(m15_snapshot.last_swing_low) < close:
            liquidity_target = float(m15_snapshot.last_swing_low)
        if structural_stop is not None and structural_stop > close and liquidity_target is not None:
            risk = structural_stop - close
            if risk > 0:
                projected_rr = (close - liquidity_target) / risk

    if projected_rr is not None:
        if projected_rr >= 2.0:
            components["atr_geometry_rr"] = 10.0
        elif projected_rr >= 1.5:
            components["atr_geometry_rr"] = 8.0
        elif projected_rr >= 1.0:
            components["atr_geometry_rr"] = 4.0

    raw_score = _component_sum(components)

    # The strategy requires a directional EMA regime plus either mature alignment
    # or an actual EMA200 reclaim transition. Scoring alone cannot bypass this.
    regime_gate = bool(price_regime and (full_alignment or transition or momentum_alignment))
    structure_gate = bool(smc_sequence["ordered"] and smc_sequence["retracement_ok"])
    if not regime_gate:
        score = min(raw_score, 64.0)
    elif not structure_gate:
        # A strong impulse is WATCH-only until a post-impulse EMA/FVG retracement
        # confirms execution geometry. This is the explicit anti-FOMO gate.
        score = min(raw_score, 74.0)
    else:
        score = raw_score

    state, active = _score_state(score)
    evidence = {
        "price": close,
        "ema20": current_20,
        "ema50": current_50,
        "ema200": current_200,
        "ema20_slope": slope20,
        "ema50_slope": slope50,
        "recent_ema200_reclaim": recent_reclaim,
        "price_regime_ok": price_regime,
        "full_ema_alignment": full_alignment,
        "momentum_alignment": momentum_alignment,
        "transition_reclaim": transition,
        "m15_trend": m15_snapshot.trend,
        "m15_bos": m15_snapshot.bos,
        "m15_mss_choch": m15_snapshot.mss,
        "recent_smc_sequence": dict(smc_sequence),
        "h1_trend": h1_snapshot.trend,
        "h1_bos": h1_snapshot.bos,
        "h1_mss_choch": h1_snapshot.mss,
        "adx14": adx,
        "plus_di14": plus_di,
        "minus_di14": minus_di,
        "adx_rising": adx_rising,
        "directional_di": directional_di,
        "atr14": m15_atr,
        "structural_stop": structural_stop,
        "liquidity_target": liquidity_target,
        "projected_rr": projected_rr,
        "regime_gate": regime_gate,
        "structure_gate": structure_gate,
    }
    return DirectionalAssessment(
        direction=direction,
        score=round(score, 6),
        state=state,
        active=active,
        components={key: round(value, 6) for key, value in components.items()},
        evidence=evidence,
    )


def evaluate_xau_m15_ema_smc_reclaim(
    m15_bars: Sequence[Bar],
    h1_bars: Sequence[Bar],
) -> EmaSmcReclaimEvaluation:
    m15 = tuple(m15_bars)
    h1 = tuple(h1_bars)
    if (
        len(m15) < MIN_M15_BARS
        or len(h1) < MIN_H1_BARS
        or any(str(row.symbol).upper() != SYMBOL for row in m15)
        or any(str(row.symbol).upper() != SYMBOL for row in h1)
    ):
        return EmaSmcReclaimEvaluation(
            strategy_id=STRATEGY_ID,
            profile=STRATEGY_PROFILE,
            symbol=SYMBOL,
            available=False,
            selected_direction=None,
            score=0.0,
            state="NO_TRADE",
            active=False,
            execution_eligible=False,
            policy_effect="OBSERVATION_ONLY",
            components={key: 0.0 for key in SCORE_WEIGHTS},
            evidence={
                "reason": "INSUFFICIENT_OR_INVALID_HISTORY",
                "m15_bars": len(m15),
                "h1_bars": len(h1),
                "minimum_m15_bars": MIN_M15_BARS,
                "minimum_h1_bars": MIN_H1_BARS,
            },
        )

    closes = tuple(float(row.close) for row in m15)
    ema20 = _ema_series(closes, EMA_PERIODS[0])
    ema50 = _ema_series(closes, EMA_PERIODS[1])
    ema200 = _ema_series(closes, EMA_PERIODS[2])
    if any(series[-1] is None for series in (ema20, ema50, ema200)):
        raise ValueError("EMA history contract violated")

    m15_atr = float(atr(list(m15), ATR_PERIOD))
    adx, plus_di, minus_di, adx_rising = _adx_di(m15, period=ADX_PERIOD)
    if not isfinite(m15_atr) or m15_atr <= 0.0:
        raise ValueError("M15 ATR must be positive")

    long = _directional_assessment(
        direction="LONG",
        m15=m15,
        h1=h1,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        m15_atr=m15_atr,
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        adx_rising=adx_rising,
    )
    short = _directional_assessment(
        direction="SHORT",
        m15=m15,
        h1=h1,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        m15_atr=m15_atr,
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        adx_rising=adx_rising,
    )

    selected = long if long.score >= short.score else short
    if long.score == short.score and not long.active and not short.active:
        selected_direction: str | None = None
    else:
        selected_direction = selected.direction

    return EmaSmcReclaimEvaluation(
        strategy_id=STRATEGY_ID,
        profile=STRATEGY_PROFILE,
        symbol=SYMBOL,
        available=True,
        selected_direction=selected_direction,
        score=selected.score,
        state=selected.state,
        active=selected.active,
        execution_eligible=False,
        policy_effect="OBSERVATION_ONLY",
        components=selected.components,
        evidence={
            "ema_periods": list(EMA_PERIODS),
            "adx_period": ADX_PERIOD,
            "atr_period": ATR_PERIOD,
            "score_weights": dict(SCORE_WEIGHTS),
            "thresholds": {
                "watch_min": 65.0,
                "valid_setup_min": 75.0,
                "a_plus_min": 85.0,
            },
            "selected": selected.evidence,
            "long_score": long.score,
            "long_state": long.state,
            "short_score": short.score,
            "short_state": short.state,
        },
        long=long,
        short=short,
    )
