"""Isolated XAUUSD broker candle collector, strictly cTrader market-data READ ONLY.

No open positions, balances, orders, cBot memory, risk limit, or token refresh.
Account binding must be uniquely the LIVE account with suffix 7903.
Candle history is published separately and never used by order execution.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_scanner.xau_decision_checklist_v1 import CANDLE_CONTRACT, REQUIRED_BARS, closed_bars
from fx_scanner.execution.ctrader_market_readonly import ReadOnly

ACCOUNT_SUFFIX = "7903"
TIMEFRAMES = {
    "H1": {"interval": timedelta(hours=1), "days": 28, "count": 600, "required": 210},
    "M15": {"interval": timedelta(minutes=15), "days": 5, "count": 500, "required": 70},
    "M5": {"interval": timedelta(minutes=5), "days": 1, "count": 300, "required": 30},
}


def make_payload(series: dict, *, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("NOW_UTC_REQUIRED")
    now = now.astimezone(UTC)
    bars = {}
    for tf, config in TIMEFRAMES.items():
        step = config["interval"]
        clean = sorted(
            (b for b in series.get(tf) or []
             if b.timestamp.tzinfo is not None and
             b.timestamp.astimezone(UTC) + step <= now),
            key=lambda b: b.timestamp,
        )
        if len(clean) < config["required"]:
            raise ValueError("NOT_ENOUGH_CLOSED_" + tf)
        clean = clean[-max(config["required"], REQUIRED_BARS[tf]):]
        bars[tf] = [
            {"closed_at": (b.timestamp.astimezone(UTC) + step).isoformat(),
             "open": float(b.open), "high": float(b.high),
             "low": float(b.low), "close": float(b.close)}
            for b in clean
        ]
    out = {
        "contract": CANDLE_CONTRACT,
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "symbol": "XAUUSD", "account_suffix": ACCOUNT_SUFFIX,
        "as_of": now.isoformat(), "bars": bars,
        "execution_authority": False, "execution_influence": False,
    }
    for tf in TIMEFRAMES:
        accepted, reason = closed_bars(out, tf, now)
        if reason or len(accepted) < TIMEFRAMES[tf]["required"]:
            raise ValueError("BROKER_CANDLES_NOT_VALID_" + tf + ":" + str(reason))
    return out


def collect() -> dict:
    fields = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN")
    if any(not os.environ.get(k) for k in fields):
        raise RuntimeError("CTRADER_READONLY_CREDENTIALS_UNAVAILABLE")
    session = ReadOnly(
        client_id=os.environ[fields[0]],
        client_secret=os.environ[fields[1]],
        access_token=os.environ[fields[2]],
        account_id=None, environment="live",
        refresh_token=None, allow_token_refresh=False,
        request_timeout_seconds=25,
    )
    try:
        accounts = [
            a for a in session.granted_accounts()
            if a.is_live and str(a.trader_login).endswith(ACCOUNT_SUFFIX)
        ]
        if len(accounts) != 1:
            raise RuntimeError("CTRADER_7903_LIVE_ACCOUNT_NOT_UNIQUE")
        session.account_id = accounts[0].ctid_trader_account_id
        session.connect()
        session.load_symbols(["XAUUSD"])
        clock = datetime.now(UTC)
        series = {
            tf: session.historical_bars(
                "XAUUSD", tf,
                from_time=clock - timedelta(days=cfg["days"]),
                to_time=clock, count=cfg["count"],
            )
            for tf, cfg in TIMEFRAMES.items()
        }
        return make_payload(series, now=datetime.now(UTC))
    finally:
        session.close()


def main(path: str) -> None:
    result = collect()
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, allow_nan=False, separators=(",", ":")),
                    encoding="utf-8")
    print("XAU_DECISION_READONLY_CANDLES",
          "as_of=" + result["as_of"],
          "H1=" + str(len(result["bars"]["H1"])),
          "M15=" + str(len(result["bars"]["M15"])),
          "M5=" + str(len(result["bars"]["M5"])), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
