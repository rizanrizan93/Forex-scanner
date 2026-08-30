from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..exceptions import ConfigurationError
from .ctrader_gateway import CTraderExecutionGateway
from .ctrader_research import CTraderResearchFeed
from .ctrader_session import CTraderOpenApiSession
from .mt5_gateway import MT5ExecutionGateway
from .mt5_session import PersistentMT5Session
from .policy import ExecutionPolicy
from .reconciliation import DualFeedRevalidator
from .runtime import BackoffPolicy, CircuitBreaker
from .symbol_mapping import MT5SymbolResolver


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _session_policies(policy: ExecutionPolicy):
    reconnect = policy.runtime.get("reconnect", {})
    breaker = policy.runtime.get("circuit_breaker", {})
    return (
        BackoffPolicy(
            initial_seconds=float(reconnect.get("backoff_initial_seconds", 1)),
            multiplier=float(reconnect.get("backoff_multiplier", 2)),
            max_seconds=float(reconnect.get("backoff_max_seconds", 30)),
        ),
        CircuitBreaker(
            failure_threshold=int(breaker.get("failure_threshold", 3)),
            recovery_seconds=float(breaker.get("recovery_seconds", 30)),
        ),
    )


def build_broker_gateway(
    policy: ExecutionPolicy,
    symbols: Iterable[str],
    *,
    backend: str | None = None,
    mt5_terminal_path: str | None = None,
):
    """Build one explicitly selected backend. No automatic cross-broker failover."""
    selected = str(
        backend
        or policy.broker.get("execution")
        or policy.broker.get("preferred", "CTRADER")
    ).upper()

    if selected == "CTRADER":
        cfg = policy.ctrader
        if str(cfg.get("role", "")).upper() == "RESEARCH_ONLY":
            raise ConfigurationError(
                "configured cTrader backend is RESEARCH_ONLY; use build_ctrader_research_feed()"
            )
        session = CTraderOpenApiSession(
            client_id=_required_env(cfg["client_id_env"]),
            client_secret=_required_env(cfg["client_secret_env"]),
            access_token=_required_env(cfg["access_token_env"]),
            account_id=int(_required_env(cfg["account_id_env"])),
            environment=str(cfg.get("environment", "DEMO")).lower(),
            request_timeout_seconds=float(cfg.get("request_timeout_seconds", 10)),
        )
        session.connect()
        universe = [str(x).upper() for x in symbols]
        session.load_symbols(universe)
        session.subscribe_spots(universe)
        gateway = CTraderExecutionGateway(
            session,
            max_quote_age_seconds=float(cfg.get("max_quote_age_seconds", 5)),
        )
        return gateway, session

    if selected == "MT5":
        cfg = policy.mt5
        terminal_path = mt5_terminal_path or _optional_env(cfg["terminal_path_env"])
        gateway = MT5ExecutionGateway(
            terminal_path=terminal_path,
            initialize_timeout_ms=int(cfg.get("initialize_timeout_ms", 10_000)),
            login=int(_required_env(cfg["login_env"])),
            server=_required_env(cfg["server_env"]),
            password=_required_env(cfg["password_env"]),
            max_quote_age_seconds=float(cfg.get("max_quote_age_seconds", 1)),
        )
        backoff, breaker = _session_policies(policy)
        session = PersistentMT5Session(gateway, backoff=backoff, circuit_breaker=breaker)
        session.ensure_connected(max_attempts=int(policy.runtime.get("reconnect", {}).get("max_attempts", 3)))
        return gateway, session

    raise ConfigurationError(f"unsupported broker backend: {selected}")


def build_ctrader_research_feed(
    policy: ExecutionPolicy,
    symbols: Iterable[str],
) -> CTraderResearchFeed:
    cfg = policy.ctrader
    if str(cfg.get("role", "")).upper() != "RESEARCH_ONLY":
        raise ConfigurationError("cTrader research feed must be configured RESEARCH_ONLY")
    session = CTraderOpenApiSession(
        client_id=_required_env(cfg["client_id_env"]),
        client_secret=_required_env(cfg["client_secret_env"]),
        access_token=_required_env(cfg["access_token_env"]),
        account_id=int(_required_env(cfg["account_id_env"])),
        environment=str(cfg.get("environment", "DEMO")).lower(),
        request_timeout_seconds=float(cfg.get("request_timeout_seconds", 10)),
    )
    try:
        session.connect()
        universe = [str(x).upper() for x in symbols]
        session.load_symbols(universe)
        session.subscribe_spots(universe)
        return CTraderResearchFeed(session)
    except Exception:
        try:
            session.close()
        except Exception:
            pass
        raise


@dataclass(frozen=True, slots=True)
class DualBrokerStack:
    research_feed: CTraderResearchFeed
    execution_gateway: MT5ExecutionGateway
    execution_session: PersistentMT5Session
    symbol_resolver: MT5SymbolResolver
    revalidator: DualFeedRevalidator


def build_dual_broker_stack(
    policy: ExecutionPolicy,
    symbols: Iterable[str],
    pip_sizes: Mapping[str, float],
) -> DualBrokerStack:
    if not bool(policy.broker.get("dual_feed_single_execution", False)):
        raise ConfigurationError("dual-feed stack is not enabled")
    if str(policy.broker.get("research", "")).upper() != "CTRADER":
        raise ConfigurationError("dual-feed research backend must be CTRADER")
    if str(policy.broker.get("execution", "")).upper() != "MT5":
        raise ConfigurationError("dual-feed execution backend must be MT5")

    universe = tuple(str(x).upper() for x in symbols)
    research_feed = build_ctrader_research_feed(policy, universe)
    execution_gateway = None
    execution_session = None
    try:
        execution_gateway, execution_session = build_broker_gateway(policy, universe, backend="MT5")
        resolver = MT5SymbolResolver(
            execution_gateway,
            explicit_map=policy.mt5.get("symbol_map", {}),
            suffix_candidates=policy.mt5.get("symbol_suffix_candidates", ["", "c"]),
            expected_contract_size=float(policy.reconciliation.get("expected_fx_contract_size", 1000)),
        )
        # Resolve every configured pair at startup. Wrong account type/symbol
        # contract fails before the execution router can ever receive an order.
        for symbol in universe:
            resolver.resolve(symbol)

        account = execution_gateway.account_snapshot()
        expected_currency = str(policy.reconciliation.get("expected_account_currency", "USC")).upper()
        if str(account.currency or "").upper() != expected_currency:
            raise ConfigurationError(
                f"execution account must be HFM Cent currency {expected_currency}; got {account.currency or 'UNKNOWN'}"
            )

        revalidator = DualFeedRevalidator(
            research_quotes=research_feed,
            execution_gateway=execution_gateway,
            symbol_resolver=resolver,
            pip_sizes=pip_sizes,
            config=policy.reconciliation,
        )
        return DualBrokerStack(
            research_feed,
            execution_gateway,
            execution_session,
            resolver,
            revalidator,
        )
    except Exception:
        if execution_gateway is not None:
            try:
                execution_gateway.close()
            except Exception:
                pass
        try:
            research_feed.close()
        except Exception:
            pass
        raise
