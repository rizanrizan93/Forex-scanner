"""Sample BUY050 durable checkpoints at 1-second cadence without modifying LIVE.

Emits sanitized transitions only. Runs as an ephemeral SSH command, not a
background VPS service. Source coverage is measured; intervals outside the
observed window must not be interpreted as no signals.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
DB = Path("/var/lib/rizan-buy050-bridge/checkpoints.sqlite")
PROFILE = "13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
IDENTITIES = {
    "XAUUSD": ("TPX_13bfa137", "44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c", 1),
    "EURUSD": ("TPE_13bfa137", "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a", 3),
    "BTCUSD": ("TPBTC", "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND", 1),
}
EVENTS = {
    "SIGNAL_RECORDED", "INTENT_PREPARED", "BASKET_STATE_ACTIVE",
    "QUARANTINE_ON", "FAULT_ON", "EXIT_PENDING_ON",
    "SIGNAL_CHANGED_DURING_GAP", "CHECKPOINT_RESET"
}

def instant():
    return datetime.now(UTC).isoformat()

def iso(value):
    try:
        if not isinstance(value, str) or not value or value.startswith("0001"):
            return None
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at.astimezone(UTC).isoformat() if at.tzinfo else None
    except (ValueError, OverflowError):
        return None

def identify(key):
    seg = str(key).split(":")
    if len(seg) == 3:
        prefix, account, symbol = seg
    elif len(seg) == 4 and seg[0] == "TPBTC" and seg[1] == PROFILE:
        prefix, account, symbol = seg[0], seg[2], seg[3]
    else:
        return None
    if symbol not in IDENTITIES or prefix != IDENTITIES[symbol][0]:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,18}", account) or not account.endswith("7903"):
        return None
    return symbol, account

def observe(conn):
    items = {}
    account_set = set()
    for key, version, raw in conn.execute("SELECT key, version, state FROM checkpoints"):
        target = identify(key)
        if not target:
            continue
        symbol, account = target
        account_set.add(account)
        if symbol in items:
            raise ValueError("DUPLICATE_SYMBOL_STATE")
        state = json.loads(raw)
        _, contract, schema = IDENTITIES[symbol]
        if (not isinstance(state, dict) or state.get("ContractHash") != contract
            or state.get("Schema") != schema or state.get("Symbol") != symbol
            or str(state.get("AccountNumber")) != account
            or symbol == "XAUUSD" and state.get("ProfileHash") != PROFILE):
            raise ValueError("STATE_PROFILE_MISMATCH")
        if type(version) is not int or version < 0:
            raise ValueError("INVALID_VERSION")
        if symbol == "BTCUSD":
            current = dict(
                signal=iso(state.get("LastSignal")),
                intent=bool(state.get("Sending") or state.get("HandoffSignal")),
                basket=bool(state.get("BatchActive")),
                quarantine=False,
                fault=state.get("Fault") is True,
                exit_pending=state.get("ExitPending") is True,
                origin=(state.get("EntryOrigin") if state.get("EntryOrigin") in ("INCUMBENT", "BTC_H4_BREAK40_ALL") else None),
            )
        else:
            basket = state.get("Basket")
            current = dict(
                signal=iso(state.get("LastSignalUtc")),
                intent=bool(state.get("PendingLabel") or state.get("PendingFirstFill")),
                basket=isinstance(basket, dict),
                quarantine=state.get("Quarantined") is True,
                fault=False,
                exit_pending=False,
                origin=(basket.get("Origin") if isinstance(basket, dict) and basket.get("Origin") in ("INCUMBENT", "XAU_H1_DISPLACEMENT") else None),
            )
        items[symbol] = dict(version=version, **current)
    if len(account_set) != 1 or set(items) != set(IDENTITIES):
        raise ValueError("EXACTLY_ONE_LIVE_ACCOUNT_THREE_STATES_REQUIRED")
    return items

def token(symbol, category, at, signal_at):
    raw = "|".join((symbol, category, at, signal_at or ""))
    return hashlib.sha256(raw.encode("ascii")).hexdigest()[:24]

def event(symbol, category, at, before, after, *, gap=False):
    assert category in EVENTS
    return dict(
        id=token(symbol, category, at, after.get("signal")),
        symbol=symbol,
        event=category,
        observed_at=at,
        signal_at=after.get("signal") if category in {"SIGNAL_RECORDED", "SIGNAL_CHANGED_DURING_GAP"} else None,
        origin=after.get("origin") if category in {"SIGNAL_RECORDED", "SIGNAL_CHANGED_DURING_GAP", "BASKET_STATE_ACTIVE"} else None,
        checkpoint_version=after.get("version"),
        evidence="NATIVE_CHECKPOINT_TRANSITION" if not gap else "INFERRED_BETWEEN_POLL_WINDOWS",
    )

def transition(prev, current, observed_at):
    result = []
    for symbol in IDENTITIES:
        before, after = prev[symbol], current[symbol]
        if after["version"] < before["version"]:
            result.append(event(symbol, "CHECKPOINT_RESET", observed_at, before, after))
        if before.get("signal") != after.get("signal") and after.get("signal"):
            result.append(event(symbol, "SIGNAL_RECORDED", observed_at, before, after))
        for field, name in (
            ("intent", "INTENT_PREPARED"), ("basket", "BASKET_STATE_ACTIVE"),
            ("quarantine", "QUARANTINE_ON"), ("fault", "FAULT_ON"),
            ("exit_pending", "EXIT_PENDING_ON")
        ):
            if after.get(field) is True and before.get(field) is not True:
                result.append(event(symbol, name, observed_at, before, after))
    return result

def watch(seconds=235, interval=1.0, clock=time.monotonic, sleeper=time.sleep, connect=None):
    # SQLite mode=ro and query_only block accidental state writes. Read-only
    # observer always closes its handle and never acquires bridge leases.
    if not 1 <= seconds <= 270 or not .5 <= interval <= 10:
        raise ValueError("WATCH_LIMITS")
    uri = DB.resolve().as_uri() + "?mode=ro"
    db = connect() if connect else sqlite3.connect(uri, uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        started = instant()
        deadline = clock() + seconds
        previous = None
        initial = None
        events = []
        samples = 0
        failures = 0
        longest_gap_s = 0.0
        last_t = None
        while clock() <= deadline:
            tick = clock()
            try:
                current = observe(db)
                observed_at = instant()
                if previous is not None:
                    events.extend(transition(previous, current, observed_at))
                previous = current
                if initial is None:
                    initial = current
                samples += 1
                if last_t is not None:
                    longest_gap_s = max(longest_gap_s, tick-last_t)
                last_t = tick
            except (sqlite3.Error, ValueError, KeyError, TypeError, OSError):
                failures += 1
                if failures > 8:
                    raise RuntimeError("TOO_MANY_READ_FAILURES")
                previous = None # fail closed: don't infer exact transitions over gaps
            remaining = deadline-clock()
            if remaining <= 0:
                break
            sleeper(min(interval, remaining))
        if previous is None or samples < 2:
            raise RuntimeError("INSUFFICIENT_OBSERVATIONS")
        # The baseline is useful to compare with the previous remote run, but
        # never classified as a new signal on its own.
        return dict(
            contract="RIZAN_BUY050_EVENT_AUDIT_V1",
            strategy="P3_BUY050", profile_sha256=PROFILE,
            read_only=True, execution_authority=False, execution_influence=False,
            started_at=started, ended_at=instant(), samples=samples,
            failures=failures, max_interval_s=round(longest_gap_s, 3),
            start_state=initial, end_state=previous, events=events[-240:],
            source="VPS_SQLITE_READONLY_1S_SAMPLING",
            terminal_journal_available=False,
            broker_deals_verified=False,
        )
    finally:
        db.close()

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=int,default=235)
    arg=parser.parse_args()
    print(json.dumps(watch(arg.seconds),allow_nan=False,separators=(",", ":")))
