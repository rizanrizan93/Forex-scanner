from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from ..exceptions import CollectorUnavailable, MissingOptionalDependency

UTC = timezone.utc


def normalize_symbol_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


@dataclass(frozen=True, slots=True)
class CTraderQuote:
    symbol_id: int
    bid: float
    ask: float
    timestamp: datetime


class CTraderOpenApiSession:
    """Synchronous facade over Spotware's asynchronous OpenApiPy client."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
        account_id: int,
        refresh_token: str | None = None,
        token_update_callback: Callable[[str, str], None] | None = None,
        environment: str = "demo",
        request_timeout_seconds: float = 10.0,
    ):
        if not all([client_id, client_secret, access_token, account_id]):
            raise ValueError("cTrader client_id/client_secret/access_token/account_id are required")
        try:
            from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
            from ctrader_open_api.messages.OpenApiMessages_pb2 import (
                ProtoOAApplicationAuthReq,
                ProtoOAAccountAuthReq,
                ProtoOAExpectedMarginReq,
                ProtoOAGetPositionUnrealizedPnLReq,
                ProtoOANewOrderReq,
                ProtoOAReconcileReq,
                ProtoOARefreshTokenReq,
                ProtoOASpotEvent,
                ProtoOASubscribeSpotsReq,
                ProtoOASymbolByIdReq,
                ProtoOASymbolsListReq,
                ProtoOATraderReq,
            )
            from twisted.internet import reactor
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency(
                "ctrader-open-api is unavailable; install requirements-ctrader.txt on the VPS"
            ) from exc

        self.Protobuf = Protobuf
        self.reactor = reactor
        self.msg = {
            "ApplicationAuthReq": ProtoOAApplicationAuthReq,
            "AccountAuthReq": ProtoOAAccountAuthReq,
            "ExpectedMarginReq": ProtoOAExpectedMarginReq,
            "GetPositionUnrealizedPnLReq": ProtoOAGetPositionUnrealizedPnLReq,
            "NewOrderReq": ProtoOANewOrderReq,
            "ReconcileReq": ProtoOAReconcileReq,
            "RefreshTokenReq": ProtoOARefreshTokenReq,
            "SpotEvent": ProtoOASpotEvent,
            "SubscribeSpotsReq": ProtoOASubscribeSpotsReq,
            "SymbolByIdReq": ProtoOASymbolByIdReq,
            "SymbolsListReq": ProtoOASymbolsListReq,
            "TraderReq": ProtoOATraderReq,
        }
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_update_callback = token_update_callback
        self.account_id = int(account_id)
        self.environment = environment.lower()
        if self.environment not in {"demo", "live"}:
            raise ValueError("environment must be demo or live")
        self.request_timeout_seconds = float(request_timeout_seconds)
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

        host = EndPoints.PROTOBUF_LIVE_HOST if self.environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self._connected = Event()
        self._authenticated = Event()
        self._reactor_started = Event()
        self._quotes_lock = Lock()
        self._quotes_by_id: dict[int, dict[str, Any]] = {}
        self.symbol_id_by_name: dict[str, int] = {}
        self.symbol_name_by_id: dict[int, str] = {}
        self.symbol_full_by_id: dict[int, Any] = {}

        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)

    def _on_connected(self, client) -> None:
        self._connected.set()

    def _on_disconnected(self, client, reason) -> None:
        self._connected.clear()
        self._authenticated.clear()

    @staticmethod
    def _event_ts(raw: int | None) -> datetime:
        if not raw:
            return datetime.now(tz=UTC)
        value = float(raw)
        seconds = value / 1000.0 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)

    def _on_message(self, client, container) -> None:
        try:
            spot_type = self.msg["SpotEvent"]().payloadType
            if getattr(container, "payloadType", None) != spot_type:
                return
            event = self.Protobuf.extract(container)
            sid = int(event.symbolId)
            with self._quotes_lock:
                state = self._quotes_by_id.setdefault(sid, {})
                try:
                    if event.HasField("bid"):
                        state["bid"] = float(event.bid) / 100000.0
                except Exception:
                    if getattr(event, "bid", 0):
                        state["bid"] = float(event.bid) / 100000.0
                try:
                    if event.HasField("ask"):
                        state["ask"] = float(event.ask) / 100000.0
                except Exception:
                    if getattr(event, "ask", 0):
                        state["ask"] = float(event.ask) / 100000.0
                state["timestamp"] = self._event_ts(getattr(event, "timestamp", None))
        except Exception:
            return

    def _run_reactor(self) -> None:
        self._reactor_started.set()
        self.reactor.run(installSignalHandlers=False)

    def _ensure_reactor(self) -> None:
        if getattr(self.reactor, "running", False):
            self._reactor_started.set()
            return
        Thread(target=self._run_reactor, name="ctrader-reactor", daemon=True).start()
        if not self._reactor_started.wait(timeout=2.0):
            raise CollectorUnavailable("cTrader Twisted reactor did not start")

    def _send_sync(self, message, *, client_msg_id: str | None = None, timeout: float | None = None):
        timeout = self.request_timeout_seconds if timeout is None else float(timeout)
        done = Event()
        box: dict[str, Any] = {}

        def success(result):
            box["result"] = result
            done.set()
            return result

        def failure(err):
            box["error"] = err
            done.set()
            return err

        def dispatch():
            try:
                deferred = self.client.send(message, clientMsgId=client_msg_id)
                deferred.addCallbacks(success, failure)
            except Exception as exc:
                box["error"] = exc
                done.set()

        self.reactor.callFromThread(dispatch)
        if not done.wait(timeout=timeout):
            raise CollectorUnavailable(f"cTrader request timeout after {timeout:.1f}s")
        if "error" in box:
            raise CollectorUnavailable(f"cTrader request failed: {box['error']}")
        return box["result"]

    def _refresh_tokens(self) -> None:
        if not self.refresh_token:
            raise CollectorUnavailable("cTrader refresh token unavailable")
        req = self.msg["RefreshTokenReq"]()
        req.refreshToken = self.refresh_token
        res = self._send_sync(req, client_msg_id=f"refresh-{uuid4().hex}")
        access = str(getattr(res, "accessToken", "") or "")
        refresh = str(getattr(res, "refreshToken", "") or "")
        if not access or not refresh:
            raise CollectorUnavailable("cTrader token refresh returned incomplete credentials")
        self.access_token = access
        self.refresh_token = refresh
        if self.token_update_callback is not None:
            try:
                self.token_update_callback(access, refresh)
            except Exception as exc:
                raise CollectorUnavailable("cTrader token refresh persistence failed") from exc

    def connect(self) -> None:
        if self.health():
            return
        self.client.startService()
        self._ensure_reactor()
        if not self._connected.wait(timeout=self.request_timeout_seconds):
            raise CollectorUnavailable("cTrader connection timeout")

        app = self.msg["ApplicationAuthReq"]()
        app.clientId = self.client_id
        app.clientSecret = self.client_secret
        self._send_sync(app, client_msg_id=f"app-{uuid4().hex}")

        account = self.msg["AccountAuthReq"]()
        account.ctidTraderAccountId = self.account_id
        account.accessToken = self.access_token
        try:
            self._send_sync(account, client_msg_id=f"acct-{uuid4().hex}")
        except Exception:
            if not self.refresh_token:
                raise
            self._refresh_tokens()
            account.accessToken = self.access_token
            self._send_sync(account, client_msg_id=f"acct-refresh-{uuid4().hex}")
        self._authenticated.set()

    def ensure_connected(self) -> None:
        if not self.health():
            self.connect()

    def close(self) -> None:
        try:
            self.reactor.callFromThread(self.client.stopService)
        except Exception:
            pass
        self._connected.clear()
        self._authenticated.clear()

    def health(self) -> bool:
        return self._connected.is_set() and self._authenticated.is_set()

    def load_symbols(self, desired_symbols: list[str]) -> None:
        self.ensure_connected()
        req = self.msg["SymbolsListReq"]()
        req.ctidTraderAccountId = self.account_id
        req.includeArchivedSymbols = False
        res = self._send_sync(req, client_msg_id=f"symbols-{uuid4().hex}")
        wanted = {normalize_symbol_name(x) for x in desired_symbols}
        ids: list[int] = []
        for light in res.symbol:
            normalized = normalize_symbol_name(getattr(light, "symbolName", ""))
            if normalized in wanted:
                sid = int(light.symbolId)
                self.symbol_id_by_name[normalized] = sid
                self.symbol_name_by_id[sid] = normalized
                ids.append(sid)
        missing = sorted(wanted - set(self.symbol_id_by_name))
        if missing:
            raise CollectorUnavailable(f"cTrader symbols unavailable: {','.join(missing)}")
        full_req = self.msg["SymbolByIdReq"]()
        full_req.ctidTraderAccountId = self.account_id
        full_req.symbolId.extend(ids)
        full_res = self._send_sync(full_req, client_msg_id=f"symbol-full-{uuid4().hex}")
        self.symbol_full_by_id = {int(s.symbolId): s for s in full_res.symbol}

    def subscribe_spots(self, symbols: list[str]) -> None:
        if not self.symbol_id_by_name:
            self.load_symbols(symbols)
        req = self.msg["SubscribeSpotsReq"]()
        req.ctidTraderAccountId = self.account_id
        req.subscribeToSpotTimestamp = True
        for symbol in symbols:
            req.symbolId.append(self.symbol_id(symbol))
        self._send_sync(req, client_msg_id=f"spots-{uuid4().hex}")

    def symbol_id(self, symbol: str) -> int:
        key = normalize_symbol_name(symbol)
        try:
            return self.symbol_id_by_name[key]
        except KeyError as exc:
            raise CollectorUnavailable(f"cTrader symbol not loaded: {symbol}") from exc

    def symbol_info(self, symbol: str):
        sid = self.symbol_id(symbol)
        try:
            return self.symbol_full_by_id[sid]
        except KeyError as exc:
            raise CollectorUnavailable(f"cTrader full symbol not loaded: {symbol}") from exc

    def quote(self, symbol: str) -> CTraderQuote:
        sid = self.symbol_id(symbol)
        with self._quotes_lock:
            state = dict(self._quotes_by_id.get(sid, {}))
        if "bid" not in state or "ask" not in state or "timestamp" not in state:
            raise CollectorUnavailable(f"cTrader quote incomplete for {symbol}")
        if state["ask"] < state["bid"]:
            raise CollectorUnavailable(f"cTrader crossed quote for {symbol}")
        return CTraderQuote(sid, float(state["bid"]), float(state["ask"]), state["timestamp"])

    def trader(self):
        req = self.msg["TraderReq"]()
        req.ctidTraderAccountId = self.account_id
        return self._send_sync(req, client_msg_id=f"trader-{uuid4().hex}").trader

    def unrealized_pnl(self):
        req = self.msg["GetPositionUnrealizedPnLReq"]()
        req.ctidTraderAccountId = self.account_id
        return self._send_sync(req, client_msg_id=f"pnl-{uuid4().hex}")

    def reconcile(self):
        req = self.msg["ReconcileReq"]()
        req.ctidTraderAccountId = self.account_id
        req.returnProtectionOrders = False
        return self._send_sync(req, client_msg_id=f"reconcile-{uuid4().hex}")

    def expected_margin(self, symbol_id: int, volume_cents: int):
        req = self.msg["ExpectedMarginReq"]()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = int(symbol_id)
        req.volume.append(int(volume_cents))
        return self._send_sync(req, client_msg_id=f"margin-{uuid4().hex}")

    def send_new_order(self, request, *, client_msg_id: str):
        return self._send_sync(request, client_msg_id=client_msg_id)

    def new_order_message(self):
        return self.msg["NewOrderReq"]()
