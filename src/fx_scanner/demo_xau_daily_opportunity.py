from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_daily_opportunity"
JAKARTA = ZoneInfo("Asia/Jakarta")
STATE_PRIORITY = {
    "EXECUTION_READY": 5,
    "ARMED": 4,
    "SETUP_FORMING": 3,
    "WATCH": 2,
    "NO_TRADE": 1,
}


def _score(row: dict[str, Any]) -> tuple[int, float, str]:
    state = str(row.get("state") or "NO_TRADE").upper()
    try:
        score = float(row.get("final_score") or -1.0)
    except (TypeError, ValueError):
        score = -1.0
    return STATE_PRIORITY.get(state, 0), score, str(row.get("observed_at") or "")


def _grade(state: str) -> str:
    value = str(state or "").upper()
    if value == "EXECUTION_READY":
        return "EXECUTION_READY"
    if value in {"ARMED", "SETUP_FORMING"}:
        return "VALID_SETUP_FORMING"
    if value == "WATCH":
        return "WATCH"
    return "NO_TRADE"


def build_daily_opportunity(
    store: SupabaseOperationalStore,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(tz=timezone.utc)).astimezone(JAKARTA)
    start_local = datetime.combine(current.date(), time.min, tzinfo=JAKARTA)
    end_local = datetime.combine(current.date(), time.max, tzinfo=JAKARTA)

    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,symbol,direction,state,final_score,"
            "entry_low,entry_high,sl,tp1,tp2,rr1,rr2,active_guards,expires_at"
        )
        .eq("symbol", SYMBOL)
        .gte("observed_at", start_local.astimezone(timezone.utc).isoformat())
        .lte("observed_at", end_local.astimezone(timezone.utc).isoformat())
        .order("observed_at", desc=True)
        .limit(1000)
        .execute()
    )
    rows = [dict(row) for row in (response.data or [])]
    if not rows:
        return {
            "contract": "XAU_DAILY_OPPORTUNITY_V1",
            "symbol": SYMBOL,
            "trading_date_jakarta": current.date().isoformat(),
            "observations": 0,
            "grade": "NO_TRADE",
            "reason": "NO_XAU_OBSERVATION_TODAY",
            "execution_influence": False,
            "forced_trade": False,
            "best": None,
        }

    rows.sort(key=_score, reverse=True)
    best = rows[0]
    signal_id = str(best.get("id") or "")
    strategy_id: str | None = None
    if signal_id:
        geometry = (
            store.client.table("broker_order_events")
            .select("signal_key,code,event_type,observed_at")
            .eq("signal_key", signal_id)
            .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
            .order("observed_at", desc=True)
            .limit(1)
            .execute()
        )
        if geometry.data:
            strategy_id = str(dict(geometry.data[0]).get("code") or "") or None

    best_payload = {
        "signal_id": signal_id or None,
        "strategy_id": strategy_id,
        "observed_at": best.get("observed_at"),
        "direction": best.get("direction"),
        "state": best.get("state"),
        "final_score": best.get("final_score"),
        "entry_low": best.get("entry_low"),
        "entry_high": best.get("entry_high"),
        "sl": best.get("sl"),
        "tp1": best.get("tp1"),
        "tp2": best.get("tp2"),
        "rr1": best.get("rr1"),
        "rr2": best.get("rr2"),
        "active_guards": best.get("active_guards"),
        "expires_at": best.get("expires_at"),
    }
    return {
        "contract": "XAU_DAILY_OPPORTUNITY_V1",
        "symbol": SYMBOL,
        "trading_date_jakarta": current.date().isoformat(),
        "observations": len(rows),
        "grade": _grade(str(best.get("state") or "")),
        "reason": "BEST_AVAILABLE_XAU_OBSERVATION",
        "execution_influence": False,
        "forced_trade": False,
        "best": best_payload,
    }


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    details = build_daily_opportunity(store)
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )
    best = details.get("best") or {}
    print(
        "CTRADER_DEMO_XAU_DAILY_OPPORTUNITY "
        f"date={details['trading_date_jakarta']} observations={details['observations']} "
        f"grade={details['grade']} strategy={best.get('strategy_id')} "
        f"state={best.get('state')} score={best.get('final_score')} forced_trade=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
