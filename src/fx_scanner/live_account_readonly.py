from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .execution.ctrader_session import CTraderOpenApiSession

UTC = timezone.utc
SCOPE_VIEW = 0


def _required(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _money(value: int | float, digits: int | None) -> float:
    return float(value) / (10 ** int(digits or 0))


def _last4(value: int | str) -> str:
    text = str(value or "")
    return text[-4:] if text else ""


def main() -> None:
    # Deliberately read-only: this module never imports an execution gateway and
    # never constructs, submits, amends, or cancels broker orders.
    client_id = _required("CTRADER_CLIENT_ID")
    client_secret = _required("CTRADER_CLIENT_SECRET")
    access_token = _required("CTRADER_ACCESS_TOKEN")
    trader_login = int(_required("CTRADER_TRADER_LOGIN"))
    pinned_raw = str(os.environ.get("CTRADER_ACCOUNT_ID", "")).strip()
    pinned_account_id = int(pinned_raw) if pinned_raw else None

    session = CTraderOpenApiSession(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=None,
        account_id=None,
        environment="live",
        allow_token_refresh=False,
    )
    try:
        accounts = session.granted_accounts()
        diagnostic = {
            "state": "CTRADER_GRANTS_DISCOVERED",
            "configured_trader_login_last4": _last4(trader_login),
            "configured_account_id_last4": _last4(pinned_account_id) if pinned_account_id else "",
            "grant_count": len(accounts),
            "grants": [
                {
                    "trader_login_last4": _last4(account.trader_login),
                    "account_id_last4": _last4(account.ctid_trader_account_id),
                    "is_live": bool(account.is_live),
                    "broker": account.broker_title_short,
                    "permission_scope": int(account.permission_scope),
                }
                for account in accounts
            ],
        }
        print(json.dumps(diagnostic, sort_keys=True), flush=True)

        granted = session.resolve_granted_account(
            trader_login=trader_login,
            require_demo=False,
            pinned_account_id=pinned_account_id,
        )
        if not granted.is_live:
            raise RuntimeError("fail-closed: resolved cTrader account is not LIVE")
        if int(granted.permission_scope) != SCOPE_VIEW:
            raise RuntimeError(
                "fail-closed: LIVE monitor requires cTrader scope=accounts (SCOPE_VIEW); "
                "trading-scope tokens are rejected"
            )

        session.connect()
        trader = session.trader()
        balance = _money(trader.balance, getattr(trader, "moneyDigits", 0))
        pnl_res = session.unrealized_pnl()
        pnl_digits = int(getattr(pnl_res, "moneyDigits", 0) or 0)
        unrealized = sum(
            _money(item.netUnrealizedPnL, pnl_digits)
            for item in tuple(getattr(pnl_res, "positionUnrealizedPnL", ()))
        )
        reconcile = session.reconcile()
        positions = tuple(getattr(reconcile, "position", ()))
        pending_orders = tuple(getattr(reconcile, "order", ()))
        equity = balance + unrealized

        payload = {
            "state": "LIVE_READ_ONLY_OK",
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "environment": "live",
            "broker": granted.broker_title_short,
            "trader_login_last4": _last4(trader_login),
            "account_id_last4": _last4(granted.ctid_trader_account_id),
            "permission_scope": int(granted.permission_scope),
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "unrealized_pnl": round(unrealized, 2),
            "open_positions": len(positions),
            "pending_orders": len(pending_orders),
            "execution_authority": "NONE",
        }
        print(json.dumps(payload, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
