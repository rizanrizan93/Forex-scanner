from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
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
        execution_ready_score_floor: float = 90.0,
    ):
        if not url.strip():
            raise ConfigurationError("SUPABASE_URL is required")
        if not secret_key.strip():
            raise ConfigurationError("SUPABASE_SECRET_KEY is required")
        self.url = url.strip()
        score_floor = float(execution_ready_score_floor)
        if not isfinite(score_floor) or not 65.0 <= score_floor <= 100.0:
            raise ConfigurationError(
                "execution_ready_score_floor must be finite and within [65,100]"
            )
        self.execution_ready_score_floor = score_floor
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

    def ensure_reference_symbols(self, pairs: Any) -> None:
        """Idempotently synchronize configured instruments into fx_symbols.

        This is backend-only reference-data bootstrap. It never weakens RLS or
        public access and fails closed if the durable reference write fails.
        """
        rows: list[dict[str, Any]] = []
        for pair in tuple(pairs):
            symbol = str(getattr(pair, "symbol", "")).upper().strip()
            base = str(getattr(pair, "base", "")).upper().strip()
            quote = str(getattr(pair, "quote", "")).upper().strip()
            pip_size = float(getattr(pair, "pip_size", 0.0))
            tier = str(getattr(pair, "tier", "")).upper().strip()
            if (
                not symbol
                or len(base) != 3
                or len(quote) != 3
                or symbol != base + quote
                or not isfinite(pip_size)
                or pip_size <= 0
                or tier not in {"A", "B"}
            ):
                raise OperationalStoreUnavailable(
                    f"invalid configured reference symbol: {symbol or 'UNKNOWN'}"
                )
            rows.append(
                {
                    "symbol": symbol,
                    "base_currency": base,
                    "quote_currency": quote,
                    "pip_size": pip_size,
                    "tier": tier,
                    "active": True,
                }
            )
        if not rows:
            raise OperationalStoreUnavailable("reference symbol bootstrap cannot be empty")
        try:
            self.client.table("fx_symbols").upsert(
                rows,
                on_conflict="symbol",
            ).execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(
                f"fx_symbols reference bootstrap failed: {exc}"
            ) from exc

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


    def start_scanner_run(
        self,
        *,
        mode: str = "DEMO_ONLY",
        code_version: str,
        data_contract_version: str = "0.4",
        started_at: datetime | None = None,
    ) -> str:
        """Create one durable producer run and return its database UUID."""
        mode = str(mode).upper()
        if mode not in {"RESEARCH_ONLY", "PAPER_ONLY", "DEMO_ONLY", "REAL_MONEY_CANDIDATE"}:
            raise ValueError("invalid scanner run mode")
        if mode == "REAL_MONEY_CANDIDATE":
            raise OperationalStoreUnavailable(
                "signal producer is demo/research only; real-money candidate mode is forbidden"
            )
        row = {
            "started_at": (started_at or datetime.now(tz=UTC)).astimezone(UTC).isoformat(),
            "mode": mode,
            "status": "RUNNING",
            "code_version": str(code_version or "UNKNOWN"),
            "data_contract_version": str(data_contract_version),
        }
        try:
            response = self.client.table("scanner_runs").insert(row).execute()
            rows = list(response.data or [])
        except Exception as exc:
            raise OperationalStoreUnavailable(f"scanner_runs insert failed: {exc}") from exc
        if len(rows) != 1 or not rows[0].get("id"):
            raise OperationalStoreUnavailable("scanner_runs insert did not return exactly one id")
        return str(rows[0]["id"])

    def finish_scanner_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: datetime | None = None,
    ) -> None:
        if not str(run_id).strip():
            raise ValueError("run_id is required")
        payload = {
            "status": str(status).upper(),
            "finished_at": (finished_at or datetime.now(tz=UTC)).astimezone(UTC).isoformat(),
        }
        try:
            response = (
                self.client.table("scanner_runs")
                .update(payload)
                .eq("id", str(run_id))
                .execute()
            )
            rows = list(response.data or [])
        except Exception as exc:
            raise OperationalStoreUnavailable(f"scanner_runs finish failed: {exc}") from exc
        if len(rows) != 1:
            raise OperationalStoreUnavailable(
                f"scanner_runs finish expected one row, got {len(rows)}"
            )

    def get_latest_currency_macro_states(
        self,
        currencies: tuple[str, ...] | list[str],
    ) -> dict[str, dict[str, Any]]:
        """Read newest durable macro snapshot per requested currency.

        Missing currencies are omitted instead of being synthesized as neutral.
        """
        fields = (
            "currency,observed_at,rate_score,central_bank_score,inflation_score,"
            "growth_score,labour_score,yield_score,risk_score,positioning_score,"
            "macro_score,coverage,freshness_seconds,evidence"
        )
        output: dict[str, dict[str, Any]] = {}
        for raw in currencies:
            currency = str(raw).upper().strip()
            if len(currency) != 3:
                raise ValueError(f"invalid currency code: {raw}")
            try:
                response = (
                    self.client.table("currency_macro_state")
                    .select(fields)
                    .eq("currency", currency)
                    .order("observed_at", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = list(response.data or [])
            except Exception as exc:
                raise OperationalStoreUnavailable(
                    f"currency_macro_state read failed for {currency}: {exc}"
                ) from exc
            if len(rows) > 1:
                raise OperationalStoreUnavailable(
                    f"currency_macro_state returned multiple latest rows for {currency}"
                )
            if rows:
                output[currency] = dict(rows[0])
        return output

    def write_currency_strength_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            self.client.table("currency_strength").insert(rows).execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(f"currency_strength write failed: {exc}") from exc

    def write_pair_ranking_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            self.client.table("pair_rankings").insert(rows).execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(f"pair_rankings write failed: {exc}") from exc

    def write_signal_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        for row in rows:
            if str(row.get("state", "")).upper() == "EXECUTION_READY":
                guards = row.get("active_guards")
                score = row.get("final_score")
                coverage = row.get("data_coverage")
                if guards not in ([], ()):
                    raise OperationalStoreUnavailable(
                        "refusing to persist EXECUTION_READY with active guards"
                    )
                if score is None or float(score) < self.execution_ready_score_floor:
                    raise OperationalStoreUnavailable(
                        "refusing to persist EXECUTION_READY below score "
                        f"{self.execution_ready_score_floor:g}"
                    )
                if coverage is None or float(coverage) < 0.80:
                    raise OperationalStoreUnavailable(
                        "refusing to persist EXECUTION_READY below coverage 0.80"
                    )
        try:
            self.client.table("signals").insert(rows).execute()
        except Exception as exc:
            raise OperationalStoreUnavailable(f"signals write failed: {exc}") from exc

    def list_signals_for_run(self, run_id: str) -> tuple[dict[str, Any], ...]:
        if not str(run_id).strip():
            raise ValueError("run_id is required")
        fields = (
            "id,run_id,observed_at,symbol,direction,setup_type,state,"
            "final_score,active_guards,data_coverage,expires_at"
        )
        try:
            response = (
                self.client.table("signals")
                .select(fields)
                .eq("run_id", str(run_id))
                .order("observed_at", desc=True)
                .execute()
            )
            return tuple(dict(row) for row in (response.data or []))
        except Exception as exc:
            raise OperationalStoreUnavailable(f"signals run read failed: {exc}") from exc
