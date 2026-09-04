from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable

from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
SYSTEM_WINS = {"TP_HIT", "STRUCTURAL_PROTECT_PROFIT"}
SYSTEM_LOSSES = {"SL_HIT", "STOP_OUT", "STRUCTURAL_PROTECT_LOSS"}
SYSTEM_BREAKEVENS = {
    "BREAKEVEN",
    "PROTECTION_CLOSE_BREAKEVEN",
    "STRUCTURAL_PROTECT_BREAKEVEN",
}


@dataclass(frozen=True, slots=True)
class CalibrationStats:
    closed: int = 0
    system_closed: int = 0
    manual_closed: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    protected_wins: int = 0
    protected_losses: int = 0
    protected_breakevens: int = 0
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

    @property
    def tp_wins(self) -> int:
        return self.wins - self.protected_wins

    @property
    def sl_losses(self) -> int:
        return self.losses - self.protected_losses


@dataclass(frozen=True, slots=True)
class CalibrationSummary:
    overall: CalibrationStats
    by_symbol: dict[str, CalibrationStats]
    by_setup: dict[str, CalibrationStats]
    by_entry_mode: dict[str, CalibrationStats]
    by_confirmation: dict[str, CalibrationStats]


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
    protected_win = exit_type == "STRUCTURAL_PROTECT_PROFIT"
    protected_loss = exit_type == "STRUCTURAL_PROTECT_LOSS"
    protected_be = exit_type == "STRUCTURAL_PROTECT_BREAKEVEN"
    r_value = _r_proxy(payload) if is_system else None
    return CalibrationStats(
        closed=stats.closed + 1,
        system_closed=stats.system_closed + int(is_system),
        manual_closed=stats.manual_closed + int(is_manual),
        wins=stats.wins + int(is_win),
        losses=stats.losses + int(is_loss),
        breakevens=stats.breakevens + int(is_be),
        protected_wins=stats.protected_wins + int(protected_win),
        protected_losses=stats.protected_losses + int(protected_loss),
        protected_breakevens=stats.protected_breakevens + int(protected_be),
        net_pnl=stats.net_pnl + net,
        r_proxy_sum=stats.r_proxy_sum + (0.0 if r_value is None else r_value),
        r_proxy_count=stats.r_proxy_count + int(r_value is not None),
    )


def summarize_closed_events(rows: Iterable[dict[str, Any]]) -> CalibrationSummary:
    overall = CalibrationStats()
    by_symbol: dict[str, CalibrationStats] = {}
    by_setup: dict[str, CalibrationStats] = {}
    by_entry_mode: dict[str, CalibrationStats] = {}
    by_confirmation: dict[str, CalibrationStats] = {}
    for row in rows:
        payload = _payload(dict(row))
        overall = _add(overall, payload)
        symbol = str(payload.get("symbol", "UNKNOWN") or "UNKNOWN").upper()
        setup = str(payload.get("setup_type", "UNKNOWN") or "UNKNOWN").upper()
        entry_mode = str(payload.get("entry_mode", "LEGACY") or "LEGACY").upper()
        confirmation = str(payload.get("confirmation", "LEGACY") or "LEGACY").upper()
        by_symbol[symbol] = _add(by_symbol.get(symbol, CalibrationStats()), payload)
        by_setup[setup] = _add(by_setup.get(setup, CalibrationStats()), payload)
        by_entry_mode[entry_mode] = _add(by_entry_mode.get(entry_mode, CalibrationStats()), payload)
        by_confirmation[confirmation] = _add(by_confirmation.get(confirmation, CalibrationStats()), payload)
    return CalibrationSummary(overall, by_symbol, by_setup, by_entry_mode, by_confirmation)


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
    """Conservative DEMO-only suggestion; never boosts a pair."""
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


def _stats_payload(stats: CalibrationStats) -> dict[str, Any]:
    return {
        "closed": stats.closed,
        "system_closed": stats.system_closed,
        "manual_closed": stats.manual_closed,
        "wins": stats.wins,
        "losses": stats.losses,
        "breakevens": stats.breakevens,
        "tp_wins": stats.tp_wins,
        "sl_losses": stats.sl_losses,
        "protected_wins": stats.protected_wins,
        "protected_losses": stats.protected_losses,
        "protected_breakevens": stats.protected_breakevens,
        "net_pnl": stats.net_pnl,
        "win_rate": stats.win_rate,
        "avg_r_proxy": stats.avg_r_proxy,
        "stage": calibration_stage(stats),
    }


def _outcome_counts_text(stats: CalibrationStats) -> str:
    return (
        f"tp={stats.tp_wins} sl={stats.sl_losses} "
        f"protect_profit={stats.protected_wins} "
        f"protect_loss={stats.protected_losses} "
        f"protect_be={stats.protected_breakevens}"
    )


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
        f"manual_closed={overall.manual_closed} {_outcome_counts_text(overall)} "
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
        print(
            "CTRADER_DEMO_PAIR_CALIBRATION "
            f"symbol={symbol} closed={stats.closed} system={stats.system_closed} "
            f"manual={stats.manual_closed} {_outcome_counts_text(stats)} "
            f"win_rate={'NONE' if win_rate is None else f'{win_rate:.3f}'} net={stats.net_pnl:.8g} "
            f"avg_r_proxy={'NONE' if avg_r is None else f'{avg_r:.3f}'} "
            f"open={int(current['open'])} floating={float(current['floating']):.8g} "
            f"stage={stage} suggested_floor_penalty={penalty:.2f}"
        )
        pair_details[symbol] = {
            **_stats_payload(stats),
            "open_positions": int(current["open"]),
            "floating_pnl": float(current["floating"]),
            "suggested_floor_penalty": penalty,
        }

    for setup, stats in sorted(summary.by_setup.items()):
        print(
            "CTRADER_DEMO_SETUP_CALIBRATION "
            f"setup={setup} closed={stats.closed} system={stats.system_closed} "
            f"manual={stats.manual_closed} {_outcome_counts_text(stats)} "
            f"win_rate={'NONE' if stats.win_rate is None else f'{stats.win_rate:.3f}'} "
            f"net={stats.net_pnl:.8g} stage={calibration_stage(stats)}"
        )

    entry_details: dict[str, Any] = {}
    for entry_mode, stats in sorted(summary.by_entry_mode.items()):
        print(
            "CTRADER_DEMO_ENTRY_CALIBRATION "
            f"entry_mode={entry_mode} closed={stats.closed} system={stats.system_closed} "
            f"manual={stats.manual_closed} {_outcome_counts_text(stats)} "
            f"win_rate={'NONE' if stats.win_rate is None else f'{stats.win_rate:.3f}'} "
            f"net={stats.net_pnl:.8g} avg_r_proxy={'NONE' if stats.avg_r_proxy is None else f'{stats.avg_r_proxy:.3f}'} "
            f"stage={calibration_stage(stats)}"
        )
        entry_details[entry_mode] = _stats_payload(stats)

    confirmation_details: dict[str, Any] = {}
    for confirmation, stats in sorted(summary.by_confirmation.items()):
        print(
            "CTRADER_DEMO_CONFIRMATION_CALIBRATION "
            f"confirmation={confirmation} closed={stats.closed} system={stats.system_closed} "
            f"{_outcome_counts_text(stats)} "
            f"win_rate={'NONE' if stats.win_rate is None else f'{stats.win_rate:.3f}'} "
            f"net={stats.net_pnl:.8g} stage={calibration_stage(stats)}"
        )
        confirmation_details[confirmation] = _stats_payload(stats)

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
            "tp_wins": overall.tp_wins,
            "sl_losses": overall.sl_losses,
            "structural_protect_profit": overall.protected_wins,
            "structural_protect_loss": overall.protected_losses,
            "structural_protect_breakeven": overall.protected_breakevens,
            "realized_net_pnl": overall.net_pnl,
            "balance": balance,
            "equity": equity,
            "floating_pnl": floating,
            "open_positions": len(positions),
            "snapshot_age_seconds": snapshot_age,
            "pair_calibration": pair_details,
            "entry_mode_calibration": entry_details,
            "confirmation_calibration": confirmation_details,
            "automatic_strategy_mutation": False,
            "geometry_calibration": "SHADOW_CAPTURE_ACTIVE_MUTATION_HOLD",
            "trade_management_calibration": "STRUCTURAL_PROFIT_PROTECT_SEPARATE_BUCKET",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
