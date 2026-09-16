from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .demo_xau_m15_ema_reversal_recovery import (
    ENTRY_WINDOW_SECONDS,
    STRATEGY_CONTRACT,
    STRATEGY_ID,
    SYMBOL,
    TP1_R,
    TP2_R,
    evaluate_xau_m15_ema_reversal_recovery,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

# Keep the V1 setup label so already-open/closed LONG paper rows remain in the
# same family and can still be reconciled after the bidirectional contract ships.
PAPER_SETUP_TYPE = "XAU_M15_EMA_REVERSAL_PAPER_V1"
FORWARD_EVIDENCE_CONTRACT = "XAU_M15_EMA_REVERSAL_FORWARD_EVIDENCE_V2"
WORKER_NAME = "ctrader_demo_xau_m15_ema_reversal_forward_evidence"
EVALUATION_EVENT = "DEMO_XAU_M15_EMA_REVERSAL_EVALUATION"
OPEN_EVENT = "DEMO_XAU_M15_EMA_REVERSAL_PAPER_OPEN"
CLOSE_EVENT = "DEMO_XAU_M15_EMA_REVERSAL_PAPER_CLOSE"
REQUEST_COUNT = 420
LOOKBACK_DAYS = 7
FORWARD_EPOCH = datetime(2026, 9, 15, 22, 12, 50, tzinfo=UTC)
SHORT_FORWARD_EPOCH = datetime(2026, 9, 16, 1, 30, 0, tzinfo=UTC)
MAX_METRIC_ROWS = 500


@dataclass(frozen=True, slots=True)
class PaperExit:
    exit_time: datetime
    exit_price: float
    result_r: float
    mae_r: float
    mfe_r: float
    tp1_touched: bool
    reason: str


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _closed_rows(bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
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
    normalized = str(direction).upper()
    if normalized == "LONG":
        adverse = [(float(row.low) - entry_price) / risk_price for row in bars]
        favorable = [(float(row.high) - entry_price) / risk_price for row in bars]
    elif normalized == "SHORT":
        adverse = [(entry_price - float(row.high)) / risk_price for row in bars]
        favorable = [(entry_price - float(row.low)) / risk_price for row in bars]
    else:
        raise ValueError("paper direction must be LONG or SHORT")
    return min(adverse), max(favorable)


def evaluate_paper_exit(
    bars: Sequence[Bar],
    *,
    entry_time: datetime,
    entry_price: float,
    stop: float,
    target: float,
    direction: str = "LONG",
) -> PaperExit | None:
    """Resolve fixed-SL/fixed-TP paper lifecycle for LONG and SHORT.

    Both directions use the same 1R stop and TP2=3R contract. If SL and TP are
    both inside one M15 candle, STOP_FIRST is used conservatively.
    """

    normalized = str(direction).upper()
    if normalized == "LONG":
        risk_price = float(entry_price) - float(stop)
        if float(target) <= float(entry_price):
            raise ValueError("LONG paper target must remain above entry")
    elif normalized == "SHORT":
        risk_price = float(stop) - float(entry_price)
        if float(target) >= float(entry_price):
            raise ValueError("SHORT paper target must remain below entry")
    else:
        raise ValueError("paper direction must be LONG or SHORT")
    if not isfinite(risk_price) or risk_price <= 0:
        raise ValueError("paper risk distance must be positive")

    ordered = tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) >= ensure_utc(entry_time)
    )
    if not ordered:
        return None

    inspected: list[Bar] = []
    for row in ordered:
        inspected.append(row)
        if normalized == "LONG":
            stop_hit = float(row.low) <= float(stop)
            target_hit = float(row.high) >= float(target)
        else:
            stop_hit = float(row.high) >= float(stop)
            target_hit = float(row.low) <= float(target)
        if stop_hit:
            mae_r, mfe_r = _paper_excursions(
                inspected,
                direction=normalized,
                entry_price=float(entry_price),
                risk_price=risk_price,
            )
            return PaperExit(
                exit_time=ensure_utc(row.timestamp),
                exit_price=float(stop),
                result_r=-1.0,
                mae_r=mae_r,
                mfe_r=mfe_r,
                tp1_touched=mfe_r >= TP1_R,
                reason="STOP",
            )
        if target_hit:
            mae_r, mfe_r = _paper_excursions(
                inspected,
                direction=normalized,
                entry_price=float(entry_price),
                risk_price=risk_price,
            )
            return PaperExit(
                exit_time=ensure_utc(row.timestamp),
                exit_price=float(target),
                result_r=TP2_R,
                mae_r=mae_r,
                mfe_r=mfe_r,
                tp1_touched=True,
                reason="TP2",
            )
    return None


def _evaluation_key(signal) -> str | None:
    if signal.signal_bar_at is None:
        return None
    return "|".join(
        (
            ensure_utc(signal.signal_bar_at).isoformat(),
            str(signal.direction or "NONE"),
            str(signal.reason),
            str(signal.contract),
        )
    )


def _already_recorded_evaluation(store: Any, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVALUATION_EVENT)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(120)
            .execute()
        )
    except Exception:
        return True
    return any(
        str(dict(row.get("payload") or {}).get("evaluation_key") or "") == key
        for row in response.data or []
    )


def _persist_evaluation(store: Any, *, signal, key: str) -> bool:
    if _already_recorded_evaluation(store, key):
        return False
    account = _account_label()
    if not account:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_XAU_M15_FORWARD_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:28]
    store.record_order_event(
        backend="CTRADER",
        account_id=account,
        signal_key=f"XAU_M15_EVAL:{digest}",
        broker_order_id=None,
        event_type=EVALUATION_EVENT,
        accepted=None,
        code=STRATEGY_ID,
        message="XAU M15 reversal/recovery forward evaluation; no broker action",
        payload={
            "evaluation_key": key,
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "forward_evidence_contract": FORWARD_EVIDENCE_CONTRACT,
            "strategy_contract": STRATEGY_CONTRACT,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "evaluation": signal.evidence(),
        },
    )
    return True


def _open_paper_rows(store: Any) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("paper_trades")
        .select("id,signal_id,entry_time,entry_price,status")
        .eq("status", "OPEN")
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _signal_row(store: Any, signal_id: str) -> dict[str, Any] | None:
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
    return None if not rows else dict(rows[0])


def _has_open_strategy_paper(store: Any) -> bool:
    for paper in _open_paper_rows(store):
        signal = _signal_row(store, str(paper["signal_id"]))
        if not signal:
            continue
        if (
            str(signal.get("setup_type")) == PAPER_SETUP_TYPE
            and str(signal.get("symbol", "")).upper() == SYMBOL
        ):
            return True
    return False


def _close_existing_papers(store: Any, bars: Sequence[Bar]) -> int:
    closed_count = 0
    for paper in _open_paper_rows(store):
        signal = _signal_row(store, str(paper["signal_id"]))
        if not signal:
            continue
        if (
            str(signal.get("setup_type")) != PAPER_SETUP_TYPE
            or str(signal.get("symbol", "")).upper() != SYMBOL
        ):
            continue
        direction = str(signal.get("direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        outcome = evaluate_paper_exit(
            bars,
            entry_time=datetime.fromisoformat(
                str(paper["entry_time"]).replace("Z", "+00:00")
            ),
            entry_price=float(paper["entry_price"]),
            stop=float(signal["sl"]),
            target=float(signal["tp2"]),
            direction=direction,
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
                    "commission": 0.0,
                    "slippage": 0.0,
                    "result_r": outcome.result_r,
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
                signal_key=f"XAU_M15_PAPER_CLOSE:{paper['id']}",
                broker_order_id=None,
                event_type=CLOSE_EVENT,
                accepted=None,
                code=STRATEGY_ID,
                message="XAU M15 reversal/recovery paper trade closed; no broker action",
                payload={
                    "contract": FORWARD_EVIDENCE_CONTRACT,
                    "execution_influence": False,
                    "paper_trade_id": str(paper["id"]),
                    "direction": direction,
                    "exit": asdict(outcome)
                    | {"exit_time": outcome.exit_time.isoformat()},
                },
            )
        closed_count += 1
    return closed_count


def _existing_paper_signal_for_bar(
    store: Any,
    signal_bar_at: datetime,
    direction: str,
) -> dict[str, Any] | None:
    response = (
        store.client.table("signals")
        .select("id,state")
        .eq("symbol", SYMBOL)
        .eq("setup_type", PAPER_SETUP_TYPE)
        .eq("direction", direction)
        .eq("observed_at", ensure_utc(signal_bar_at).isoformat())
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return None if not rows else dict(rows[0])


def _paper_exists_for_signal(store: Any, signal_id: str) -> bool:
    response = (
        store.client.table("paper_trades")
        .select("id")
        .eq("signal_id", signal_id)
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


def _maybe_open_new_paper(
    store: Any,
    bars: Sequence[Bar],
    *,
    signal,
    as_of: datetime,
) -> bool:
    if _has_open_strategy_paper(store):
        return False
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        return False
    if signal.signal_bar_at is None or signal.next_entry_at is None:
        return False
    direction = str(signal.direction)
    signal_bar_at = ensure_utc(signal.signal_bar_at)
    entry_at = ensure_utc(signal.next_entry_at)
    now = ensure_utc(as_of)
    direction_epoch = SHORT_FORWARD_EPOCH if direction == "SHORT" else FORWARD_EPOCH
    if signal_bar_at < direction_epoch:
        return False
    if not entry_at <= now <= entry_at + timedelta(seconds=ENTRY_WINDOW_SECONDS):
        return False
    entry_bar = _bar_at(bars, entry_at)
    if entry_bar is None:
        return False

    entry = float(entry_bar.open)
    stop = float(signal.structural_stop or 0.0)
    if not (isfinite(entry) and isfinite(stop) and entry > 0.0 and stop > 0.0):
        return False
    if direction == "LONG":
        if stop >= entry:
            return False
        risk = entry - stop
        target = entry + TP2_R * risk
        tp1_reference = entry + TP1_R * risk
    else:
        if stop <= entry:
            return False
        risk = stop - entry
        target = entry - TP2_R * risk
        tp1_reference = entry - TP1_R * risk
        if target <= 0 or tp1_reference <= 0:
            return False

    existing = _existing_paper_signal_for_bar(store, signal_bar_at, direction)
    if existing is None:
        response = (
            store.client.table("signals")
            .insert(
                {
                    "observed_at": signal_bar_at.isoformat(),
                    "symbol": SYMBOL,
                    "direction": direction,
                    "setup_type": PAPER_SETUP_TYPE,
                    "state": "WATCH",
                    "pair_score": 70.0 if direction == "LONG" else -70.0,
                    "execution_score": 0.0,
                    "final_score": 70.0,
                    "entry_low": entry,
                    "entry_high": entry,
                    "sl": stop,
                    "tp2": target,
                    "rr2": TP2_R,
                    "active_guards": ["PAPER_ONLY_NO_BROKER_AUTHORITY"],
                    "data_coverage": 1.0,
                    "expires_at": (
                        entry_at + timedelta(seconds=ENTRY_WINDOW_SECONDS)
                    ).isoformat(),
                }
            )
            .execute()
        )
        rows = list(response.data or [])
        if len(rows) != 1 or not rows[0].get("id"):
            raise RuntimeError("XAU M15 paper signal insert did not return one id")
        signal_id = str(rows[0]["id"])
    else:
        signal_id = str(existing["id"])

    if _paper_exists_for_signal(store, signal_id):
        return False
    response = (
        store.client.table("paper_trades")
        .insert(
            {
                "signal_id": signal_id,
                "entry_time": entry_at.isoformat(),
                "entry_price": entry,
                "spread_cost": 0.0,
                "commission": 0.0,
                "slippage": 0.0,
                "status": "OPEN",
            }
        )
        .execute()
    )
    created = bool(response.data or [])
    if created:
        account = _account_label()
        if account:
            digest = hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:24]
            store.record_order_event(
                backend="CTRADER",
                account_id=account,
                signal_key=f"XAU_M15_PAPER_OPEN:{digest}",
                broker_order_id=None,
                event_type=OPEN_EVENT,
                accepted=None,
                code=STRATEGY_ID,
                message="XAU M15 reversal/recovery paper trade opened; no broker action",
                payload={
                    "contract": FORWARD_EVIDENCE_CONTRACT,
                    "execution_influence": False,
                    "signal_id": signal_id,
                    "direction": direction,
                    "signal_bar_at": signal_bar_at.isoformat(),
                    "entry_time": entry_at.isoformat(),
                    "entry_price": entry,
                    "stop": stop,
                    "tp1_reference": tp1_reference,
                    "tp2": target,
                    "risk_price": risk,
                    "entry_model": "NEXT_M15_BAR_OPEN",
                },
            )
    return created


def _strategy_closed_rows(store: Any) -> list[dict[str, Any]]:
    response = (
        store.client.table("paper_trades")
        .select("id,signal_id,exit_time,result_r,mae_r,mfe_r,status")
        .eq("status", "CLOSED")
        .order("exit_time", desc=False)
        .limit(MAX_METRIC_ROWS)
        .execute()
    )
    selected: list[dict[str, Any]] = []
    for paper in response.data or []:
        signal = _signal_row(store, str(paper["signal_id"]))
        if not signal:
            continue
        if (
            str(signal.get("setup_type")) == PAPER_SETUP_TYPE
            and str(signal.get("symbol", "")).upper() == SYMBOL
        ):
            row = dict(paper)
            row["direction"] = str(signal.get("direction") or "").upper()
            selected.append(row)
    return selected


def summarize_forward_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    results = [float(row["result_r"]) for row in rows if row.get("result_r") is not None]
    if not results:
        return {
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "expectancy_r": None,
            "profit_factor": None,
            "max_drawdown_r": None,
            "tp1_touch_rate": None,
            "promotion_evidence_state": "NO_CLOSED_SAMPLE",
            "promotion_authority": False,
            "minimum_review_sample": 30,
        }

    wins = sum(value > 0.0 for value in results)
    losses = sum(value < 0.0 for value in results)
    gross_profit = sum(value for value in results if value > 0.0)
    gross_loss = -sum(value for value in results if value < 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in results:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    tp1_touches = sum(float(row.get("mfe_r") or 0.0) >= TP1_R for row in rows)
    profit_factor = None if gross_loss <= 0.0 else gross_profit / gross_loss
    expectancy = sum(results) / len(results)
    state = "COLLECTING"
    if len(results) >= 30:
        if (
            expectancy > 0.0
            and profit_factor is not None
            and profit_factor >= 1.15
            and max_dd <= 8.0
        ):
            state = "EVIDENCE_POSITIVE_REVIEW_CANDIDATE"
        else:
            state = "EVIDENCE_NOT_YET_SUPPORTIVE"
    return {
        "closed_trades": len(results),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(results),
        "expectancy_r": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_dd,
        "tp1_touch_rate": tp1_touches / len(results),
        "promotion_evidence_state": state,
        "promotion_authority": False,
        "minimum_review_sample": 30,
    }


def summarize_forward_metrics_by_direction(
    rows: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        direction: summarize_forward_metrics(
            tuple(row for row in rows if str(row.get("direction") or "").upper() == direction)
        )
        for direction in ("LONG", "SHORT")
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_M15_FORWARD_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_M15_FORWARD_EVIDENCE_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    bars: tuple[Bar, ...] = ()
    signal = None
    persisted_evaluation = False
    opened = False
    closed = 0
    metrics: dict[str, Any] = {}
    by_direction: dict[str, dict[str, Any]] = {}
    error: str | None = None
    try:
        feed.ensure_connected()
        bars = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=as_of - timedelta(days=LOOKBACK_DAYS),
                to_time=as_of,
                count=REQUEST_COUNT,
            )
        )
        closed_bars = _closed_rows(bars, as_of=as_of)
        signal = evaluate_xau_m15_ema_reversal_recovery(bars, as_of=as_of)
        key = _evaluation_key(signal)
        if key is not None:
            persisted_evaluation = _persist_evaluation(store, signal=signal, key=key)
        closed = _close_existing_papers(store, closed_bars)
        opened = _maybe_open_new_paper(store, bars, signal=signal, as_of=as_of)
        closed_rows = _strategy_closed_rows(store)
        metrics = summarize_forward_metrics(closed_rows)
        by_direction = summarize_forward_metrics_by_direction(closed_rows)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    signal_reason = None if signal is None else signal.reason
    signal_direction = None if signal is None else signal.direction
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": FORWARD_EVIDENCE_CONTRACT,
            "strategy_id": STRATEGY_ID,
            "strategy_contract": STRATEGY_CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "broker_order_submission": False,
            "promotion_authority": False,
            "supported_directions": ["LONG", "SHORT"],
            "forward_epoch": FORWARD_EPOCH.isoformat(),
            "short_forward_epoch": SHORT_FORWARD_EPOCH.isoformat(),
            "observed_at": as_of.isoformat(),
            "bars_received": len(bars),
            "signal_direction": signal_direction,
            "signal_reason": signal_reason,
            "signal_active": False if signal is None else signal.active,
            "persisted_new_evaluation": persisted_evaluation,
            "paper_opened": opened,
            "paper_closed": closed,
            "metrics": metrics,
            "metrics_by_direction": by_direction,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_M15_REVERSAL_FORWARD_EVIDENCE "
        f"healthy={healthy} bars={len(bars)} direction={signal_direction or 'NONE'} "
        f"reason={signal_reason or 'NONE'} eval_persisted={persisted_evaluation} "
        f"paper_opened={opened} paper_closed={closed} "
        f"sample={metrics.get('closed_trades', 0)} "
        f"long_sample={by_direction.get('LONG', {}).get('closed_trades', 0)} "
        f"short_sample={by_direction.get('SHORT', {}).get('closed_trades', 0)} "
        f"expectancy_r={metrics.get('expectancy_r')} "
        f"pf={metrics.get('profit_factor')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
