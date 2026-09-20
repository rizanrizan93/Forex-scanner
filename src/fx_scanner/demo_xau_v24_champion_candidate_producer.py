from __future__ import annotations

"""Prospective cTrader DEMO adapter for the frozen XAU V24 champion portfolio.

Research lineage (no parameter retuning here):
- V20/V24 D1 staggered TSMOM: D1 close vs EMA200 + 60D return, next D1
  open, 2 ATR stop, 2R target, max 30 D1 bars, daily staggering.
- V20 M15 L12/L20 breakout: H1 EMA20/50 + ADX/DI direction, previous
  completed-D1 TSMOM direction match, M15 breakout/body/close-location,
  structural stop, 1.5R or 2R target, next M15 open, max 16 M15 bars.
- V20 portfolio de-duplication priority at the same entry/side:
  L20 > D1 staggered > L12.

This module intentionally does NOT turn V110/V123 post-V24 research filters into
execution gates. Their causal-health/era evidence remains a separate research
lineage so the DEMO forward sample can identify whether the original champion
edge survives prospectively instead of silently testing a different strategy.
"""

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Any, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore
from .demo_xau_v24_utc_d1_context import UtcD1Context, load_or_build_context

UTC = timezone.utc
SYMBOL = "XAUUSD"
STRATEGY_ID = "XAU_V24_CHAMPION_DEMO_V1"
DATA_CONTRACT = "XAU_V24_CHAMPION_FORWARD_V2_UTC_D1"
WORKER_NAME = "ctrader_demo_xau_v24_champion_candidate_producer"

D1_COMPONENT = "V20_D1_TSMOM_C1_R200"
L12_COMPONENT = "V20_M15_L12_ADX12_D1_R150"
L20_COMPONENT = "V20_M15_L20_ADX15_D1_R200"

M15_MAX_HOLD_BARS = 16
D1_MAX_HOLD_BARS = 30
D1_ENTRY_GRACE_SECONDS = 30 * 60
M15_ENTRY_GRACE_SECONDS = 3 * 60
STOP_BUFFER_ATR = 0.15
MIN_RISK_ATR = 0.50
SCORE = 60.0

_COMPONENT_SPEC = {
    D1_COMPONENT: {
        "priority": 2,
        "setup_type": "V24_D1",
        "timeframe": "D1",
        "max_hold_bars": D1_MAX_HOLD_BARS,
        "reward_r": 2.0,
    },
    L12_COMPONENT: {
        "priority": 1,
        "setup_type": "V24_L12",
        "timeframe": "M15",
        "max_hold_bars": M15_MAX_HOLD_BARS,
        "reward_r": 1.5,
        "lookback": 12,
        "h1_adx_min": 12.0,
        "body_atr_min": 0.50,
        "cooldown_bars": 3,
    },
    L20_COMPONENT: {
        "priority": 3,
        "setup_type": "V24_L20",
        "timeframe": "M15",
        "max_hold_bars": M15_MAX_HOLD_BARS,
        "reward_r": 2.0,
        "lookback": 20,
        "h1_adx_min": 15.0,
        "body_atr_min": 0.55,
        "cooldown_bars": 4,
    },
}


@dataclass(frozen=True, slots=True)
class ChampionCandidate:
    component_id: str
    direction: str
    signal_bar_at: datetime
    entry_at: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_r: float
    atr: float

    @property
    def priority(self) -> int:
        return int(_COMPONENT_SPEC[self.component_id]["priority"])

    @property
    def setup_type(self) -> str:
        return str(_COMPONENT_SPEC[self.component_id]["setup_type"])

    @property
    def timeframe(self) -> str:
        return str(_COMPONENT_SPEC[self.component_id]["timeframe"])

    @property
    def max_hold_bars(self) -> int:
        return int(_COMPONENT_SPEC[self.component_id]["max_hold_bars"])


def _ema_seeded(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 1:
        raise ValueError("V24_EMA_PERIOD_INVALID")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(v) for v in values[:period]) / float(period)
    out: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (period + 1.0)
    value = seed
    for raw in values[period:]:
        value = alpha * float(raw) + (1.0 - alpha) * value
        out.append(value)
    return tuple(out)


def _rma(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("V24_RMA_PERIOD_INVALID")
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(v) for v in values[:period]) / float(period)
    out: list[float | None] = [None] * (period - 1) + [seed]
    value = seed
    for raw in values[period:]:
        value = ((value * (period - 1)) + float(raw)) / float(period)
        out.append(value)
    return tuple(out)


def _indicator_series(rows: Sequence[Bar]) -> dict[str, tuple[float | None, ...]]:
    values = tuple(rows)
    if len(values) < 2:
        return {
            "ema20": tuple(None for _ in values),
            "ema50": tuple(None for _ in values),
            "atr": tuple(None for _ in values),
            "plus_di": tuple(None for _ in values),
            "minus_di": tuple(None for _ in values),
            "adx": tuple(None for _ in values),
        }
    closes = [float(x.close) for x in values]
    ema20 = _ema_seeded(closes, 20)
    ema50 = _ema_seeded(closes, 50)

    trs: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    previous = values[0]
    for current in values[1:]:
        up_move = float(current.high) - float(previous.high)
        down_move = float(previous.low) - float(current.low)
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
        )
        previous = current

    tr_rma = _rma(trs, 14)
    plus_rma = _rma(plus_dm, 14)
    minus_rma = _rma(minus_dm, 14)
    atr_values: list[float | None] = [None]
    plus_values: list[float | None] = [None]
    minus_values: list[float | None] = [None]
    dx_values: list[float] = []
    dx_indexes: list[int] = []

    for index, (tr, plus, minus) in enumerate(
        zip(tr_rma, plus_rma, minus_rma), start=1
    ):
        atr_values.append(None if tr is None else float(tr))
        if tr is None or plus is None or minus is None or float(tr) <= 0:
            plus_values.append(None)
            minus_values.append(None)
            continue
        pdi = 100.0 * float(plus) / float(tr)
        mdi = 100.0 * float(minus) / float(tr)
        plus_values.append(pdi)
        minus_values.append(mdi)
        denom = pdi + mdi
        dx_values.append(0.0 if denom <= 1e-12 else 100.0 * abs(pdi - mdi) / denom)
        dx_indexes.append(index)

    adx_values: list[float | None] = [None] * len(values)
    adx_rma = _rma(dx_values, 14)
    for index, value in zip(dx_indexes, adx_rma):
        if value is not None:
            adx_values[index] = float(value)

    while len(atr_values) < len(values):
        atr_values.append(None)
    while len(plus_values) < len(values):
        plus_values.append(None)
    while len(minus_values) < len(values):
        minus_values.append(None)

    return {
        "ema20": ema20,
        "ema50": ema50,
        "atr": tuple(atr_values[: len(values)]),
        "plus_di": tuple(plus_values[: len(values)]),
        "minus_di": tuple(minus_values[: len(values)]),
        "adx": tuple(adx_values),
    }


def _next_raw_bar(rows: Sequence[Bar], signal_at: datetime) -> Bar | None:
    target = ensure_utc(signal_at)
    for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp)):
        if ensure_utc(row.timestamp) > target:
            return row
    return None


def _within(now: datetime, start: datetime, seconds: int) -> bool:
    current = ensure_utc(now)
    begin = ensure_utc(start)
    return begin <= current <= begin + timedelta(seconds=int(seconds))


def _first_bar_for_utc_day(rows: Sequence[Bar], target_day: date) -> Bar | None:
    matches = [
        row
        for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp).date() == target_day
    ]
    return matches[0] if matches else None


def _d1_candidate(
    context: UtcD1Context,
    raw_m15: Sequence[Bar],
    *,
    now: datetime,
) -> ChampionCandidate | None:
    direction = context.direction
    atr = float(context.atr14)
    if direction not in {"LONG", "SHORT"} or not isfinite(atr) or atr <= 0:
        return None

    current_day = ensure_utc(now).date()
    if context.target_day != current_day or context.signal_day >= current_day:
        return None
    entry_bar = _first_bar_for_utc_day(raw_m15, current_day)
    if entry_bar is None:
        return None
    entry_at = ensure_utc(entry_bar.timestamp)
    if not _within(now, entry_at, D1_ENTRY_GRACE_SECONDS):
        return None

    entry = float(entry_bar.open)
    risk = 2.0 * atr
    if direction == "LONG":
        stop = entry - risk
        target = entry + 2.0 * risk
    else:
        stop = entry + risk
        target = entry - 2.0 * risk
    return ChampionCandidate(
        component_id=D1_COMPONENT,
        direction=direction,
        signal_bar_at=datetime.combine(context.signal_day, datetime.min.time(), tzinfo=UTC),
        entry_at=entry_at,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        reward_r=2.0,
        atr=atr,
    )


def _h1_bias(rows: Sequence[Bar], *, adx_min: float) -> str | None:
    bars = tuple(rows)
    if len(bars) < 61:
        return None
    ind = _indicator_series(bars)
    i = len(bars) - 1
    vals = (
        ind["ema20"][i],
        ind["ema50"][i],
        ind["adx"][i],
        ind["plus_di"][i],
        ind["minus_di"][i],
    )
    if any(v is None for v in vals):
        return None
    ema20, ema50, adx, plus_di, minus_di = (float(v) for v in vals)
    if adx < float(adx_min):
        return None
    close = float(bars[-1].close)
    long_ok = close > ema20 > ema50 and plus_di > minus_di
    short_ok = close < ema20 < ema50 and minus_di > plus_di
    if long_ok == short_ok:
        return None
    return "LONG" if long_ok else "SHORT"


def _m15_candidate(
    component_id: str,
    raw_m15: Sequence[Bar],
    raw_h1: Sequence[Bar],
    d1_direction: str | None,
    *,
    now: datetime,
) -> ChampionCandidate | None:
    spec = _COMPONENT_SPEC[component_id]
    closed_m15 = _closed_bars(raw_m15, as_of=now, timeframe_seconds=900)
    lookback = int(spec["lookback"])
    if len(closed_m15) < max(80, lookback + 6):
        return None
    signal_bar = closed_m15[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    if signal_at.hour == 21:
        return None
    entry_bar = _next_raw_bar(raw_m15, signal_at)
    if entry_bar is None:
        return None
    entry_at = ensure_utc(entry_bar.timestamp)
    if not _within(now, entry_at, M15_ENTRY_GRACE_SECONDS):
        return None

    signal_close_at = signal_at + timedelta(minutes=15)
    closed_h1 = _closed_bars(raw_h1, as_of=signal_close_at, timeframe_seconds=3600)
    if len(closed_h1) < 61:
        return None
    h1_direction = _h1_bias(closed_h1, adx_min=float(spec["h1_adx_min"]))
    if h1_direction is None or d1_direction != h1_direction:
        return None

    ind = _indicator_series(closed_m15)
    atr_raw = ind["atr"][-1]
    if atr_raw is None:
        return None
    atr = float(atr_raw)
    if not isfinite(atr) or atr <= 0:
        return None
    body = abs(float(signal_bar.close) - float(signal_bar.open))
    candle_range = float(signal_bar.high) - float(signal_bar.low)
    if candle_range <= 0 or body < float(spec["body_atr_min"]) * atr:
        return None

    prior = closed_m15[-(lookback + 1):-1]
    if len(prior) != lookback:
        return None
    upper = max(float(x.high) for x in prior)
    lower = min(float(x.low) for x in prior)
    local = closed_m15[-6:]
    direction = None
    stop = None
    if (
        h1_direction == "LONG"
        and float(signal_bar.close) > upper
        and (float(signal_bar.close) - float(signal_bar.low)) / candle_range >= 0.68
    ):
        direction = "LONG"
        stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
    elif (
        h1_direction == "SHORT"
        and float(signal_bar.close) < lower
        and (float(signal_bar.high) - float(signal_bar.close)) / candle_range >= 0.68
    ):
        direction = "SHORT"
        stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
    if direction is None or stop is None:
        return None

    entry = float(entry_bar.open)
    risk = entry - stop if direction == "LONG" else stop - entry
    if not isfinite(risk) or risk < MIN_RISK_ATR * atr:
        return None
    reward_r = float(spec["reward_r"])
    target = entry + reward_r * risk if direction == "LONG" else entry - reward_r * risk
    if target <= 0:
        return None
    return ChampionCandidate(
        component_id=component_id,
        direction=direction,
        signal_bar_at=signal_at,
        entry_at=entry_at,
        entry_price=entry,
        stop_loss=float(stop),
        take_profit=float(target),
        reward_r=reward_r,
        atr=atr,
    )


def _history_window(now: datetime, timeframe_seconds: int, count: int, factor: float) -> datetime:
    return ensure_utc(now) - timedelta(seconds=timeframe_seconds * count * factor)


def _latest_geometry_payloads(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,code,event_type,payload")
        .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
        .eq("code", STRATEGY_ID)
        .order("observed_at", desc=True)
        .limit(120)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _already_emitted(
    history: Sequence[dict[str, Any]],
    candidate: ChampionCandidate,
) -> bool:
    target = candidate.signal_bar_at.isoformat()
    for row in history:
        payload = dict(row.get("payload") or {})
        if (
            str(payload.get("component_id") or "") == candidate.component_id
            and str(payload.get("signal_bar_at") or "") == target
        ):
            return True
    return False


def _cooldown_ok(
    history: Sequence[dict[str, Any]],
    candidate: ChampionCandidate,
) -> bool:
    if candidate.component_id == D1_COMPONENT:
        return True
    cooldown = int(_COMPONENT_SPEC[candidate.component_id]["cooldown_bars"])
    latest: datetime | None = None
    for row in history:
        payload = dict(row.get("payload") or {})
        if str(payload.get("component_id") or "") != candidate.component_id:
            continue
        raw = payload.get("signal_bar_at")
        if not raw:
            continue
        try:
            stamp = ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except ValueError:
            continue
        if latest is None or stamp > latest:
            latest = stamp
    if latest is None:
        return True
    # Historical V20 counts completed M15 bars. During continuous trading this
    # equals elapsed 15-minute slots; weekend/session gaps can only make the live
    # gate more permissive after a long closure, which is the intended reset.
    elapsed = (candidate.signal_bar_at - latest).total_seconds()
    return elapsed >= cooldown * 900


def _dedupe(candidates: Sequence[ChampionCandidate]) -> tuple[ChampionCandidate, ...]:
    chosen: dict[tuple[datetime, str], ChampionCandidate] = {}
    for candidate in candidates:
        key = (ensure_utc(candidate.entry_at), candidate.direction)
        current = chosen.get(key)
        if current is None or candidate.priority > current.priority:
            chosen[key] = candidate
    return tuple(
        sorted(
            chosen.values(),
            key=lambda x: (ensure_utc(x.entry_at), -x.priority, x.component_id),
        )
    )


def _signal_row(run_id: str, candidate: ChampionCandidate, *, now: datetime, ttl: float) -> dict[str, Any]:
    half = max(candidate.entry_price * 1e-7, candidate.atr * 0.001)
    return {
        "run_id": run_id,
        "observed_at": ensure_utc(now).isoformat(),
        "symbol": SYMBOL,
        "direction": candidate.direction,
        "setup_type": candidate.setup_type,
        "state": "EXECUTION_READY",
        "pair_score": SCORE,
        "execution_score": SCORE,
        "final_score": SCORE,
        "entry_low": candidate.entry_price - half,
        "entry_high": candidate.entry_price + half,
        "sl": candidate.stop_loss,
        "tp1": None,
        "tp2": candidate.take_profit,
        "tp3": None,
        "rr1": None,
        "rr2": candidate.reward_r,
        "rr3": None,
        "macro_bias": candidate.direction,
        "h4_bias": None,
        "h1_bias": candidate.direction,
        "active_guards": [],
        "data_coverage": 1.0,
        "expires_at": (ensure_utc(now) + timedelta(seconds=ttl)).isoformat(),
    }


def _persist_geometry(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
    row: dict[str, Any],
    candidate: ChampionCandidate,
) -> None:
    payload = {
        "signal_id": str(row["id"]),
        "run_id": row.get("run_id"),
        "symbol": SYMBOL,
        "direction": candidate.direction,
        "strategy_id": STRATEGY_ID,
        "component_id": candidate.component_id,
        "signal_bar_at": candidate.signal_bar_at.isoformat(),
        "entry_at": candidate.entry_at.isoformat(),
        "entry_mode": candidate.component_id,
        "timeframe": candidate.timeframe,
        "max_hold_bars": candidate.max_hold_bars,
        "exit_model": (
            "D1_FIXED_2ATR_STOP_2R_MAX30"
            if candidate.component_id == D1_COMPONENT
            else f"M15_STRUCTURAL_STOP_{candidate.reward_r:g}R_MAX16"
        ),
        "entry_low": row.get("entry_low"),
        "entry_high": row.get("entry_high"),
        "planned_entry": candidate.entry_price,
        "planned_sl": candidate.stop_loss,
        "planned_tp1": None,
        "planned_tp2": candidate.take_profit,
        "rr1": None,
        "rr2": candidate.reward_r,
        "source": DATA_CONTRACT,
        "execution_influence": True,
        "environment": "DEMO",
        "live_execution_enabled": False,
        "lineage": {
            "champion": "V20/V24 D1_PLUS_L12_L20",
            "v110_v121": "research attribution/causal-health lineage",
            "v123": "shadow onset research; not an execution gate",
        },
    }
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=str(row["id"]),
        broker_order_id=f"GEOMETRY:{row['id']}",
        event_type="DEMO_SIGNAL_GEOMETRY",
        accepted=True,
        code=STRATEGY_ID,
        message="XAU V24 champion DEMO geometry persisted",
        payload=payload,
    )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V24_CHAMPION_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V24_CHAMPION_REQUIRE_DEMO")

    account_id = (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )
    if not account_id:
        raise SystemExit("XAU_V24_CHAMPION_ACCOUNT_ID_REQUIRED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    run_id = store.start_scanner_run(
        mode="DEMO_ONLY",
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        data_contract_version=DATA_CONTRACT,
        started_at=now,
    )
    error: str | None = None
    candidates: tuple[ChampionCandidate, ...] = ()
    persisted: list[dict[str, Any]] = []
    context_by_day: dict[date, UtcD1Context] = {}
    try:
        feed.ensure_connected()
        raw_h1 = tuple(
            feed.historical_bars(
                SYMBOL,
                "H1",
                from_time=_history_window(now, 3600, 180, 1.35),
                to_time=now,
                count=180,
            )
        )
        raw_m15 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=_history_window(now, 900, 360, 1.25),
                to_time=now,
                count=360,
            )
        )

        closed_m15 = _closed_bars(raw_m15, as_of=now, timeframe_seconds=900)
        def context_for(day: date) -> UtcD1Context:
            if day not in context_by_day:
                context_by_day[day] = load_or_build_context(
                    store=store,
                    feed=feed,
                    account_id=account_id,
                    target_day=day,
                )
            return context_by_day[day]

        current_context = context_for(now.date())
        signal_day = (
            ensure_utc(closed_m15[-1].timestamp).date()
            if closed_m15
            else now.date()
        )
        signal_context = context_for(signal_day)

        history = _latest_geometry_payloads(store)
        raw_candidates = [
            value
            for value in (
                _d1_candidate(current_context, raw_m15, now=now),
                _m15_candidate(
                    L12_COMPONENT,
                    raw_m15,
                    raw_h1,
                    signal_context.direction,
                    now=now,
                ),
                _m15_candidate(
                    L20_COMPONENT,
                    raw_m15,
                    raw_h1,
                    signal_context.direction,
                    now=now,
                ),
            )
            if value is not None
        ]
        candidates = _dedupe(
            tuple(
                candidate
                for candidate in raw_candidates
                if not _already_emitted(history, candidate)
                and _cooldown_ok(history, candidate)
            )
        )

        ttl = min(300.0, float(policy.order.get("max_signal_age_seconds", 300)))
        rows = [_signal_row(run_id, candidate, now=now, ttl=ttl) for candidate in candidates]
        if rows:
            response = store.client.table("signals").insert(rows).execute()
            persisted = [dict(row) for row in (response.data or [])]
            if len(persisted) != len(candidates):
                raise RuntimeError("XAU_V24_CHAMPION_SIGNAL_INSERT_COUNT_MISMATCH")
            by_setup = {candidate.setup_type: candidate for candidate in candidates}
            for row in persisted:
                setup = str(row.get("setup_type") or "")
                candidate = by_setup.get(setup)
                if candidate is None:
                    raise RuntimeError("XAU_V24_CHAMPION_PERSISTED_COMPONENT_UNKNOWN")
                _persist_geometry(
                    store,
                    account_id=account_id,
                    row=row,
                    candidate=candidate,
                )

        store.finish_scanner_run(run_id, status="COMPLETED", finished_at=datetime.now(tz=UTC))
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        try:
            store.finish_scanner_run(run_id, status="FAILED", finished_at=datetime.now(tz=UTC))
        except Exception:
            pass
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "strategy_id": STRATEGY_ID,
            "data_contract": DATA_CONTRACT,
            "environment": "DEMO",
            "execution_influence": True,
            "live_execution_enabled": False,
            "components": [D1_COMPONENT, L12_COMPONENT, L20_COMPONENT],
            "candidate_count": len(candidates),
            "signals_written": len(persisted),
            "score": SCORE,
            "risk_policy": "shared bounded DEMO executor",
            "d1_source": "UTC_CALENDAR_D1_FROM_CTRADER_H1_PARITY_V124",
            "d1_contexts": [
                {
                    "target_day": context.target_day.isoformat(),
                    "signal_day": context.signal_day.isoformat(),
                    "direction": context.direction,
                    "atr14": context.atr14,
                    "source": context.source,
                    "history_days": context.history_days,
                }
                for context in sorted(context_by_day.values(), key=lambda x: x.target_day)
            ],
            "v110_v121": "lineage/benchmark",
            "v123": "shadow only",
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_V24_CHAMPION "
        f"healthy={int(healthy)} candidates={len(candidates)} "
        f"signals={len(persisted)} strategy={STRATEGY_ID} "
        "d1_source=UTC_CALENDAR_D1_FROM_CTRADER_H1_PARITY_V124"
    )
    for candidate in candidates:
        print(
            "CTRADER_DEMO_XAU_V24_COMPONENT "
            f"component={candidate.component_id} direction={candidate.direction} "
            f"signal_bar={candidate.signal_bar_at.isoformat()} "
            f"entry_at={candidate.entry_at.isoformat()} rr={candidate.reward_r:g}"
        )
    if error is not None:
        print(f"CTRADER_DEMO_XAU_V24_ERROR {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
