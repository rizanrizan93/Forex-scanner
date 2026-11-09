"""Minimal XAU M15 market-data collector for forecast display (LIVE read-only).

No positions, account balances, orders, token rotation or cBot state is read.
Only last fully CLOSED broker M1 and M15 bars from the same 7903 account.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
from fx_scanner.xau_m15_macro_forecast import validate_fast_m15_snapshot

ACCOUNT_SUFFIX = "7903"


class ReadOnly(CTraderOpenApiSession):
    allowed = frozenset({
        "ProtoOAApplicationAuthReq",
        "ProtoOAGetAccountListByAccessTokenReq",
        "ProtoOAAccountAuthReq",
        "ProtoOASymbolsListReq",
        "ProtoOASymbolByIdReq",
        "ProtoOAGetTrendbarsReq",
        "ProtoHeartbeatEvent",
    })

    def _send_sync(self, message, **kwargs):
        if message.DESCRIPTOR.name not in self.allowed:
            raise RuntimeError("XAU_M15_READ_ONLY_PROTOCOL_GUARD")
        return super()._send_sync(message, **kwargs)


def to_snapshot(m1_bars, m15_bars, *, now):
    if now.tzinfo is None:
        raise ValueError("CURRENT_TIME_MUST_BE_AWARE")
    now = now.astimezone(UTC)
    candle_start = now.replace(minute=15 * (now.minute // 15), second=0, microsecond=0)
    closed_m1 = sorted(
        (b for b in m1_bars if b.timestamp + timedelta(minutes=1) <= now),
        key=lambda b: b.timestamp,
    )
    closed_m15 = sorted(
        (b for b in m15_bars if b.timestamp + timedelta(minutes=15) <= now),
        key=lambda b: b.timestamp,
    )
    if not closed_m1 or not closed_m15:
        raise ValueError("NO_CLOSED_BROKER_BARS")
    m1, m15 = closed_m1[-1], closed_m15[-1]
    price_at = m1.timestamp + timedelta(minutes=1)
    m15_closed = m15.timestamp + timedelta(minutes=15)
    if m15_closed != candle_start:
        raise ValueError("M15_PREVIOUS_CANDLE_NOT_CLOSED")
    if not (candle_start <= price_at <= now and (now - price_at).total_seconds() <= 150):
        raise ValueError("M1_PRICE_NOT_FRESH")
    if m1.close <= 0 or m15.close <= 0:
        raise ValueError("INVALID_BROKER_PRICE")
    payload = {
        "contract": "RIZAN_XAU_M15_BROKER_READONLY_V1",
        "symbol": "XAUUSD",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "account_suffix": ACCOUNT_SUFFIX,
        "as_of": now.isoformat(),
        "price_observed_at": price_at.isoformat(),
        "price": float(m1.close),
        "latest_closed_m15": {
            "close": float(m15.close),
            "closed_at": m15_closed.isoformat(),
        },
        "timeframe_fresh": {"M15": True},
        "execution_authority": False,
        "execution_influence": False,
    }
    validate_fast_m15_snapshot(payload, now=now)
    return payload


def collect():
    fields = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN")
    if not all(os.environ.get(k) for k in fields):
        raise RuntimeError("XAU_M15_READONLY_CREDENTIALS_MISSING")
    r = ReadOnly(
        client_id=os.environ[fields[0]], client_secret=os.environ[fields[1]],
        access_token=os.environ[fields[2]], account_id=None,
        environment="live", refresh_token=None, allow_token_refresh=False,
        request_timeout_seconds=20,
    )
    try:
        accounts = [x for x in r.granted_accounts()
                    if x.is_live and str(x.trader_login).endswith(ACCOUNT_SUFFIX)]
        if len(accounts) != 1:
            raise RuntimeError("XAU_M15_7903_LIVE_BINDING_NOT_UNIQUE")
        r.account_id = accounts[0].ctid_trader_account_id
        r.connect()
        r.load_symbols(["XAUUSD"])
        t = datetime.now(UTC)
        m1 = r.historical_bars(
            "XAUUSD", "M1", from_time=t - timedelta(minutes=12),
            to_time=t, count=20,
        )
        m15 = r.historical_bars(
            "XAUUSD", "M15", from_time=t - timedelta(hours=2),
            to_time=t, count=12,
        )
        return to_snapshot(m1, m15, now=datetime.now(UTC))
    finally:
        r.close()


def main(path):
    result = collect()
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    print("XAU_M15_READONLY_VALID candle=" + result["latest_closed_m15"]["closed_at"]
          + " quote=" + result["price_observed_at"])


if __name__ == "__main__":
    main(sys.argv[1])
