from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

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
