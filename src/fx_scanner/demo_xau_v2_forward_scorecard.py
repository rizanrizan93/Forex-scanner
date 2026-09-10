from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .demo_adaptive_calibration_v2 import SYSTEM_BREAKEVENS, SYSTEM_LOSSES, SYSTEM_WINS
from .demo_outcome_normalization import normalize_adaptive_profit_lock_outcomes
from .demo_xau_strategy_latency_telemetry import STRATEGY_ACTIVATED_AT, STRATEGY_ID
from .storage.supabase_operational import SupabaseOperationalStore

WORKER = "ctrader_demo_xau_impulse_retest_v2_forward_scorecard"
CLOSED_LIMIT = 500
SIGNAL_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class ForwardStats:
    reliable_closed: int
    decisive: int
    wins: int
    losses: int
    breakevens: int
    net_pnl: float
    adaptive_lock_wins: int
    adaptive_lock_losses: int
    adaptive_lock_breakevens: int

    @property
    def win_rate(self) -> float | None:
        return None if self.decisive <= 0 else self.wins / self.decisive


def forward_stage(decisive: int) -> str:
    if decisive < 5:
        return "OBSERVE"
    if decisive < 10:
        return "SHADOW_EVALUATION"
    if decisive < 20:
        return "MICRO_ACTIVATION_REVIEW_ELIGIBLE"
    return "LOCALIZED_STRATEGY_REVIEW_ELIGIBLE"


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _signals(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select("id,observed_at,symbol,direction,state,final_score,setup_type")
        .eq("symbol", "XAUUSD")
        .gte("observed_at", STRATEGY_ACTIVATED_AT.isoformat())
        .order("observed_at", desc=True)
        .limit(SIGNAL_LIMIT)
        .execute()
    )
    return {
        str(row.get("id")): dict(row)
        for row in (response.data or [])
        if row.get("id")
    }


def _closed(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,code,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(CLOSED_LIMIT)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _reliable_v2_rows(
    store: SupabaseOperationalStore,
    *,
    signals: dict[str, dict[str, Any]] | None = None,
    closed_rows: tuple[dict[str, Any], ...] | None = None,
    adaptive_rows: tuple[dict[str, Any], ...] | None = None,
) -> tuple[dict[str, Any], ...]:
    signals = _signals(store) if signals is None else signals
    raw = _closed(store) if closed_rows is None else closed_rows
    normalized = normalize_adaptive_profit_lock_outcomes(
        store,
        raw,
        adaptive_rows=adaptive_rows,
    )
    output: list[dict[str, Any]] = []
    for row in normalized:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        signal_id = str(row.get("signal_key") or payload.get("signal_id") or "").strip()
        signal = signals.get(signal_id)
        if signal is None:
            continue
        if str(payload.get("symbol") or signal.get("symbol") or "").upper() != "XAUUSD":
            continue
        exit_type = str(payload.get("exit_type") or row.get("code") or "").upper()
        if exit_type.startswith("MANUAL_CLOSE_"):
            continue
        if bool(payload.get("partial_close", False)):
            continue
        if exit_type not in SYSTEM_WINS | SYSTEM_LOSSES | SYSTEM_BREAKEVENS:
            continue
        item = dict(row)
        enriched = dict(payload)
        enriched["strategy_id"] = STRATEGY_ID
        enriched["strategy_activated_at"] = STRATEGY_ACTIVATED_AT.isoformat()
        enriched["strategy_forward_scope"] = "XAUUSD_SIGNAL_CREATED_AFTER_V2_SOLE_AUTHORITY_ACTIVATION"
        item["payload"] = enriched
        output.append(item)
    return tuple(output)


def summarize_forward(rows: tuple[dict[str, Any], ...]) -> ForwardStats:
    wins = losses = breakevens = 0
    net_pnl = 0.0
    adaptive_wins = adaptive_losses = adaptive_breakevens = 0
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        exit_type = str(payload.get("exit_type") or row.get("code") or "").upper()
        wins += int(exit_type in SYSTEM_WINS)
        losses += int(exit_type in SYSTEM_LOSSES)
        breakevens += int(exit_type in SYSTEM_BREAKEVENS)
        adaptive_wins += int(exit_type == "ADAPTIVE_PROFIT_LOCK_PROFIT")
        adaptive_losses += int(exit_type == "ADAPTIVE_PROFIT_LOCK_LOSS")
        adaptive_breakevens += int(exit_type == "ADAPTIVE_PROFIT_LOCK_BREAKEVEN")
        net = _finite(payload.get("net_pnl_estimate"))
        if net is not None:
            net_pnl += net
    return ForwardStats(
        reliable_closed=len(rows),
        decisive=wins + losses,
        wins=wins,
        losses=losses,
        breakevens=breakevens,
        net_pnl=net_pnl,
        adaptive_lock_wins=adaptive_wins,
        adaptive_lock_losses=adaptive_losses,
        adaptive_lock_breakevens=adaptive_breakevens,
    )


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    signals = _signals(store)
    rows = _reliable_v2_rows(store, signals=signals)
    stats = summarize_forward(rows)
    details = {
        "strategy_id": STRATEGY_ID,
        "strategy_authority": "SOLE_DEMO_EXECUTION_STRATEGY",
        "strategy_activated_at": STRATEGY_ACTIVATED_AT.isoformat(),
        "symbol": "XAUUSD",
        "scope": "FORWARD_DEMO_ONLY_POST_ACTIVATION",
        "completed_trade_source": "DEMO_TRADE_CLOSED",
        "historical_adaptive_lock_overlay": "READ_ONLY_CALIBRATION_NORMALIZATION",
        "reliable_closed": stats.reliable_closed,
        "decisive": stats.decisive,
        "wins": stats.wins,
        "losses": stats.losses,
        "breakevens": stats.breakevens,
        "win_rate": stats.win_rate,
        "realized_net_pnl": stats.net_pnl,
        "adaptive_lock_wins": stats.adaptive_lock_wins,
        "adaptive_lock_losses": stats.adaptive_lock_losses,
        "adaptive_lock_breakevens": stats.adaptive_lock_breakevens,
        "stage": forward_stage(stats.decisive),
        "minimum_decisive_micro_activation_review": 10,
        "minimum_decisive_localized_strategy_review": 20,
        "r_expectancy_status": "NOT_REPORTED_WITHOUT_EXACT_BROKER_RISK_NORMALIZATION",
        "automatic_strategy_mutation": False,
        "execution_influence": False,
        "live_unlock": False,
    }
    store.write_heartbeat(WORKER, healthy=True, lag_seconds=0.0, details=details)
    print(
        "CTRADER_DEMO_XAU_V2_FORWARD_SCORECARD "
        f"strategy={STRATEGY_ID} reliable_closed={stats.reliable_closed} "
        f"decisive={stats.decisive} wins={stats.wins} losses={stats.losses} "
        f"breakevens={stats.breakevens} "
        f"win_rate={'NONE' if stats.win_rate is None else f'{stats.win_rate:.3f}'} "
        f"realized_net={stats.net_pnl:.8g} stage={forward_stage(stats.decisive)} "
        "execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
