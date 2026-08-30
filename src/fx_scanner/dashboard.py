from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import FXScannerError


class DashboardReadError(FXScannerError):
    """Read-only dashboard query failed."""


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    latest_run: dict[str, Any] | None
    rankings: tuple[dict[str, Any], ...]
    signals: tuple[dict[str, Any], ...]
    heartbeats: tuple[dict[str, Any], ...]
    macro: tuple[dict[str, Any], ...]
    performance: tuple[dict[str, Any], ...]
    broker_account: dict[str, Any] | None
    broker_positions: tuple[dict[str, Any], ...]


class SupabaseDashboardReader:
    """Read-only dashboard adapter.

    The dashboard is intentionally outside the scanner/execution hot path.
    It reads durable snapshots already written by runtime/research workers and
    never submits orders or mutates execution state.
    """

    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in (getattr(response, "data", None) or [])]

    def latest_run(self) -> dict[str, Any] | None:
        try:
            response = (
                self.client.table("scanner_runs")
                .select(
                    "id,started_at,finished_at,mode,status,code_version,"
                    "data_contract_version"
                )
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"scanner_runs read failed: {exc}") from exc
        rows = self._rows(response)
        return rows[0] if rows else None

    def rankings_for_run(
        self,
        run_id: str | None,
        *,
        limit: int = 15,
    ) -> tuple[dict[str, Any], ...]:
        if not run_id:
            return ()
        try:
            response = (
                self.client.table("pair_rankings")
                .select(
                    "observed_at,symbol,direction,macro_edge,technical_edge,"
                    "cross_asset_score,session_score,volatility_score,spread_score,"
                    "pair_opportunity_score,rank,coverage"
                )
                .eq("run_id", str(run_id))
                .order("rank")
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"pair_rankings read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_signals(self, *, limit: int = 30) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("signals")
                .select(
                    "observed_at,symbol,direction,setup_type,state,pair_score,"
                    "execution_score,final_score,entry_low,entry_high,sl,tp1,tp2,"
                    "rr1,rr2,macro_bias,h4_bias,h1_bias,active_guards,"
                    "data_coverage,expires_at"
                )
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"signals read failed: {exc}") from exc
        return tuple(self._rows(response))

    def heartbeats(self) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select("worker_name,observed_at,healthy,lag_seconds,details")
                .order("observed_at", desc=True)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"runtime_heartbeats read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_macro(self, *, raw_limit: int = 96) -> tuple[dict[str, Any], ...]:
        """Return the newest durable macro snapshot per currency."""
        try:
            response = (
                self.client.table("currency_macro_state")
                .select(
                    "currency,observed_at,rate_score,central_bank_score,"
                    "inflation_score,growth_score,labour_score,yield_score,"
                    "risk_score,positioning_score,macro_score,coverage,"
                    "freshness_seconds"
                )
                .order("observed_at", desc=True)
                .limit(int(raw_limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"currency_macro_state read failed: {exc}") from exc

        newest: dict[str, dict[str, Any]] = {}
        for row in self._rows(response):
            currency = str(row.get("currency", "")).upper()
            if currency and currency not in newest:
                newest[currency] = row
        return tuple(newest[key] for key in sorted(newest))

    def latest_performance(self, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("model_performance")
                .select(
                    "as_of,setup_type,symbol,session,regime,sample_scope,"
                    "trades,wins,losses,win_rate,expectancy_r,profit_factor,"
                    "max_drawdown_r"
                )
                .order("as_of", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"model_performance read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_broker_account(self) -> dict[str, Any] | None:
        try:
            response = (
                self.client.table("broker_account_state")
                .select(
                    "backend,account_id,snapshot_id,observed_at,broker_name,"
                    "environment,currency,balance,equity,floating_profit,margin,"
                    "margin_free,margin_level,leverage,trade_allowed,"
                    "connection_healthy,metadata"
                )
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"broker_account_state read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        return rows[0] if rows else None

    def broker_positions_for_account(
        self,
        account: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], ...]:
        if not account or not account.get("snapshot_id"):
            return ()
        try:
            response = (
                self.client.table("broker_position_state")
                .select(
                    "observed_at,position_id,symbol,side,volume,open_price,"
                    "current_price,sl,tp,profit,swap,magic,comment,opened_at"
                )
                .eq("backend", str(account["backend"]))
                .eq("account_id", str(account["account_id"]))
                .eq("snapshot_id", str(account["snapshot_id"]))
                .order("profit", desc=True)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"broker_position_state read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def snapshot(self) -> DashboardSnapshot:
        run = self.latest_run()
        rankings = self.rankings_for_run(None if run is None else run.get("id"))
        broker_account = self.latest_broker_account()
        broker_positions = self.broker_positions_for_account(broker_account)
        return DashboardSnapshot(
            latest_run=run,
            rankings=rankings,
            signals=self.latest_signals(),
            heartbeats=self.heartbeats(),
            macro=self.latest_macro(),
            performance=self.latest_performance(),
            broker_account=broker_account,
            broker_positions=broker_positions,
        )
