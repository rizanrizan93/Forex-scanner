from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import create_client

from .execution.ctrader_gateway import CTraderExecutionGateway
from .execution.ctrader_session import CTraderOpenApiSession
from .execution.models import OrderIntent, OrderSide, OrderType
from .live_account_readonly import ACCOUNT_MAP_LAST4, SCOPE_TRADE, _discover_accounts, _select_account

UTC = timezone.utc
TICKETS_TABLE = "live_order_tickets"
CLAIMS_TABLE = "live_order_claims"
MANUAL_LIVE_ACK = "I_UNDERSTAND_LIVE_ORDER"


def _required(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _db():
    url = _required("SUPABASE_URL")
    key = str(os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not key:
        raise RuntimeError("missing SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _canonical_spec(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row["symbol"]).upper(),
        "account_login_last4": str(row["account_login_last4"]),
        "side": str(row["side"]).upper(),
        "order_type": str(row["order_type"]).upper(),
        "volume": float(row["volume"]),
        "entry_price": None if row.get("entry_price") is None else float(row["entry_price"]),
        "stop_loss": float(row["stop_loss"]),
        "take_profit": float(row["take_profit"]),
        "risk_pct": float(row["risk_pct"]),
        "expires_at": str(row["expires_at"]),
        "order_expires_at": row.get("order_expires_at"),
        "source": str(row.get("source") or "RIZAN_SCANNER"),
        "metadata": row.get("metadata") or {},
    }


def _fingerprint(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _ticket_id(fingerprint: str) -> str:
    return f"RZLIVE-{fingerprint[:16].upper()}"


def _ticket_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket_id": row["ticket_id"],
        "fingerprint": row["fingerprint"],
        "symbol": row["symbol"],
        "account_login_last4": row["account_login_last4"],
        "side": row["side"],
        "order_type": row["order_type"],
        "volume": float(row["volume"]),
        "entry_price": None if row.get("entry_price") is None else float(row["entry_price"]),
        "stop_loss": float(row["stop_loss"]),
        "take_profit": float(row["take_profit"]),
        "risk_pct": float(row["risk_pct"]),
        "expires_at": row["expires_at"],
        "order_expires_at": row.get("order_expires_at"),
    }


def prepare(args: argparse.Namespace) -> int:
    now = datetime.now(tz=UTC)
    symbol = args.symbol.upper()
    order_type = args.order_type.upper()
    entry = None if order_type == "MARKET" else float(args.entry_price)
    if order_type != "MARKET" and args.entry_price is None:
        raise RuntimeError("LIMIT/STOP requires --entry-price")
    order_expiry = None
    if args.order_expires_minutes is not None:
        if order_type == "MARKET":
            raise RuntimeError("MARKET cannot have broker order expiry")
        order_expiry = _iso(now + timedelta(minutes=args.order_expires_minutes))
    spec = {
        "symbol": symbol,
        "account_login_last4": ACCOUNT_MAP_LAST4[symbol],
        "side": args.side.upper(),
        "order_type": order_type,
        "volume": float(args.volume),
        "entry_price": entry,
        "stop_loss": float(args.stop_loss),
        "take_profit": float(args.take_profit),
        "risk_pct": float(args.risk_pct),
        "expires_at": _iso(now + timedelta(minutes=args.ticket_expires_minutes)),
        "order_expires_at": order_expiry,
        "source": "RIZAN_SCANNER",
        "metadata": {"strategy_ref": args.strategy_ref or "manual-ticket"},
    }
    # OrderIntent validates side/SL/entry/TP and the <=1% canonical live risk contract.
    OrderIntent(
        signal_id="PREPARE",
        symbol=spec["symbol"],
        side=OrderSide(spec["side"]),
        order_type=OrderType(spec["order_type"]),
        created_at=now,
        volume=spec["volume"],
        entry_price=spec["entry_price"],
        stop_loss=spec["stop_loss"],
        take_profit=spec["take_profit"],
        risk_pct=spec["risk_pct"],
        expires_at=_parse_dt(spec["order_expires_at"]),
    )
    fingerprint = _fingerprint(spec)
    row = {"ticket_id": _ticket_id(fingerprint), "fingerprint": fingerprint, **spec}
    _db().table(TICKETS_TABLE).insert(row).execute()
    print(json.dumps({"state": "LIVE_TICKET_PREPARED", **_ticket_summary(row)}, sort_keys=True))
    return 0


def _load_ticket(ticket_id: str) -> dict[str, Any]:
    response = _db().table(TICKETS_TABLE).select("*").eq("ticket_id", ticket_id).limit(1).execute()
    rows = list(response.data or [])
    if len(rows) != 1:
        raise RuntimeError("ticket not found or not unique")
    row = dict(rows[0])
    if row["fingerprint"] != _fingerprint(_canonical_spec(row)):
        raise RuntimeError("fail-closed: ticket fingerprint mismatch")
    if _parse_dt(row["expires_at"]) <= datetime.now(tz=UTC):
        raise RuntimeError("fail-closed: approval ticket expired")
    expected = ACCOUNT_MAP_LAST4.get(str(row["symbol"]).upper())
    if not expected or str(row["account_login_last4"]) != expected:
        raise RuntimeError("fail-closed: ticket account mapping mismatch")
    return row


def _broker_context(row: dict[str, Any]):
    client_id = _required("CTRADER_CLIENT_ID")
    client_secret = _required("CTRADER_CLIENT_SECRET")
    access_token = _required("CTRADER_ACCESS_TOKEN")
    accounts = _discover_accounts(client_id=client_id, client_secret=client_secret, access_token=access_token)
    account = _select_account(accounts, symbol=str(row["symbol"]).upper())
    if int(account.permission_scope) != SCOPE_TRADE:
        raise RuntimeError("fail-closed: selected LIVE account lacks SCOPE_TRADE")
    session = CTraderOpenApiSession(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=None,
        account_id=account.ctid_trader_account_id,
        environment="live",
        allow_token_refresh=False,
    )
    session.connect()
    return session, account


def _intent(row: dict[str, Any]) -> OrderIntent:
    return OrderIntent(
        signal_id=str(row["ticket_id"]),
        symbol=str(row["symbol"]),
        side=OrderSide(str(row["side"])),
        order_type=OrderType(str(row["order_type"])),
        created_at=datetime.now(tz=UTC),
        volume=float(row["volume"]),
        entry_price=None if row.get("entry_price") is None else float(row["entry_price"]),
        stop_loss=float(row["stop_loss"]),
        take_profit=float(row["take_profit"]),
        risk_pct=float(row["risk_pct"]),
        expires_at=_parse_dt(row.get("order_expires_at")),
        comment=f"LIVE_APPROVED:{row['ticket_id']}",
    )


def _preflight(row: dict[str, Any]):
    session, account = _broker_context(row)
    try:
        gateway = CTraderExecutionGateway(session)
        snapshot = gateway.account_snapshot()
        if not snapshot.trade_allowed:
            raise RuntimeError("fail-closed: broker reports trading not allowed")
        if snapshot.equity <= 0 or snapshot.margin_free is None or snapshot.margin_free <= 0:
            raise RuntimeError("fail-closed: LIVE account has no usable equity/free margin")
        intent = _intent(row)
        preflight = gateway.preflight(intent, {"comment_prefix": "RIZAN_LIVE_APPROVED"})
        if not preflight.accepted:
            raise RuntimeError(f"broker preflight rejected: {preflight.code}: {preflight.message}")
        expected_margin = float(getattr(preflight.request, "expected_margin", 0.0) or 0.0)
        if expected_margin <= 0:
            raise RuntimeError("fail-closed: expected margin unavailable")
        used_margin = max(0.0, snapshot.equity - float(snapshot.margin_free))
        prospective_ratio = (used_margin + expected_margin) / snapshot.equity
        max_ratio = float(os.environ.get("LIVE_MANUAL_MAX_MARGIN_FRACTION", "0.50"))
        if not 0 < max_ratio <= 0.75:
            raise RuntimeError("LIVE_MANUAL_MAX_MARGIN_FRACTION must be in (0,0.75]")
        if prospective_ratio > max_ratio:
            raise RuntimeError(
                f"fail-closed: prospective margin ratio {prospective_ratio:.3f} exceeds {max_ratio:.3f}"
            )
        return {
            "state": "LIVE_PREFLIGHT_OK",
            "ticket_id": row["ticket_id"],
            "symbol": row["symbol"],
            "account_login_last4": row["account_login_last4"],
            "equity": round(snapshot.equity, 2),
            "margin_free": round(float(snapshot.margin_free), 2),
            "expected_margin": round(expected_margin, 2),
            "prospective_margin_ratio": round(prospective_ratio, 4),
        }
    finally:
        session.close()


def preflight(args: argparse.Namespace) -> int:
    row = _load_ticket(args.ticket_id)
    print(json.dumps(_preflight(row), sort_keys=True))
    return 0


def execute(args: argparse.Namespace) -> int:
    if _required("LIVE_MANUAL_APPROVAL_ENABLED") != MANUAL_LIVE_ACK:
        raise RuntimeError("LIVE manual approval lane is not enabled")
    row = _load_ticket(args.ticket_id)
    expected_phrase = f"APPROVE LIVE {row['ticket_id']}"
    if args.confirmation != expected_phrase:
        raise RuntimeError(f"approval phrase mismatch; expected exactly: {expected_phrase}")

    # Preflight before the one-time claim. A failing preflight does not burn the ticket.
    pf = _preflight(row)
    print(json.dumps(pf, sort_keys=True), flush=True)

    db = _db()
    claim = {
        "ticket_id": row["ticket_id"],
        "fingerprint": row["fingerprint"],
        "github_run_id": str(os.environ.get("GITHUB_RUN_ID") or "manual"),
        "github_actor": str(os.environ.get("GITHUB_ACTOR") or "unknown"),
        "status": "CLAIMED",
    }
    # ticket_id is a PRIMARY KEY: a second approval fails atomically here, before broker submit.
    db.table(CLAIMS_TABLE).insert(claim).execute()
    claimed = True

    session = None
    try:
        session, _ = _broker_context(row)
        gateway = CTraderExecutionGateway(session)
        broker_pf = gateway.preflight(_intent(row), {"comment_prefix": "RIZAN_LIVE_APPROVED"})
        if not broker_pf.accepted:
            result = {"accepted": False, "code": broker_pf.code, "message": broker_pf.message}
        else:
            broker_result = gateway.submit(broker_pf)
            result = {
                "accepted": bool(broker_result.accepted),
                "code": broker_result.code,
                "message": broker_result.message,
                "broker_order_id": broker_result.broker_order_id,
                "broker_position_id": broker_result.broker_position_id,
                "executed_volume": broker_result.executed_volume,
                "executed_price": broker_result.executed_price,
                "protection_verified": broker_result.protection_verified,
            }
        status = "EXECUTED" if result["accepted"] else "REJECTED"
        db.table(CLAIMS_TABLE).update({
            "status": status,
            "broker_order_id": result.get("broker_order_id"),
            "broker_position_id": result.get("broker_position_id"),
            "result": result,
            "finalized_at": _iso(datetime.now(tz=UTC)),
        }).eq("ticket_id", row["ticket_id"]).eq("status", "CLAIMED").execute()
        print(json.dumps({"state": f"LIVE_ORDER_{status}", "ticket_id": row["ticket_id"], "result": result}, sort_keys=True))
        return 0 if result["accepted"] else 2
    except Exception as exc:
        if claimed:
            try:
                db.table(CLAIMS_TABLE).update({
                    "status": "UNKNOWN",
                    "result": {"error_type": type(exc).__name__, "message": str(exc)},
                    "finalized_at": _iso(datetime.now(tz=UTC)),
                }).eq("ticket_id", row["ticket_id"]).eq("status", "CLAIMED").execute()
            except Exception:
                pass
        raise
    finally:
        if session is not None:
            session.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RIZAN cTrader LIVE manual-approval lane")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--symbol", choices=sorted(ACCOUNT_MAP_LAST4), required=True)
    p.add_argument("--side", choices=[x.value for x in OrderSide], required=True)
    p.add_argument("--order-type", choices=[x.value for x in OrderType], required=True)
    p.add_argument("--volume", type=float, required=True)
    p.add_argument("--entry-price", type=float)
    p.add_argument("--stop-loss", type=float, required=True)
    p.add_argument("--take-profit", type=float, required=True)
    p.add_argument("--risk-pct", type=float, required=True)
    p.add_argument("--ticket-expires-minutes", type=int, default=15)
    p.add_argument("--order-expires-minutes", type=int)
    p.add_argument("--strategy-ref", default="")
    p.set_defaults(func=prepare)

    p = sub.add_parser("preflight")
    p.add_argument("--ticket-id", required=True)
    p.set_defaults(func=preflight)

    p = sub.add_parser("execute")
    p.add_argument("--ticket-id", required=True)
    p.add_argument("--confirmation", required=True)
    p.set_defaults(func=execute)
    return parser


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
