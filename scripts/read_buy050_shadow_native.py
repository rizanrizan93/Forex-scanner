"""Ephemeral BUY050 shadow inputs from authorized VPS (read-only SQLite).

This output stays within the GitHub Actions job. It is NEVER committed or sent
to the Streamlit frontend. No bridge lease, checkpoint, order, or service writes.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/var/lib/rizan-buy050-bridge")
SEED = Path("/opt/rizan-buy050-bridge/BTC_SEED_PACKET.json")
PROFILE = "13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"


def read():
    now = datetime.now(timezone.utc)
    db = ROOT / "checkpoints.sqlite"
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=8)
    try:
        con.execute("PRAGMA query_only=ON")
        rows = con.execute("SELECT key,state FROM checkpoints").fetchall()
    finally:
        con.close()
    out = {"as_of": now.isoformat(), "read_only": True, "states": {}, "btc_feed": None}
    accounts = set()
    for key, raw in rows:
        parts = key.split(":")
        symbol = None
        if len(parts) == 3 and parts[0] == "TPX_13bfa137" and parts[2] == "XAUUSD":
            account, symbol = parts[1], "XAUUSD"
        elif len(parts) == 3 and parts[0] == "TPE_13bfa137" and parts[2] == "EURUSD":
            account, symbol = parts[1], "EURUSD"
        elif len(parts) == 4 and parts[0] == "TPBTC" and parts[1] == PROFILE and parts[3] == "BTCUSD":
            account, symbol = parts[2], "BTCUSD"
        if symbol is None or not re.fullmatch(r"[1-9][0-9]{0,18}", account) or not account.endswith("7903"):
            continue
        if symbol in out["states"]:
            raise ValueError("DUPLICATE_NATIVE_STATE")
        accounts.add(account)
        state = json.loads(raw)
        if state.get("Symbol") != symbol or str(state.get("AccountNumber")) != account:
            raise ValueError("NATIVE_STATE_IDENTITY_MISMATCH")
        fields = [
            "LastSignalUtc", "LastRealExitUtc", "LastBarUtc", "Quarantined",
            "XauResumeUtc", "XauDay", "XauDaySignals",
        ] if symbol == "XAUUSD" else [
            "LastSignalUtc", "LastRealExitUtc", "LastBarUtc", "Quarantined", "Eur"
        ] if symbol == "EURUSD" else [
            "LastSignal", "Fault", "ExitPending", "WeekendLockUntil",
            "Sending", "BatchActive", "BatchRemaining",
        ]
        out["states"][symbol] = {field: state.get(field) for field in fields if field in state}
    if len(accounts) != 1 or set(out["states"]) != {"XAUUSD", "EURUSD", "BTCUSD"}:
        raise ValueError("FULL_ACCOUNT_NATIVE_STATES_REQUIRED")
    out["account_binding"] = hashlib.sha256(next(iter(accounts)).encode()).hexdigest()

    # Full deterministic BTC feed is needed for original 2019-seeded EMA/ATR.
    # Read seed and complete extension minutes without modifying the DB. A
    # gap prevents publication instead of fabricating a candle.
    try:
        seed = json.loads(SEED.read_text())
        if seed.get("source") != "BITSTAMP_BTCUSD_M1" or seed.get("contract") != "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND":
            raise ValueError("BTC_SEED_IDENTITY")
        through = int(now.timestamp()) // 3600 * 3600
        start = 1792108800
        if seed.get("through") != start or len(seed.get("bars", [])) != 68280:
            raise ValueError("BTC_SEED_COVERAGE")
        hourlies = list(seed["bars"])
        db = ROOT / "btc-m1.sqlite"
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            con.execute("PRAGMA query_only=ON")
            cursor = con.execute("SELECT at,o,h,l,c FROM minutes WHERE at>=? AND at<? ORDER BY at", (start, through))
            expected = start
            cur_hour = None
            opening = high = low = close = None
            count = 0
            for at, o, h, l, c in cursor:
                if at != expected:
                    raise ValueError("BTC_EXTENSION_GAP")
                expected += 60
                bucket = at - at % 3600
                if cur_hour != bucket:
                    if cur_hour is not None:
                        if count != 60:
                            raise ValueError("BTC_PARTIAL_HOUR")
                        hourlies.append([cur_hour, opening, high, low, close, count])
                    cur_hour, opening, high, low, close, count = bucket, o, h, l, c, 1
                else:
                    high, low, close, count = max(high, h), min(low, l), c, count + 1
            if cur_hour is not None:
                if count != 60:
                    raise ValueError("BTC_PARTIAL_FINAL_HOUR")
                hourlies.append([cur_hour, opening, high, low, close, count])
            if expected != through:
                raise ValueError("BTC_EXTENSION_NOT_CURRENT")
        finally:
            con.close()
        out["btc_feed"] = {
            "contract": "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND",
            "source": "BITSTAMP_BTCUSD_M1", "through": through, "bars": hourlies,
        }
    except (OSError, ValueError, sqlite3.Error, TypeError) as exc:
        out["btc_feed"] = None
        out["btc_feed_status"] = type(exc).__name__
    return out


if __name__ == "__main__":
    print(json.dumps(read(), allow_nan=False, separators=(",", ":")))
