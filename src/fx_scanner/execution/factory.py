from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..exceptions import ConfigurationError
from .ctrader_gateway import CTraderExecutionGateway
from .ctrader_research import CTraderResearchFeed
from .ctrader_session import CTraderOpenApiSession
from .ctrader_tokens import CTraderTokenStateStore
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


def _allow_ctrader_token_refresh() -> bool:
    return os.getenv("CTRADER_DISABLE_TOKEN_REFRESH", "").strip() != "1"


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

    if selected != "CTRADER":
        raise ConfigurationError(
            "Forex Scanner execution is permanently locked to FP Markets cTrader DEMO"
        )

    if selected == "CTRADER":
        cfg = policy.ctrader
        if str(cfg.get("role", "")).upper() != "RESEARCH_AND_DEMO_EXECUTION":
            raise ConfigurationError(
                "configured cTrader backend is not enabled for demo execution"
            )
        if str(cfg.get("environment", "DEMO")).upper() != "DEMO":
            raise ConfigurationError("cTrader execution is hard-locked to DEMO")
        token_store = CTraderTokenStateStore(_required_env(cfg["token_state_path_env"]))
        tokens = token_store.load(
            fallback_access=_required_env(cfg["access_token_env"]),
            fallback_refresh=_required_env(cfg["refresh_token_env"]),
        )
        pinned_account_id = _optional_env(cfg["account_id_env"])
        session = CTraderOpenApiSession(
            client_id=_required_env(cfg["client_id_env"]),
            client_secret=_required_env(cfg["client_secret_env"]),
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_update_callback=token_store.save,
            account_id=None,
            environment="demo",
            request_timeout_seconds=float(cfg.get("request_timeout_seconds", 10)),
            allow_token_refresh=_allow_ctrader_token_refresh(),
        )
        try:
            account = session.resolve_granted_account(
                trader_login=int(_required_env(cfg["trader_login_env"])),
                require_demo=True,
                pinned_account_id=None if pinned_account_id is None else int(pinned_account_id),
            )
            if bool(policy.demo_safety.get("require_trade_scope", True)) and account.permission_scope != 1:
                raise ConfigurationError("cTrader token does not have SCOPE_TRADE")
            session.connect()
            universe = [str(x).upper() for x in symbols]
            session.load_symbols(universe)
            session.subscribe_spots(universe)
            gateway = CTraderExecutionGateway(
                session,
                max_quote_age_seconds=float(cfg.get("max_quote_age_seconds", 5)),
                quote_wait_timeout_seconds=float(cfg.get("quote_wait_timeout_seconds", 5)),
                quote_poll_seconds=float(cfg.get("quote_poll_seconds", 0.10)),
            )
            return gateway, session
        except Exception:
            try:
                session.close()
            except Exception:
                pass
            raise

    raise ConfigurationError(f"unsupported broker backend: {selected}")


def build_ctrader_research_feed(
    policy: ExecutionPolicy,
    symbols: Iterable[str],
) -> CTraderResearchFeed:
    cfg = policy.ctrader
    if str(cfg.get("role", "")).upper() not in {"RESEARCH_ONLY", "RESEARCH_AND_DEMO_EXECUTION"}:
        raise ConfigurationError("cTrader research role is invalid")
    token_store = CTraderTokenStateStore(_required_env(cfg["token_state_path_env"]))
    tokens = token_store.load(
        fallback_access=_required_env(cfg["access_token_env"]),
        fallback_refresh=_required_env(cfg["refresh_token_env"]),
    )
    pinned_account_id = _optional_env(cfg["account_id_env"])
    session = CTraderOpenApiSession(
        client_id=_required_env(cfg["client_id_env"]),
        client_secret=_required_env(cfg["client_secret_env"]),
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_update_callback=token_store.save,
        account_id=None,
        environment=str(cfg.get("environment", "DEMO")).lower(),
        request_timeout_seconds=float(cfg.get("request_timeout_seconds", 10)),
        allow_token_refresh=_allow_ctrader_token_refresh(),
    )
    try:
        session.resolve_granted_account(
            trader_login=int(_required_env(cfg["trader_login_env"])),
            require_demo=bool(cfg.get("require_demo", True)),
            pinned_account_id=None if pinned_account_id is None else int(pinned_account_id),
        )
        session.connect()
        universe = [str(x).upper() for x in symbols]
        session.load_symbols(universe)
        session.subscribe_spots(universe)
        return CTraderResearchFeed(session, universe)
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
    raise ConfigurationError(
        "dual-broker MT5 execution is retired; FP Markets cTrader DEMO only"
    )
