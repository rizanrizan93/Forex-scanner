from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable

from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
SYSTEM_WINS = {"TP_HIT"}
SYSTEM_LOSSES = {"SL_HIT", "STOP_OUT"}
SYSTEM_BREAKEVENS = {"BREAKEVEN", "PROTECTION_CLOSE_BREAKEVEN"}


@dataclass(frozen=True, slots=True)
class CalibrationStats:
    closed: int = 0
    system_closed: int = 0
    manual_closed: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    net_pnl: float = 0.0
    r_proxy_sum: float = 0.0
    r_proxy_count: int = 0

    @property
    def decisive_system(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        decisive = self.decisive_system
        return None if decisive <= 0 else self.wins / decisive

    @property
    def avg_r_proxy(self) -> float | None:
        return None if self.r_proxy_count <= 0 else self.r_proxy_sum / self.r_proxy_count


@dataclass(frozen=True, slots=True)
class CalibrationSummary:
    overall: CalibrationStats
    by_symbol: dict[str, CalibrationStats]
    by_setup: dict[str, CalibrationStats]


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _r_proxy(payload: dict[str, Any]) -> float | None:
    direction = str(payload.get("direction", "")).upper()
    entry_low = _finite_float(payload.get("entry_low"))
    entry_high = _finite_float(payload.get("entry_high"))
    stop = _finite_float(payload.get("planned_sl"))
    exit_price = _finite_float(payload.get("exit_price"))
    if (
        direction not in {"LONG", "SHORT"}
        or entry_low is None
        or entry_high is None
        or stop is None
        or exit_price is None
        or not 0 < entry_low <= entry_high
    ):
        return None
    entry_mid = (entry_low + entry_high) / 2.0
    risk = abs(entry_mid - stop)
    if risk <= 1e-12:
        return None
    realized = exit_price - entry_mid if direction == "LONG" else entry_mid - exit_price
    value = realized / risk
    if not isfinite(value):
        return None
    return max(-10.0, min(10.0, value))


def _add(stats: CalibrationStats, payload: dict[str, Any]) -> CalibrationStats:
    exit_type = str(payload.get("exit_type", "") or "").upper()
    net = _finite_float(payload.get("net_pnl_estimate")) or 0.0
    is_manual = exit_type.startswith("MANUAL_CLOSE_")
    is_win = exit_type in SYSTEM_WINS
    is_loss = exit_type in SYSTEM_LOSSES
    is_be = exit_type in SYSTEM_BREAKEVENS
    is_system = is_win or is_loss or is_be
    r_value = _r_proxy(payload) if is_system else None
    return CalibrationStats(
        closed=stats.closed + 1,
        system_closed=stats.system_closed + int(is_system),
        manual_closed=stats.manual_closed + int(is_manual),
        wins=stats.wins + int(is_win),
        losses=stats.losses + int(is_loss),
        breakevens=stats.breakevens + int(is_be),
        net_pnl=stats.net_pnl + net,
        r_proxy_sum=stats.r_proxy_sum + (0.0 if r_value is None else r_value),
        r_proxy_count=stats.r_proxy_count + int(r_value is not None),
    )


def summarize_closed_events(rows: Iterable[dict[str, Any]]) -> CalibrationSummary:
    overall = CalibrationStats()
    by_symbol: dict[str, CalibrationStats] = {}
    by_setup: dict[str, CalibrationStats] = {}
    for row in rows:
        payload = _payload(dict(row))
        overall = _add(overall, payload)
        symbol = str(payload.get("symbol", "UNKNOWN") or "UNKNOWN").upper()
        setup = str(payload.get("setup_type", "UNKNOWN") or "UNKNOWN").upper()
        by_symbol[symbol] = _add(by_symbol.get(symbol, CalibrationStats()), payload)
        by_setup[setup] = _add(by_setup.get(setup, CalibrationStats()), payload)
    return CalibrationSummary(overall, by_symbol, by_setup)


def calibration_stage(stats: CalibrationStats) -> str:
    decisive = stats.decisive_system
    if decisive < 5:
        return "OBSERVE"
    if decisive < 10:
        return "SHADOW"
    if decisive < 20:
        return "MICRO_READY"
    return "ADAPTIVE_READY"


def suggested_score_floor_penalty(stats: CalibrationStats) -> float:
    """Conservative DEMO-only suggestion; never boosts a pair.

    Manual closes and breakevens do not drive the suggestion. A beta prior
    prevents tiny samples from creating large changes. No penalty is suggested
    before ten decisive system exits. The suggested cap is 2.5 points until 20
    decisive exits and 5 points thereafter.
    """

    decisive = stats.decisive_system
    if decisive < 10:
        return 0.0
    posterior_win_rate = (stats.wins + 2.0) / (decisive + 4.0)
    deficit = max(0.0, 0.45 - posterior_win_rate)
    cap = 2.5 if decisive < 20 else 5.0
    return min(cap, round(deficit * 20.0, 2))


def _latest_account_and_positions(store: SupabaseOperationalStore):
    response = (
        store.client.table("broker_account_state")
        .select(
            "backend,account_id,snapshot_id,observed_at,balance,equity,"
            "floating_profit,margin,margin_free"
        )
        .eq("backend", "CTRADER")
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    accounts = list(response.data or [])
    if not accounts:
        return None, ()
    account = dict(accounts[0])
    snapshot_id = str(account.get("snapshot_id", "") or "")
    if not snapshot_id:
        return account, ()
    positions_res = (
        store.client.table("broker_position_state")
        .select("position_id,snapshot_id,symbol,side,volume,open_price,sl,tp,profit")
        .eq("backend", "CTRADER")
        .eq("account_id", str(account.get("account_id", "")))
        .eq("snapshot_id", snapshot_id)
        .order("symbol")
        .execute()
    )
    return account, tuple(dict(row) for row in (positions_res.data or []))


def _closed_events(store: SupabaseOperationalStore, *, account_id: str | None, limit: int = 500):
    query = (
        store.client.table("broker_order_events")
        .select("observed_at,account_id,signal_key,code,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(int(limit))
    )
    if account_id:
        query = query.eq("account_id", str(account_id))
    response = query.execute()
    return tuple(dict(row) for row in (response.data or []))


def _snapshot_age_seconds(account: dict[str, Any] | None) -> float | None:
    if not account or not account.get("observed_at"):
        return None
    try:
        observed = datetime.fromisoformat(str(account["observed_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        return None
    return max(0.0, (datetime.now(tz=UTC) - observed.astimezone(UTC)).total_seconds())


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    account, positions = _latest_account_and_positions(store)
    account_id = None if account is None else str(account.get("account_id", "") or "")
    rows = _closed_events(store, account_id=account_id or None)
    summary = summarize_closed_events(rows)

    balance = None if account is None else _finite_float(account.get("balance"))
    equity = None if account is None else _finite_float(account.get("equity"))
    floating = None if account is None else _finite_float(account.get("floating_profit"))
    snapshot_age = _snapshot_age_seconds(account)
    balance_text = "NONE" if balance is None else f"{balance:.8g}"
    equity_text = "NONE" if equity is None else f"{equity:.8g}"
    floating_text = "NONE" if floating is None else f"{floating:.8g}"
    age_text = "NONE" if snapshot_age is None else f"{snapshot_age:.1f}"
    overall = summary.overall
    print(
        "CTRADER_DEMO_INCREMENTAL_CALIBRATION "
        f"closed={overall.closed} system_closed={overall.system_closed} "
        f"manual_closed={overall.manual_closed} tp={overall.wins} sl={overall.losses} "
        f"breakeven={overall.breakevens} realized_net={overall.net_pnl:.8g} "
        f"balance={balance_text} equity={equity_text} floating_pnl={floating_text} "
        f"open_positions={len(positions)} snapshot_age_s={age_text} mode=SHADOW_INCREMENTAL"
    )

    current_by_symbol: dict[str, dict[str, float | int]] = {}
    for position in positions:
        symbol = str(position.get("symbol", "UNKNOWN") or "UNKNOWN").upper()
        item = current_by_symbol.setdefault(symbol, {"open": 0, "floating": 0.0})
        item["open"] = int(item["open"]) + 1
        pnl = _finite_float(position.get("profit"))
        if pnl is not None:
            item["floating"] = float(item["floating"]) + pnl

    symbols = sorted(set(summary.by_symbol) | set(current_by_symbol))
    pair_details: dict[str, Any] = {}
    for symbol in symbols:
        stats = summary.by_symbol.get(symbol, CalibrationStats())
        current = current_by_symbol.get(symbol, {"open": 0, "floating": 0.0})
        win_rate = stats.win_rate
        avg_r = stats.avg_r_proxy
        penalty = suggested_score_floor_penalty(stats)
        stage = calibration_stage(stats)
        win_text = "NONE" if win_rate is None else f"{win_rate:.3f}"
        r_text = "NONE" if avg_r is None else f"{avg_r:.3f}"
        print(
            "CTRADER_DEMO_PAIR_CALIBRATION "
            f"symbol={symbol} closed={stats.closed} system={stats.system_closed} "
            f"manual={stats.manual_closed} tp={stats.wins} sl={stats.losses} "
            f"win_rate={win_text} net={stats.net_pnl:.8g} avg_r_proxy={r_text} "
            f"open={int(current['open'])} floating={float(current['floating']):.8g} "
            f"stage={stage} suggested_floor_penalty={penalty:.2f}"
        )
        pair_details[symbol] = {
            "closed": stats.closed,
            "system_closed": stats.system_closed,
            "manual_closed": stats.manual_closed,
            "wins": stats.wins,
            "losses": stats.losses,
            "net_pnl": stats.net_pnl,
            "win_rate": win_rate,
            "avg_r_proxy": avg_r,
            "open_positions": int(current["open"]),
            "floating_pnl": float(current["floating"]),
            "stage": stage,
            "suggested_floor_penalty": penalty,
        }

    for setup, stats in sorted(summary.by_setup.items()):
        win_rate = stats.win_rate
        print(
            "CTRADER_DEMO_SETUP_CALIBRATION "
            f"setup={setup} closed={stats.closed} system={stats.system_closed} "
            f"manual={stats.manual_closed} tp={stats.wins} sl={stats.losses} "
            f"win_rate={'NONE' if win_rate is None else f'{win_rate:.3f}'} "
            f"net={stats.net_pnl:.8g} stage={calibration_stage(stats)}"
        )

    store.write_heartbeat(
        "ctrader_demo_incremental_calibration",
        healthy=True,
        lag_seconds=snapshot_age,
        details={
            "mode": "SHADOW_INCREMENTAL",
            "closed": overall.closed,
            "system_closed": overall.system_closed,
            "manual_closed": overall.manual_closed,
            "wins": overall.wins,
            "losses": overall.losses,
            "breakevens": overall.breakevens,
            "realized_net_pnl": overall.net_pnl,
            "balance": balance,
            "equity": equity,
            "floating_pnl": floating,
            "open_positions": len(positions),
            "snapshot_age_seconds": snapshot_age,
            "pair_calibration": pair_details,
            "automatic_strategy_mutation": False,
            "geometry_calibration": "HOLD_UNTIL_SUFFICIENT_CLOSED_AND_TRAJECTORY_EVIDENCE",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
