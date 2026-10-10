"""Live dispatcher module for Turso (libsql) and GitHub Actions trigger.

Dependencies: pip install requests libsql-client
Required environment: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, GITHUB_PAT_TOKEN,
GITHUB_REPO_OWNER, GITHUB_REPO_NAME.

The existing live_order_tickets table must have the columns used below and
ticket_id must be UNIQUE or PRIMARY KEY. Provision the schema separately.
Account labels below are supplied mappings, not verified broker account IDs.
The GitHub workflow must listen for repository_dispatch: trigger-live-order.
HTTP 204 means the event was accepted, not that a broker order was executed.

The executor must atomically claim each ticket, check expiry and fingerprint,
and reconcile broker orders before retrying. A fingerprint is a content hash,
not an authorization signature or a cross-ticket deduplication guarantee.
No orders or network requests run merely by importing this module.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import libsql_client
import requests

ACCOUNT_MAP = {"XAUUSD": "LIVE_LOGIN_4480", "EURUSD": "LIVE_LOGIN_7903"}
EVENT_TYPE = "trigger-live-order"


class DispatchError(RuntimeError):
    """Ticket was persisted, but event delivery failed or is uncertain."""

    def __init__(self, ticket_id, message):
        self.ticket_id = ticket_id
        super().__init__(f"{message}; ticket_id={ticket_id}. Do not create a new ticket to retry.")


def _env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise EnvironmentError(f"Missing environment variable: {name}")
    return value


def _positive_number(name, value):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        result = float(number)
        if result == float("inf") or result <= 0:
            raise ValueError(f"{name} is outside supported numeric range")
        return result
    except (InvalidOperation, TypeError, OverflowError) as exc:
        raise ValueError(f"Invalid {name}") from exc


def _validate(signal_data):
    symbol = str(signal_data.get("symbol", "")).strip().upper()
    side = str(signal_data.get("side", "")).strip().upper()
    if symbol not in ACCOUNT_MAP:
        raise ValueError(f"Unsupported symbol for live trading: {symbol}")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    data = {"account": ACCOUNT_MAP[symbol], "symbol": symbol, "side": side}
    for name in ("volume", "sl", "tp", "risk_pct"):
        if name not in signal_data:
            raise ValueError(f"Missing signal field: {name}")
        data[name] = _positive_number(name, signal_data[name])
    if data["risk_pct"] > 100:
        raise ValueError("risk_pct must not exceed 100")
    if (side == "BUY" and data["sl"] >= data["tp"]) or (
        side == "SELL" and data["tp"] >= data["sl"]
    ):
        raise ValueError("BUY requires sl < tp; SELL requires tp < sl")
    # Entry price, contract sizing and actual account risk require broker checks.
    return data


def _github_config():
    token = _env("GITHUB_PAT_TOKEN")
    owner = _env("GITHUB_REPO_OWNER")
    repo = _env("GITHUB_REPO_NAME")
    for value in (owner, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
            raise ValueError("Invalid GitHub repository owner/name")
    return token, owner, repo


def _trigger(ticket_id, config):
    token, owner, repo = config
    try:
        response = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/dispatches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"event_type": EVENT_TYPE, "client_payload": {"ticket_id": ticket_id}},
            timeout=(10, 30),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise DispatchError(ticket_id, "GitHub delivery outcome is uncertain") from None
    if response.status_code != 204:
        raise DispatchError(ticket_id, f"GitHub dispatch failed (HTTP {response.status_code})")


def dispatch_live_signal(signal_data):
    """Persist a new ticket and dispatch its ID; return metadata on acceptance.

    Example input: {"symbol": "XAUUSD", "side": "BUY", "volume": 0.1,
                    "sl": 2300.0, "tp": 2350.0, "risk_pct": 1.5}
    Every invocation creates a distinct ticket. Do not automatically retry this
    function after errors: an insert or event may already have succeeded.
    """
    data = _validate(signal_data)
    turso_url, turso_token = _env("TURSO_DATABASE_URL"), _env("TURSO_AUTH_TOKEN")
    config = _github_config()  # Validate all required configuration before insert.
    now = datetime.now(timezone.utc)
    ticket_id = f"RZLIVE-{now:%Y%m%dT%H%M%S}-{uuid4().hex}"
    expiry = (now + timedelta(minutes=10)).isoformat()
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    params = [ticket_id, data["account"], data["symbol"], data["side"],
              data["volume"], data["sl"], data["tp"], data["risk_pct"],
              expiry, fingerprint, "PENDING"]
    client = libsql_client.create_client_sync(url=turso_url, auth_token=turso_token)
    try:
        client.execute({"sql": """
            INSERT INTO live_order_tickets
            (ticket_id, account, symbol, side, volume, sl, tp, risk_pct,
             expiry, fingerprint, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, "args": params})
    except Exception:
        raise DispatchError(ticket_id, "Database write failed or its outcome is uncertain") from None
    finally:
        client.close()
    _trigger(ticket_id, config)
    return {"ticket_id": ticket_id, "account": data["account"],
            "expiry": expiry, "fingerprint": fingerprint,
            "status": "PENDING", "github_dispatch_accepted": True}
