from __future__ import annotations

import os

from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .exceptions import ConfigurationError
from .execution.ctrader_session import CTraderOpenApiSession
from .execution.ctrader_tokens import CTraderTokenStateStore
from .execution.policy import load_execution_policy


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def run() -> int:
    """Read the current cTrader DEMO account and positions without mutations.

    Durable token state is read so the snapshot uses the same current access
    token as the trading runtime. The cTrader session is deliberately created
    without a refresh token or persistence callback: an expired/invalid access
    token therefore fails closed rather than refreshing tokens or writing state.
    No order, protection, execution-control or Supabase write path is reachable.
    """

    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    ctrader = policy.ctrader

    if str(ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_POSITION_SNAPSHOT_DEMO_ONLY")
    if not bool(ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_POSITION_SNAPSHOT_REQUIRE_DEMO")

    token_store = CTraderTokenStateStore(_required_env(ctrader["token_state_path_env"]))
    tokens = token_store.load(
        fallback_access=_required_env(ctrader["access_token_env"]),
        fallback_refresh=_required_env(ctrader["refresh_token_env"]),
    )

    pinned_account_id = _optional_env(ctrader["account_id_env"])
    session = CTraderOpenApiSession(
        client_id=_required_env(ctrader["client_id_env"]),
        client_secret=_required_env(ctrader["client_secret_env"]),
        access_token=tokens.access_token,
        refresh_token=None,
        token_update_callback=None,
        account_id=None,
        environment="demo",
        request_timeout_seconds=float(ctrader.get("request_timeout_seconds", 10)),
        allow_token_refresh=False,
    )

    symbols = [pair.symbol for pair in cfg.pairs]
    try:
        session.resolve_granted_account(
            trader_login=int(_required_env(ctrader["trader_login_env"])),
            require_demo=True,
            pinned_account_id=(None if pinned_account_id is None else int(pinned_account_id)),
        )
        session.connect()
        session.load_symbols(symbols)
        session.subscribe_spots(symbols)

        snapshot = capture_ctrader_demo_snapshot(
            session=session,
            store=None,
            phase="READ_ONLY",
        )
        print(
            "CTRADER_DEMO_POSITION_SNAPSHOT_OK "
            f"account_id={snapshot.account.account_id} "
            f"balance={snapshot.account.balance:.8g} "
            f"equity={snapshot.account.equity:.8g} "
            f"floating_pnl={float(snapshot.account.floating_profit or 0.0):.8g} "
            f"margin={float(snapshot.account.margin or 0.0):.8g} "
            f"margin_free={float(snapshot.account.margin_free or 0.0):.8g} "
            f"open_positions={len(snapshot.positions)} "
            "orders_mutated=0 token_refreshes=0 database_writes=0"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
