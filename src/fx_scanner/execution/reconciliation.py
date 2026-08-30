from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from typing import Any, Mapping

from ..exceptions import FXScannerError
from .models import OrderIntent, OrderSide, OrderType
from .position_sizer import size_position

UTC = timezone.utc


class RevalidationBlocked(FXScannerError):
    pass


@dataclass(frozen=True, slots=True)
class RevalidationMetrics:
    research_bid: float
    research_ask: float
    execution_bid: float
    execution_ask: float
    research_age_seconds: float
    execution_age_seconds: float
    mid_divergence_pips: float
    research_spread_pips: float
    execution_spread_pips: float
    spread_ratio: float
    entry_drift_pips: float
    rr: float
    internal_latency_ms: float


@dataclass(frozen=True, slots=True)
class RevalidatedOrder:
    original_intent: OrderIntent
    prepared_intent: OrderIntent
    account_snapshot: Any
    metrics: RevalidationMetrics


class DualFeedRevalidator:
    """Fast execution-side reconciliation for cTrader research -> MT5 execution.

    It never reruns the full strategy. It verifies that the HFM execution venue
    still agrees enough with the research setup to preserve price geometry,
    structural invalidation, RR, spread and risk sizing.
    """

    def __init__(
        self,
        *,
        research_quotes,
        execution_gateway,
        symbol_resolver,
        pip_sizes: Mapping[str, float],
        config: Mapping[str, Any],
        clock=monotonic,
        wall_clock=lambda: datetime.now(tz=UTC),
    ):
        self.research_quotes = research_quotes
        self.execution_gateway = execution_gateway
        self.symbol_resolver = symbol_resolver
        self.pip_sizes = {str(k).upper(): float(v) for k, v in pip_sizes.items()}
        self.config = dict(config)
        self.clock = clock
        self.wall_clock = wall_clock

    @staticmethod
    def _age(now: datetime, timestamp: datetime) -> float:
        if timestamp.tzinfo is None:
            raise RevalidationBlocked("QUOTE_TIMESTAMP_NAIVE")
        age = (now - timestamp.astimezone(UTC)).total_seconds()
        if age < -1.0:
            raise RevalidationBlocked(f"QUOTE_TIMESTAMP_IN_FUTURE:{age:.3f}")
        return max(0.0, age)

    @staticmethod
    def _validate_quote(label: str, quote) -> None:
        values = (float(quote.bid), float(quote.ask))
        if not all(isfinite(x) and x > 0 for x in values):
            raise RevalidationBlocked(f"{label}_QUOTE_INVALID")
        if float(quote.ask) < float(quote.bid):
            raise RevalidationBlocked(f"{label}_QUOTE_CROSSED")

    def revalidate(self, intent: OrderIntent) -> RevalidatedOrder:
        started = self.clock()
        if intent.order_type != OrderType.MARKET and not bool(self.config.get("allow_pending_orders", False)):
            raise RevalidationBlocked("PENDING_ORDER_REVALIDATION_DISABLED")

        canonical = intent.symbol.upper()
        try:
            pip = self.pip_sizes[canonical]
        except KeyError as exc:
            raise RevalidationBlocked(f"PIP_SIZE_MISSING:{canonical}") from exc
        if pip <= 0:
            raise RevalidationBlocked(f"PIP_SIZE_INVALID:{canonical}")

        resolved = self.symbol_resolver.resolve(canonical)
        research = self.research_quotes.quote(canonical)
        execution = self.execution_gateway.quote(resolved.broker_symbol)
        self._validate_quote("RESEARCH", research)
        self._validate_quote("EXECUTION", execution)

        now = self.wall_clock()
        research_age = self._age(now, research.timestamp)
        execution_age = self._age(now, execution.timestamp)
        if research_age > float(self.config.get("research_quote_max_age_seconds", 2.0)):
            raise RevalidationBlocked(f"RESEARCH_QUOTE_STALE:{research_age:.3f}")
        if execution_age > float(self.config.get("execution_quote_max_age_seconds", 1.0)):
            raise RevalidationBlocked(f"EXECUTION_QUOTE_STALE:{execution_age:.3f}")

        research_mid = (float(research.bid) + float(research.ask)) / 2.0
        execution_mid = (float(execution.bid) + float(execution.ask)) / 2.0
        divergence_pips = abs(execution_mid - research_mid) / pip
        if divergence_pips > float(self.config.get("max_mid_divergence_pips", 2.0)):
            raise RevalidationBlocked(f"BROKER_FEED_DIVERGENCE_BLOCK:{divergence_pips:.3f}")

        research_spread = (float(research.ask) - float(research.bid)) / pip
        execution_spread = (float(execution.ask) - float(execution.bid)) / pip
        max_exec_spread = float(self.config.get("max_execution_spread_pips", 4.0))
        if execution_spread > max_exec_spread:
            raise RevalidationBlocked(f"SPREAD_BLOCK:{execution_spread:.3f}")

        spread_floor = float(self.config.get("spread_ratio_floor_pips", 0.10))
        spread_ratio = execution_spread / max(research_spread, spread_floor)
        if spread_ratio > float(self.config.get("max_spread_ratio_vs_research", 12.0)):
            raise RevalidationBlocked(f"SPREAD_DIVERGENCE_BLOCK:{spread_ratio:.3f}")

        executable = float(execution.ask if intent.side == OrderSide.BUY else execution.bid)
        if intent.side == OrderSide.BUY:
            if not (intent.stop_loss < executable < intent.take_profit):
                raise RevalidationBlocked("STRUCTURE_INVALID")
            reward = intent.take_profit - executable
            risk = executable - intent.stop_loss
        else:
            if not (intent.take_profit < executable < intent.stop_loss):
                raise RevalidationBlocked("STRUCTURE_INVALID")
            reward = executable - intent.take_profit
            risk = intent.stop_loss - executable
        if risk <= 0 or reward <= 0:
            raise RevalidationBlocked("STRUCTURE_INVALID")

        reference_entry = float(
            intent.entry_price
            if intent.entry_price is not None
            else (research.ask if intent.side == OrderSide.BUY else research.bid)
        )
        entry_drift_pips = abs(executable - reference_entry) / pip
        original_risk_pips = abs(reference_entry - intent.stop_loss) / pip
        absolute_limit = float(self.config.get("max_entry_drift_pips", 2.0))
        r_limit = float(self.config.get("max_entry_drift_r", 0.15)) * original_risk_pips
        allowed_drift = min(absolute_limit, r_limit) if original_risk_pips > 0 else absolute_limit
        if entry_drift_pips > allowed_drift:
            raise RevalidationBlocked(
                f"CHASE_BLOCK:drift={entry_drift_pips:.3f}:allowed={allowed_drift:.3f}"
            )

        rr = reward / risk
        if rr < float(self.config.get("min_rr", 1.5)):
            raise RevalidationBlocked(f"RR_BLOCK:{rr:.3f}")

        account = self.execution_gateway.account_snapshot()
        expected_currency = str(self.config.get("expected_account_currency", "")).upper().strip()
        actual_currency = str(getattr(account, "currency", "") or "").upper().strip()
        if expected_currency and actual_currency != expected_currency:
            raise RevalidationBlocked(
                f"ACCOUNT_CURRENCY_MISMATCH:{actual_currency or 'UNKNOWN'}!={expected_currency}"
            )

        spec = self.execution_gateway.symbol_trade_spec(resolved.broker_symbol)
        expected_contract = self.config.get("expected_fx_contract_size")
        contract_size = getattr(spec, "contract_size", None)
        if expected_contract is not None:
            if contract_size is None or abs(float(contract_size) - float(expected_contract)) > 1e-9:
                raise RevalidationBlocked(
                    f"CENT_CONTRACT_MISMATCH:{contract_size}!={float(expected_contract)}"
                )

        volume = size_position(
            equity=float(account.equity),
            risk_pct=float(intent.risk_pct),
            entry_price=executable,
            stop_loss=float(intent.stop_loss),
            spec=spec,
        )

        elapsed_ms = (self.clock() - started) * 1000.0
        max_latency = float(self.config.get("max_internal_revalidation_ms", 500.0))
        if elapsed_ms > max_latency:
            raise RevalidationBlocked(f"REVALIDATION_LATENCY_BLOCK:{elapsed_ms:.1f}ms")

        prepared = replace(
            intent,
            broker_symbol=resolved.broker_symbol,
            volume=volume,
            entry_price=executable if intent.order_type == OrderType.MARKET else intent.entry_price,
        )
        metrics = RevalidationMetrics(
            research_bid=float(research.bid),
            research_ask=float(research.ask),
            execution_bid=float(execution.bid),
            execution_ask=float(execution.ask),
            research_age_seconds=research_age,
            execution_age_seconds=execution_age,
            mid_divergence_pips=divergence_pips,
            research_spread_pips=research_spread,
            execution_spread_pips=execution_spread,
            spread_ratio=spread_ratio,
            entry_drift_pips=entry_drift_pips,
            rr=rr,
            internal_latency_ms=elapsed_ms,
        )
        return RevalidatedOrder(intent, prepared, account, metrics)
