from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from ..exceptions import ConfigurationError, FXScannerError, MissingOptionalDependency

UTC = timezone.utc


class OperationalStoreUnavailable(FXScannerError):
    """Durable operational state cannot be read or written safely."""


@dataclass(frozen=True, slots=True)
class ExecutionControlSnapshot:
    control_key: str
    execution_mode: str
    new_orders_enabled: bool
    emergency_stop: bool
    close_all_requested: bool
    version: int
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ExecutionControlSnapshot":
        raw_time = str(row["updated_at"]).replace("Z", "+00:00")
        updated_at = datetime.fromisoformat(raw_time)
        if updated_at.tzinfo is None:
            raise OperationalStoreUnavailable("execution_control updated_at must be timezone-aware")
        return cls(
            control_key=str(row["control_key"]),
            execution_mode=str(row["execution_mode"]).upper(),
            new_orders_enabled=bool(row["new_orders_enabled"]),
            emergency_stop=bool(row["emergency_stop"]),
            close_all_requested=bool(row["close_all_requested"]),
            version=int(row["version"]),
            updated_at=updated_at.astimezone(UTC),
        )


class SupabaseOperationalStore:
    """Backend-only Supabase adapter for durable scanner/control state."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        *,
        client: Any | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        if not url.strip():
            raise ConfigurationError("SUPABASE_URL is required")
        if not secret_key.strip():
            raise ConfigurationError("SUPABASE_SECRET_KEY is required")
        self.url = url.strip()
        if client is not None:
            self.client = client
            return
        if client_factory is None:
            try:
                from supabase import create_client
            except ModuleNotFoundError as exc:
                raise MissingOptionalDependency("supabase package is unavailable") from exc
            client_factory = create_client
        self.client = client_factory(self.url, secret_key)

    @classmethod
    def from_env(cls, **kwargs) -> "SupabaseOperationalStore":
        url = os.getenv("SUPABASE_URL", "").strip()
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not secret:
            secret = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        return cls(url, secret, **kwargs)

    def get_execution_control(self, control_key: str = "primary") -> ExecutionControlSnapshot:
        try:
            response = (
                self.client.table("execution_control")
                .select(
                    "control_key,execution_mode,new_orders_enabled,emergency_stop,"
                    "close_all_requested,version,updated_at"
                )
                .eq("control_key", control_key)
                .limit(2)
                .execute()
            )
            rows = list(response.data or [])
        except Exception as exc:
            raise OperationalStoreUnavailable(f"execution_control read failed: {exc}") from exc
        if len(rows) != 1:
            raise OperationalStoreUnavailable(f"expected exactly one execution_control row, got {len(rows)}")
        return ExecutionControlSnapshot.from_row(rows[0])

    def list_execution_ready_signals(self, *, limit: int = 10) -> tuple[dict[str, Any], ...]:
        if limit <= 0 or limit > 100:
            raise ValueError("signal limit must be in [1,100]")
        fields = (
            "id,run_id,observed_at,symbol,direction,setup_type,state,"
            "entry_low,entry_high,sl,tp1,tp2,rr1,rr2,active_guards,"
            "data_coverage,expires_at,final_score"
        )
        try:
            response = (
                self.client.table("signals")
                .select(fields)
                .eq("state", "EXECUTION_READY")
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return tuple(dict(row) for row in (response.data or []))
        except Exception as exc:
            raise OperationalStoreUnavailable(
                f"execution-ready signal read failed: {exc}"
            ) from exc

    def claim_signal_for_execution(self, signal_id: str) -> bool:
        """Atomically move one EXECUTION_READY signal to COOLDOWN before broker I/O."""
        if not str(signal_id).strip():
            raise ValueError("signal_id is required")
        try:
            response = (
                self.client.table("signals")
                .update({"state": "COOLDOWN"})
                .eq("id", str(signal_id))
                .eq("state", "EXECUTION_READY")
                .execute()
            )
            rows = list(response.data or [])
        except Exception as exc:
            raise OperationalStoreUnavailable(f"signal claim failed: {exc}") from exc
        if len(rows) > 1:
            raise OperationalStoreUnavailable("signal claim updated multiple rows")
        return len(rows) == 1

    def set_execution_control(
        self,
        *,
        execution_mode: str,
        new_orders_enabled: bool,
        emergency_stop: bool,
        close_all_requested: bool = False,
        control_key: str = "primary",
        source: str = "ctrader_demo_control",
    ) -> ExecutionControlSnapshot:
        """Optimistic, versioned control-plane update for the phone-only demo runtime."""
        mode = str(execution_mode).upper()
        if mode not in {"DISABLED", "SIMULATION", "CONFIRM_TO_TRADE", "AUTO"}:
            raise ValueError("invalid execution control mode")
        current = self.get_execution_control(control_key)
        payload = {
            "execution_mode": mode,
            "new_orders_enabled": bool(new_orders_enabled),
            "emergency_stop": bool(emergency_stop),
            "close_all_requested": bool(close_all_requested),
            "version": current.version + 1,
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "metadata": {"source": str(source), "previous_version": current.version},
        }
        try:
            response = (
                self.client.table("execution_control")
                .update(payload)
                .eq("control_key", control_key)
                .eq("version", current.version)
                .execute()
            )
            rows = list(response.data or [])
        except Exception as exc:
            raise OperationalStoreUnavailable(
                f"execution_control update failed: {exc}"
            ) from exc
        if len(rows) != 1:
            raise OperationalStoreUnavailable(
                "execution_control optimistic update lost a race"
            )
        return ExecutionControlSnapshot.from_row(rows[0])

    def list_active_symbols(self) -> tuple[str, ...]:
        try:
            response = (
                self.client.table("fx_symbols")
                .select("symbol")
                .eq("active", True)
                .order("symbol")
                .execute()
            )
            return tuple(str(row["symbol"]).upper() for row in (response.data or []))
        except Exception as exc:
            raise OperationalStoreUnavailable(f"fx_symbols read failed: {exc}") from exc

    def write_heartbeat(
        self,
        worker_name: str,
        *,
        healthy: bool,
        lag_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "worker_name": worker_name,
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "healthy": bool(healthy),
            "lag_seconds": lag_seconds,
            "details": details or {},
        }
        try:
            self.client.table("runtime_heartbeats").upsert(payload, on_conflict="worker_name").execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(f"heartbeat write failed: {exc}") from exc

    def publish_broker_telemetry(
        self,
        account: Any,
        positions: Any,
        *,
        broker_name: str | None = None,
        environment: str | None = None,
        connection_healthy: bool = True,
    ) -> str:
        """Publish one coherent broker-account/open-position snapshot."""
        snapshot_id = str(uuid4())
        observed_at = datetime.now(tz=UTC).isoformat()
        backend = getattr(account.backend, "value", str(account.backend)).upper()
        account_id = str(account.account_id)

        position_rows = []
        for position in tuple(positions):
            position_backend = getattr(
                position.backend, "value", str(position.backend)
            ).upper()
            if position_backend != backend:
                raise OperationalStoreUnavailable("broker telemetry backend mismatch")
            opened_at = getattr(position, "opened_at", None)
            position_rows.append({
                "backend": backend,
                "account_id": account_id,
                "position_id": str(position.position_id),
                "snapshot_id": snapshot_id,
                "observed_at": observed_at,
                "symbol": str(position.symbol),
                "side": str(position.side).upper(),
                "volume": float(position.volume),
                "open_price": float(position.open_price),
                "current_price": position.current_price,
                "sl": position.stop_loss,
                "tp": position.take_profit,
                "profit": position.profit,
                "swap": position.swap,
                "magic": position.magic,
                "comment": position.comment,
                "opened_at": None if opened_at is None else opened_at.isoformat(),
                "metadata": {},
            })

        try:
            if position_rows:
                (
                    self.client.table("broker_position_state")
                    .upsert(
                        position_rows,
                        on_conflict="backend,account_id,position_id",
                    )
                    .execute()
                )

            account_row = {
                "backend": backend,
                "account_id": account_id,
                "snapshot_id": snapshot_id,
                "observed_at": observed_at,
                "broker_name": broker_name,
                "environment": None if environment is None else str(environment).upper(),
                "currency": account.currency,
                "balance": float(account.balance),
                "equity": float(account.equity),
                "floating_profit": account.floating_profit,
                "margin": account.margin,
                "margin_free": account.margin_free,
                "margin_level": account.margin_level,
                "leverage": account.leverage,
                "trade_allowed": bool(account.trade_allowed),
                "connection_healthy": bool(connection_healthy),
                "metadata": {"server": account.server} if account.server else {},
            }
            (
                self.client.table("broker_account_state")
                .upsert(account_row, on_conflict="backend,account_id")
                .execute()
            )
        except Exception as exc:
            raise OperationalStoreUnavailable(
                f"broker telemetry write failed: {exc}"
            ) from exc
        return snapshot_id

    def record_order_event(
        self,
        *,
        backend: str,
        account_id: str,
        signal_key: str,
        event_type: str,
        broker_order_id: str | None = None,
        accepted: bool | None = None,
        code: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        row = {
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "backend": backend.upper(),
            "account_id": str(account_id),
            "signal_key": signal_key,
            "broker_order_id": broker_order_id,
            "event_type": event_type,
            "accepted": accepted,
            "code": code,
            "message": message,
            "payload": payload or {},
        }
        try:
            self.client.table("broker_order_events").insert(row).execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(f"broker_order_events write failed: {exc}") from exc
