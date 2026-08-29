from __future__ import annotations

import os
from typing import Iterable

from ..exceptions import ConfigurationError
from .ctrader_gateway import CTraderExecutionGateway
from .ctrader_session import CTraderOpenApiSession
from .mt5_gateway import MT5ExecutionGateway
from .mt5_session import PersistentMT5Session
from .policy import ExecutionPolicy
from .runtime import BackoffPolicy, CircuitBreaker


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def build_broker_gateway(
    policy: ExecutionPolicy,
    symbols: Iterable[str],
    *,
    backend: str | None = None,
    mt5_terminal_path: str | None = None,
):
    """Build and connect one explicitly selected broker backend.

    No automatic cTrader->MT5 failover is performed. Cross-broker failover can
    duplicate exposure and must remain an explicit operator action.
    """
    selected = str(backend or policy.broker.get("preferred", "CTRADER")).upper()
    if selected == "CTRADER":
        cfg = policy.ctrader
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
        gateway = MT5ExecutionGateway(terminal_path=mt5_terminal_path)
        reconnect = policy.runtime.get("reconnect", {})
        breaker = policy.runtime.get("circuit_breaker", {})
        session = PersistentMT5Session(
            gateway,
            backoff=BackoffPolicy(
                initial_seconds=float(reconnect.get("backoff_initial_seconds", 1)),
                multiplier=float(reconnect.get("backoff_multiplier", 2)),
                max_seconds=float(reconnect.get("backoff_max_seconds", 30)),
            ),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(breaker.get("failure_threshold", 3)),
                recovery_seconds=float(breaker.get("recovery_seconds", 30)),
            ),
        )
        session.ensure_connected(max_attempts=int(reconnect.get("max_attempts", 3)))
        return gateway, session

    raise ConfigurationError(f"unsupported broker backend: {selected}")
