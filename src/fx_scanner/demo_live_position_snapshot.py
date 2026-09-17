from __future__ import annotations

import os

from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .exceptions import ConfigurationError
from .execution.ctrader_session import CTraderOpenApiSession
from .execution.ctrader_tokens import CTraderTokenStateStore
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def run() -> int:
    """Read current cTrader DEMO truth and persist research telemetry only.

    The broker session remains strictly mutation-free: it has no refresh token,
    no token persistence callback and no execution gateway.  The only writes are
    Supabase telemetry rows for account/open-position state plus the bounded
    sampled MAE/MFE trajectory maintained by ``capture_ctrader_demo_snapshot``.
    An expired/invalid access token therefore fails closed instead of refreshing
    credentials or reaching any order/protection mutation path.
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
    store = SupabaseOperationalStore.from_env()

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
            store=store,
            phase="READ_ONLY_PERSISTED",
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
            f"snapshot_id={snapshot.snapshot_id or 'NONE'} "
            "orders_mutated=0 token_refreshes=0 telemetry_persisted=1"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
