from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .config import load_project_config
from .demo_five_core_candidate_producer import (
    _history_window_seconds,
    _subset_cfg,
    _with_history_requirements,
)
from .demo_five_core_router import (
    D1_ENTRY_WINDOW_SECONDS,
    D1_MAX_HOLD_BARS,
    D1_STOP_ATR,
    D1_TARGET_ATR,
    PAIR_STRATEGY_IDS,
    evaluate_xau_d1_tsmom_60_200,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

XAU_SYMBOL = "XAUUSD"
STRATEGY_ID = PAIR_STRATEGY_IDS[XAU_SYMBOL]
PAPER_SETUP_TYPE = "D1_TSMOM_60_200_PAPER_V1"
PAPER_CONTRACT = "XAU_D1_TSMOM_PAPER_FORWARD_V1"
WORKER_NAME = "ctrader_demo_xau_d1_tsmom_paper_forward"
OPEN_EVENT = "DEMO_XAU_D1_PAPER_OPEN"
CLOSE_EVENT = "DEMO_XAU_D1_PAPER_CLOSE"
REQUEST_COUNT = 280
ENTRY_GRACE = timedelta(hours=6)
FORWARD_EPOCH = datetime(2026, 9, 13, tzinfo=UTC)
STRESS_COST_USD = 0.35


@dataclass(frozen=True, slots=True)
class PaperExit:
    exit_time: datetime
    exit_price: float
    gross_r: float
    net_r: float
    mae_r: float
    mfe_r: float
    reason: str


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _bar_at(bars: Sequence[Bar], timestamp: datetime) -> Bar | None:
    target = ensure_utc(timestamp)
    for row in bars:
        if ensure_utc(row.timestamp) == target:
            return row
    return None


def _paper_excursions(
    bars: Sequence[Bar],
    *,
    direction: str,
    entry_price: float,
    risk_price: float,
) -> tuple[float, float]:
    if not bars or risk_price <= 0:
        return 0.0, 0.0
    sign = 1.0 if direction == "LONG" else -1.0
    favorable: list[float] = []
    adverse: list[float] = []
    for row in bars:
        if direction == "LONG":
            favorable.append((float(row.high) - entry_price) / risk_price)
            adverse.append((float(row.low) - entry_price) / risk_price)
        else:
            favorable.append((entry_price - float(row.low)) / risk_price)
            adverse.append((entry_price - float(row.high)) / risk_price)
    del sign
    return min(adverse), max(favorable)


def evaluate_paper_exit(
    bars: Sequence[Bar],
    *,
    direction: str,
    entry_time: datetime,
    entry_price: float,
    stop: float,
    target: float,
    stress_cost_usd: float = STRESS_COST_USD,
    max_hold_bars: int = D1_MAX_HOLD_BARS,
) -> PaperExit | None:
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if max_hold_bars <= 0:
        raise ValueError("max_hold_bars must be positive")
    risk_price = abs(float(entry_price) - float(stop))
    if not isfinite(risk_price) or risk_price <= 0:
        raise ValueError("paper risk distance must be positive")

    ordered = tuple(
        row
        for row in sorted(bars, key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) >= ensure_utc(entry_time)
    )
    if not ordered:
        return None

    inspected: list[Bar] = []
    for row in ordered[:max_hold_bars]:
        inspected.append(row)
        if direction == "LONG":
            stop_hit = float(row.low) <= stop
            target_hit = float(row.high) >= target
        else:
            stop_hit = float(row.high) >= stop
            target_hit = float(row.low) <= target

        # Frozen historical contract: same-bar ambiguity is STOP_FIRST.
        if stop_hit:
            mae_r, mfe_r = _paper_excursions(
                inspected,
                direction=direction,
                entry_price=entry_price,
                risk_price=risk_price,
            )
            gross_r = -1.0
            return PaperExit(
                exit_time=ensure_utc(row.timestamp),
                exit_price=float(stop),
                gross_r=gross_r,
                net_r=gross_r - float(stress_cost_usd) / risk_price,
                mae_r=mae_r,
                mfe_r=mfe_r,
                reason="STOP",
            )
        if target_hit:
            mae_r, mfe_r = _paper_excursions(
                inspected,
                direction=direction,
                entry_price=entry_price,
                risk_price=risk_price,
            )
            gross_r = 2.0
            return PaperExit(
                exit_time=ensure_utc(row.timestamp),
                exit_price=float(target),
                gross_r=gross_r,
                net_r=gross_r - float(stress_cost_usd) / risk_price,
                mae_r=mae_r,
                mfe_r=mfe_r,
                reason="TARGET",
            )

    # A time exit is knowable only once the next D1 bar exists, proving that
    # the max-hold bar has closed. This avoids using an incomplete bar close.
    if len(ordered) > max_hold_bars:
        time_bar = ordered[max_hold_bars - 1]
        next_bar = ordered[max_hold_bars]
        sign = 1.0 if direction == "LONG" else -1.0
        gross_r = sign * (float(time_bar.close) - entry_price) / risk_price
        mae_r, mfe_r = _paper_excursions(
            ordered[:max_hold_bars],
            direction=direction,
            entry_price=entry_price,
            risk_price=risk_price,
        )
        return PaperExit(
            exit_time=ensure_utc(next_bar.timestamp),
            exit_price=float(time_bar.close),
            gross_r=gross_r,
            net_r=gross_r - float(stress_cost_usd) / risk_price,
            mae_r=mae_r,
            mfe_r=mfe_r,
            reason="TIME_MAX30",
        )
    return None


def _open_paper_rows(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("paper_trades")
        .select("id,signal_id,entry_time,entry_price,status")
        .eq("status", "OPEN")
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _signal_row(store: SupabaseOperationalStore, signal_id: str) -> dict[str, Any] | None:
    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,symbol,direction,setup_type,state,entry_low,entry_high,"
            "sl,tp2,rr2"
        )
        .eq("id", signal_id)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None
    return dict(rows[0])


def _close_existing_paper(
    store: SupabaseOperationalStore,
    bars: Sequence[Bar],
) -> int:
    closed = 0
    for paper in _open_paper_rows(store):
        signal = _signal_row(store, str(paper["signal_id"]))
        if not signal:
            continue
        if str(signal.get("setup_type")) != PAPER_SETUP_TYPE:
            continue
        if str(signal.get("symbol", "")).upper() != XAU_SYMBOL:
            continue
        stop = float(signal["sl"])
        target = float(signal["tp2"])
        outcome = evaluate_paper_exit(
            bars,
            direction=str(signal["direction"]),
            entry_time=datetime.fromisoformat(str(paper["entry_time"]).replace("Z", "+00:00")),
            entry_price=float(paper["entry_price"]),
            stop=stop,
            target=target,
        )
        if outcome is None:
            continue
        (
            store.client.table("paper_trades")
            .update(
                {
                    "exit_time": outcome.exit_time.isoformat(),
                    "exit_price": outcome.exit_price,
                    "spread_cost": 0.0,
                    "commission": STRESS_COST_USD,
                    "slippage": 0.0,
                    "result_r": outcome.net_r,
                    "mae_r": outcome.mae_r,
                    "mfe_r": outcome.mfe_r,
                    "status": "CLOSED",
                }
            )
            .eq("id", str(paper["id"]))
            .eq("status", "OPEN")
            .execute()
        )
        (
            store.client.table("signals")
            .update({"state": "COOLDOWN"})
            .eq("id", str(paper["signal_id"]))
            .execute()
        )
        account = _account_label()
        if account:
            store.record_order_event(
                backend="CTRADER",
                account_id=account,
                signal_key=f"PAPER_CLOSE:{paper['id']}",
                event_type=CLOSE_EVENT,
                accepted=None,
                code=STRATEGY_ID,
                message="XAU D1 exact-rule paper trade closed; no broker order",
                payload={
                    "contract": PAPER_CONTRACT,
                    "execution_influence": False,
                    "paper_trade_id": str(paper["id"]),
                    "exit_reason": outcome.reason,
                    "gross_r": outcome.gross_r,
                    "stress_net_r": outcome.net_r,
                },
            )
        closed += 1
    return closed


def _existing_signal_for_bar(
    store: SupabaseOperationalStore,
    signal_bar_at: datetime,
) -> dict[str, Any] | None:
    response = (
        store.client.table("signals")
        .select("id,state")
        .eq("symbol", XAU_SYMBOL)
        .eq("setup_type", PAPER_SETUP_TYPE)
        .eq("observed_at", ensure_utc(signal_bar_at).isoformat())
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return None if not rows else dict(rows[0])


def _paper_exists_for_signal(store: SupabaseOperationalStore, signal_id: str) -> bool:
    response = (
        store.client.table("paper_trades")
        .select("id")
        .eq("signal_id", signal_id)
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


def _create_paper_for_signal(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    entry_time: datetime,
    entry_price: float,
) -> bool:
    if _paper_exists_for_signal(store, signal_id):
        return False
    response = (
        store.client.table("paper_trades")
        .insert(
            {
                "signal_id": signal_id,
                "entry_time": ensure_utc(entry_time).isoformat(),
                "entry_price": float(entry_price),
                "spread_cost": 0.0,
                "commission": STRESS_COST_USD,
                "slippage": 0.0,
                "status": "OPEN",
            }
        )
        .execute()
    )
    return bool(response.data or [])


def _maybe_open_new_paper(
    store: SupabaseOperationalStore,
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> bool:
    if any(
        _signal_row(store, str(row["signal_id"]))
        and str(_signal_row(store, str(row["signal_id"])).get("setup_type"))
        == PAPER_SETUP_TYPE
        for row in _open_paper_rows(store)
    ):
        return False

    signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=as_of)
    if signal.direction not in {"LONG", "SHORT"}:
        return False
    if signal.signal_bar_at is None or signal.next_entry_at is None or signal.atr is None:
        return False
    signal_bar_at = ensure_utc(signal.signal_bar_at)
    entry_at = ensure_utc(signal.next_entry_at)
    now = ensure_utc(as_of)
    if signal_bar_at < FORWARD_EPOCH:
        return False
    if not entry_at <= now <= entry_at + ENTRY_GRACE:
        return False
    entry_bar = _bar_at(bars, entry_at)
    if entry_bar is None:
        return False

    atr = float(signal.atr)
    if not isfinite(atr) or atr <= 0:
        return False
    entry = float(entry_bar.open)
    if signal.direction == "LONG":
        stop = entry - D1_STOP_ATR * atr
        target = entry + D1_TARGET_ATR * atr
    else:
        stop = entry + D1_STOP_ATR * atr
        target = entry - D1_TARGET_ATR * atr

    existing = _existing_signal_for_bar(store, signal_bar_at)
    if existing is None:
        response = (
            store.client.table("signals")
            .insert(
                {
                    "observed_at": signal_bar_at.isoformat(),
                    "symbol": XAU_SYMBOL,
                    "direction": signal.direction,
                    "setup_type": PAPER_SETUP_TYPE,
                    "state": "WATCH",
                    "pair_score": 60.0,
                    "execution_score": 0.0,
                    "final_score": 60.0,
                    "entry_low": entry,
                    "entry_high": entry,
                    "sl": stop,
                    "tp2": target,
                    "rr2": D1_TARGET_ATR / D1_STOP_ATR,
                    "active_guards": ["PAPER_ONLY_NO_BROKER_AUTHORITY"],
                    "data_coverage": 1.0,
                    "expires_at": (entry_at + ENTRY_GRACE).isoformat(),
                }
            )
            .execute()
        )
        rows = list(response.data or [])
        if len(rows) != 1 or not rows[0].get("id"):
            raise RuntimeError("paper signal insert did not return exactly one id")
        signal_id = str(rows[0]["id"])
    else:
        signal_id = str(existing["id"])

    created = _create_paper_for_signal(
        store,
        signal_id=signal_id,
        entry_time=entry_at,
        entry_price=entry,
    )
    if created:
        account = _account_label()
        if account:
            digest = hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:24]
            store.record_order_event(
                backend="CTRADER",
                account_id=account,
                signal_key=f"PAPER_OPEN:{digest}",
                event_type=OPEN_EVENT,
                accepted=None,
                code=STRATEGY_ID,
                message="XAU D1 exact-rule paper trade opened; no broker order",
                payload={
                    "contract": PAPER_CONTRACT,
                    "execution_influence": False,
                    "signal_id": signal_id,
                    "signal_bar_at": signal_bar_at.isoformat(),
                    "entry_time": entry_at.isoformat(),
                    "entry_price": entry,
                    "stop": stop,
                    "target": target,
                    "stress_cost_usd": STRESS_COST_USD,
                    "entry_window_seconds_reference": D1_ENTRY_WINDOW_SECONDS,
                },
            )
    return created


def run() -> int:
    cfg = _with_history_requirements(
        _subset_cfg(load_project_config(None), (XAU_SYMBOL,))
    )
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_PAPER_FORWARD_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_PAPER_FORWARD_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, (XAU_SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    opened = False
    closed = 0
    error: str | None = None
    bars: tuple[Bar, ...] = ()
    try:
        feed.ensure_connected()
        timeframe_seconds = int(cfg.timeframes["D1"])
        start = as_of - timedelta(
            seconds=_history_window_seconds("D1", REQUEST_COUNT, timeframe_seconds)
        )
        bars = tuple(
            feed.historical_bars(
                XAU_SYMBOL,
                "D1",
                from_time=start,
                to_time=as_of,
                count=REQUEST_COUNT,
            )
        )
        closed = _close_existing_paper(store, bars)
        opened = _maybe_open_new_paper(store, bars, as_of=as_of)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
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
            "contract": PAPER_CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "broker_order_submission": False,
            "strategy_id": STRATEGY_ID,
            "forward_epoch": FORWARD_EPOCH.isoformat(),
            "bars": len(bars),
            "opened": opened,
            "closed": closed,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_D1_TSMOM_PAPER_FORWARD "
        f"healthy={healthy} bars={len(bars)} opened={opened} closed={closed}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
