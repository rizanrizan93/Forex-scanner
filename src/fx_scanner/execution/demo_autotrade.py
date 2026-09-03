from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class DemoAutoReport:
    scanned: int
    eligible: int
    claimed: int
    executed: int
    skipped: tuple[str, ...]


class SupabaseOrderAuditSink:
    """Best-effort audit adapter consumed by ExecutionRouter."""

    def __init__(self, store):
        self.store = store

    def emit(self, event: dict[str, Any]) -> None:
        payload = dict(event.get("payload") or {})
        self.store.record_order_event(
            backend=str(event.get("backend", "CTRADER")),
            account_id=str(event.get("account_id", "UNKNOWN")),
            signal_key=str(event.get("signal_key", "UNKNOWN")),
            event_type=str(event.get("event_type", "UNKNOWN")),
            broker_order_id=payload.get("broker_order_id"),
            accepted=event.get("accepted"),
            code=None if event.get("code") is None else str(event.get("code")),
            message=None if event.get("message") is None else str(event.get("message")),
            payload=payload,
        )


class CTraderDemoAutoExecutor:
    """Consume durable EXECUTION_READY signals and submit demo-only cTrader orders.

    Broker exposure is reconciled before the durable Supabase claim. This keeps
    capacity/same-symbol blocks from consuming a signal into COOLDOWN before any
    broker attempt, while the canonical EXECUTION_READY -> COOLDOWN transition
    remains the atomic claim immediately before execution.
    """

    def __init__(self, *, cfg, policy, gateway, router, store):
        self.cfg = cfg
        self.policy = policy
        self.gateway = gateway
        self.router = router
        self.store = store
        self.demo = policy.demo_safety
        self.control_gate = getattr(router, "control_gate", None)

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    def _intent(self, row: dict[str, Any], *, now: datetime) -> OrderIntent | None:
        signal_id = str(row.get("id", "")).strip()
        symbol = str(row.get("symbol", "")).upper().strip()
        direction = str(row.get("direction", "")).upper().strip()
        if not signal_id or symbol not in self.cfg.pair_map or direction not in {"LONG", "SHORT"}:
            return None
        if str(row.get("state", "")).upper() != "EXECUTION_READY":
            return None

        guards = row.get("active_guards")
        if guards not in (None, [], ()):
            return None
        coverage = float(row.get("data_coverage") or 0.0)
        if coverage < float(self.demo["min_signal_coverage"]):
            return None
        final_score = row.get("final_score")
        if final_score is not None and float(final_score) < float(
            self.cfg.scoring["states"]["execution_candidate_min"]
        ):
            return None

        observed_at = self._dt(row.get("observed_at"))
        if observed_at is None:
            return None
        age = (now - observed_at).total_seconds()
        if age < -1.0 or age > float(self.policy.order["max_signal_age_seconds"]):
            return None
        expires_at = self._dt(row.get("expires_at"))
        if expires_at is not None and now > expires_at:
            return None

        try:
            entry_low = float(row["entry_low"])
            entry_high = float(row["entry_high"])
            stop_loss = float(row["sl"])
            take_profit = float(row["tp2"])
            rr2 = float(row["rr2"])
        except (TypeError, ValueError, KeyError):
            return None
        if not (0 < entry_low < entry_high and rr2 >= float(self.cfg.strategy["trade_plan"]["minimum_tp2_rr"])):
            return None

        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        quote = self.gateway.market_quote(symbol)
        executable = float(quote.ask if side == OrderSide.BUY else quote.bid)
        if not entry_low <= executable <= entry_high:
            return None
        if side == OrderSide.BUY and not (stop_loss < executable < take_profit):
            return None
        if side == OrderSide.SELL and not (take_profit < executable < stop_loss):
            return None

        volume = min(0.01, float(self.demo["max_order_lots"]))
        return OrderIntent(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            created_at=observed_at,
            volume=volume,
            entry_price=executable,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_pct=min(
                float(self.cfg.risk["risk_per_trade_pct"]),
                float(self.demo["max_risk_pct"]),
            ),
            comment=f"DEMO_AUTO:{row.get('setup_type') or 'UNKNOWN'}",
        )

    def _broker_exposure_block(self, symbol: str) -> str | None:
        """Reconcile current cTrader exposure before consuming the durable signal.

        Fail closed when total broker capacity cannot be read. For the cTrader
        gateway, also reject stacking a second position on the same symbol.
        """
        try:
            open_positions = int(self.gateway.position_count())
        except Exception as exc:
            return f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"

        max_positions = int(self.demo.get("max_concurrent_positions", 1))
        if open_positions >= max_positions:
            return f"BROKER_CAPACITY_FULL:{open_positions}/{max_positions}"

        session = getattr(self.gateway, "session", None)
        if session is None:
            return None
        try:
            session.ensure_connected()
            target_symbol_id = int(session.symbol_info(symbol).symbolId)
            reconcile = session.reconcile()
            for position in tuple(getattr(reconcile, "position", ())):
                trade_data = getattr(position, "tradeData", None)
                position_symbol_id = getattr(trade_data, "symbolId", None)
                if position_symbol_id is not None and int(position_symbol_id) == target_symbol_id:
                    return f"BROKER_SYMBOL_ALREADY_OPEN:{symbol}"
        except Exception as exc:
            return f"BROKER_SYMBOL_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"
        return None

    def poll_once(self, *, limit: int = 10) -> DemoAutoReport:
        if self.policy.live_safety.get("require_control_plane", False):
            if self.control_gate is None:
                return DemoAutoReport(
                    0, 0, 0, 0, ("CONTROL_PLANE_BLOCKED:NOT_CONFIGURED",)
                )
            try:
                self.control_gate.assert_orders_allowed(self.policy.mode.value)
            except Exception as exc:
                return DemoAutoReport(
                    0,
                    0,
                    0,
                    0,
                    (f"CONTROL_PLANE_BLOCKED:{type(exc).__name__}:{exc}",),
                )

        now = datetime.now(tz=UTC)
        rows = self.store.list_execution_ready_signals(limit=limit)
        eligible = 0
        claimed = 0
        executed = 0
        skipped: list[str] = []

        for row in rows:
            signal_id = str(row.get("id", "UNKNOWN"))
            try:
                intent = self._intent(row, now=now)
            except Exception as exc:
                skipped.append(f"{signal_id}:INTENT_ERROR:{type(exc).__name__}:{exc}")
                continue
            if intent is None:
                skipped.append(f"{signal_id}:NOT_ELIGIBLE")
                continue
            eligible += 1

            exposure_block = self._broker_exposure_block(intent.symbol)
            if exposure_block is not None:
                skipped.append(f"{signal_id}:{exposure_block}")
                continue

            try:
                if not self.store.claim_signal_for_execution(intent.signal_id):
                    skipped.append(f"{signal_id}:CLAIM_LOST")
                    continue
                claimed += 1
                receipt = self.router.execute(intent)
                if receipt.accepted:
                    executed += 1
                else:
                    skipped.append(f"{signal_id}:BROKER_NOT_ACCEPTED")
            except Exception as exc:
                skipped.append(f"{signal_id}:EXECUTION_BLOCKED:{type(exc).__name__}:{exc}")

        return DemoAutoReport(
            scanned=len(rows),
            eligible=eligible,
            claimed=claimed,
            executed=executed,
            skipped=tuple(skipped),
        )
