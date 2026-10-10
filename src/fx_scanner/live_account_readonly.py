from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .execution.ctrader_session import CTraderOpenApiSession

UTC = timezone.utc
SCOPE_VIEW = 0
SCOPE_TRADE = 1
ACCOUNT_MAP_LAST4 = {
    "XAUUSD": "4480",
    "EURUSD": "7903",
}


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


def _discover_accounts(*, client_id: str, client_secret: str, access_token: str):
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
        return tuple(session.granted_accounts())
    finally:
        session.close()


def _select_account(accounts, *, symbol: str):
    expected_last4 = ACCOUNT_MAP_LAST4[symbol]
    matches = [
        account
        for account in accounts
        if bool(account.is_live) and _last4(account.trader_login) == expected_last4
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"fail-closed: {symbol} LIVE mapping expected exactly one trader login ending "
            f"{expected_last4}; matches={len(matches)}"
        )
    account = matches[0]
    if int(account.permission_scope) not in {SCOPE_VIEW, SCOPE_TRADE}:
        raise RuntimeError(
            f"fail-closed: unsupported cTrader permission scope {account.permission_scope}"
        )
    return account


def _snapshot_account(*, client_id: str, client_secret: str, access_token: str, symbol: str, account):
    session = CTraderOpenApiSession(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=None,
        account_id=account.ctid_trader_account_id,
        environment="live",
        allow_token_refresh=False,
    )
    try:
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
        return {
            "symbol_lane": symbol,
            "state": "LIVE_READ_ONLY_OK",
            "environment": "live",
            "broker": account.broker_title_short,
            "trader_login_last4": _last4(account.trader_login),
            "account_id_last4": _last4(account.ctid_trader_account_id),
            "permission_scope": int(account.permission_scope),
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "unrealized_pnl": round(unrealized, 2),
            "open_positions": len(positions),
            "pending_orders": len(pending_orders),
            "execution_authority": "NONE",
        }
    finally:
        session.close()


def main() -> None:
    # Deliberately read-only: this module never imports an execution gateway and
    # never constructs, submits, amends, or cancels broker orders. A token may
    # carry SCOPE_TRADE, but this monitor only performs account/data requests.
    client_id = _required("CTRADER_CLIENT_ID")
    client_secret = _required("CTRADER_CLIENT_SECRET")
    access_token = _required("CTRADER_ACCESS_TOKEN")

    accounts = _discover_accounts(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )
    diagnostic = {
        "state": "CTRADER_LIVE_GRANTS_DISCOVERED",
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "grant_count": len(accounts),
        "configured_mapping": ACCOUNT_MAP_LAST4,
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

    snapshots = []
    for symbol in ("XAUUSD", "EURUSD"):
        account = _select_account(accounts, symbol=symbol)
        snapshots.append(
            _snapshot_account(
                client_id=client_id,
                client_secret=client_secret,
                access_token=access_token,
                symbol=symbol,
                account=account,
            )
        )

    print(
        json.dumps(
            {
                "state": "LIVE_MULTI_ACCOUNT_READ_ONLY_OK",
                "observed_at": datetime.now(tz=UTC).isoformat(),
                "accounts": snapshots,
                "execution_authority": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
