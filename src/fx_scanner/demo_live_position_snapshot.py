from __future__ import annotations

from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy


def run() -> int:
    """Read the current cTrader DEMO account and positions without mutations.

    This intentionally has no Supabase execution-control dependency, does not
    require the autotrade opt-in, and never calls an order/protection manager.
    Broker truth comes directly from trader, unrealized-PnL and reconcile API
    requests. Passing store=None also guarantees that the snapshot itself does
    not write telemetry or trajectory state to the database.
    """

    cfg = load_project_config(None)
    policy = load_execution_policy(None)

    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_POSITION_SNAPSHOT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_POSITION_SNAPSHOT_REQUIRE_DEMO")

    symbols = [pair.symbol for pair in cfg.pairs]
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    try:
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
            "orders_mutated=0 database_writes=0"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
