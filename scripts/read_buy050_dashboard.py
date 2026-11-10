"""Publish a minimal, read-only BUY050 bridge observation.

Runs via sudo on the authorized VPS in an ephemeral GitHub Actions SSH session.
No cTrader/order API, service restarts, token handling or checkpoint mutation.
NEVER publish raw checkpoint JSON, account IDs, position sizes or secrets.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
ROOT = Path("/var/lib/rizan-buy050-bridge")
ACCOUNT_SUFFIX = "7903"
PROFILE = "13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
CONTRACTS = {
    "XAUUSD": ("TPX_13bfa137", "44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c", 1, "XAU_BATCH_SEND_REF_COOLDOWN_V1"),
    "EURUSD": ("TPE_13bfa137", "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a", 3, "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1"),
    "BTCUSD": ("TPBTC", "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND", 1, None),
}


def btc_feed_state(value):
    """Expose only an allowlisted bridge-feed state and safe exception class.

    The VPS health record describes bridge feed generation, NOT acceptance
    by the BTC cBot and NOT evidence of a signal or executable order.
    """
    if value == "ready":
        return "READY", None
    if isinstance(value, str) and value.startswith("unavailable:"):
        kind = value.partition(":")[2]
        error = kind if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", kind) else None
        return "UNAVAILABLE", error
    return "UNKNOWN", None


def utc_text(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.year < 2020:
            return None
        return dt.astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def checkpoint_symbol(key):
    parts = key.split(":")
    if len(parts) == 3 and parts[0] in ("TPX_13bfa137", "TPE_13bfa137"):
        prefix, account, symbol = parts
    elif len(parts) == 4 and parts[0] == "TPBTC" and parts[1] == PROFILE:
        prefix, account, symbol = parts[0], parts[2], parts[3]
    else:
        return None
    expected = CONTRACTS.get(symbol)
    if not expected or expected[0] != prefix or not re.fullmatch(r"[1-9][0-9]{0,18}", account):
        return None
    if not account.endswith(ACCOUNT_SUFFIX):
        return None
    return symbol, account


def snapshot():
    now = datetime.now(UTC)
    output = {
        "contract": "RIZAN_BUY050_READONLY_V1",
        "strategy": "P3_BUY050",
        "source_release": "BUY050_RUNTIMEGUARD_20261108",
        "account_suffix": ACCOUNT_SUFFIX,
        "observed_at": now.isoformat(),
        "read_only": True,
        "execution_authority": False,
        "service_active": False,
        "bridge": {"observed_at": None, "connected": None, "profile_ok": False, "macro_snapshot_present": False, "btc_feed_status": "UNKNOWN", "btc_feed_error": None},
        "symbols": [],
    }
    try:
        service = subprocess.run(
            ["systemctl", "is-active", "rizan-buy050-bridge.service"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        output["service_active"] = service.returncode == 0 and service.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        health = json.loads((ROOT / "health.json").read_text())
        btc_status, btc_error = btc_feed_state(health.get("btc"))
        output["bridge"] = {
            "observed_at": utc_text(health.get("observed_utc")),
            "connected": health["connected"] if type(health.get("connected")) is int and 0 <= health["connected"] <= 3 else None,
            "profile_ok": health.get("profile") == "RIZAN_BUY050_FROZEN_20261107",
            "macro_snapshot_present": health.get("macro_snapshot_present") is True,
            "btc_feed_status": btc_status,
            "btc_feed_error": btc_error,
        }
    except (OSError, ValueError, TypeError, KeyError):
        pass

    db = ROOT / "checkpoints.sqlite"
    connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        states = connection.execute("SELECT key,version,state FROM checkpoints").fetchall()
        leases = connection.execute("SELECT key,expires_at,touched_at FROM bridge_leases").fetchall()
    finally:
        connection.close()

    selected = {}
    account_values = set()
    unrecognized = set()
    for key, version, raw in states:
        identified = checkpoint_symbol(key)
        if not identified:
            # A newly deployed algo may use a new checkpoint prefix/profile.
            # Never declare such checkpoints connected under the OLD identity.
            # Report only the symbol-level mismatch; do not expose raw keys.
            parts = str(key).split(":")
            if (len(parts) >= 3 and parts[-1] in CONTRACTS
                    and re.fullmatch(r"[1-9][0-9]{0,18}", parts[-2])
                    and parts[-2].endswith(ACCOUNT_SUFFIX)):
                unrecognized.add(parts[-1])
            continue
        symbol, account = identified
        if symbol in selected:
            raise ValueError("DUPLICATE_SYMBOL_CHECKPOINT")
        account_values.add(account)
        selected[symbol] = (key, version, json.loads(raw))
    if len(account_values) > 1:
        raise ValueError("MULTIPLE_ACCOUNTS_IN_SCOPE")

    lease_by_key = {k: (expires, touched) for k, expires, touched in leases}
    for symbol, (_, contract_hash, schema, execution_model) in CONTRACTS.items():
        data = {
            "symbol": symbol, "identity_ok": False, "checkpoint_present": False,
            "lease_active": False, "lease_touched_at": None, "checkpoint_version": None,
            "last_bar_at": None, "last_signal_at": None, "checkpoint_basket": False,
            "pending_intent": False, "fault": False, "quarantined": False,
            "weekend_lock_until": None, "unrecognized_checkpoint": symbol in unrecognized,
        }
        if symbol in selected:
            key, version, state = selected[symbol]
            if not isinstance(state, dict):
                raise ValueError("INVALID_CHECKPOINT_STATE")
            data["checkpoint_present"] = True
            ok = state.get("Schema") == schema and state.get("ContractHash") == contract_hash and state.get("Symbol") == symbol
            if symbol == "XAUUSD":
                ok = ok and state.get("ProfileHash") == PROFILE
            if execution_model:
                ok = ok and state.get("ExecutionModel") == execution_model
            data["identity_ok"] = bool(ok)
            data["checkpoint_version"] = version if type(version) is int and version >= 0 else None
            data["last_bar_at"] = utc_text(state.get("LastBarUtc"))
            data["last_signal_at"] = utc_text(state.get("LastSignal" if symbol == "BTCUSD" else "LastSignalUtc"))
            data["checkpoint_basket"] = bool(state.get("Basket")) if symbol != "BTCUSD" else bool(state.get("BatchActive"))
            data["pending_intent"] = bool(state.get("PendingLabel") or state.get("PendingFirstFill") or state.get("XauPendingSignal")) if symbol != "BTCUSD" else bool(state.get("Sending") or state.get("BatchRemaining") or state.get("HandoffSignal"))
            data["fault"] = state.get("Fault") is True if symbol == "BTCUSD" else False
            data["quarantined"] = state.get("Quarantined") is True if symbol != "BTCUSD" else False
            if symbol == "BTCUSD":
                data["weekend_lock_until"] = utc_text(state.get("WeekendLockUntil"))
                data["exit_pending"] = state.get("ExitPending") is True
            lease = lease_by_key.get(key)
            if lease:
                expires, touched = lease
                if type(expires) in (float, int) and type(touched) in (float, int):
                    data["lease_active"] = float(expires) > time.time() and time.time() - float(touched) < 90
                    if 0 <= time.time() - float(touched) <= 86400:
                        data["lease_touched_at"] = datetime.fromtimestamp(float(touched), UTC).isoformat()
        output["symbols"].append(data)
    return output


if __name__ == "__main__":
    print(json.dumps(snapshot(), allow_nan=False, separators=(",", ":")))
