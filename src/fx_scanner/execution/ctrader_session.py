from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from ..exceptions import CollectorUnavailable, MissingOptionalDependency
from ..models import Bar

UTC = timezone.utc


def normalize_symbol_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


@dataclass(frozen=True, slots=True)
class CTraderQuote:
    symbol_id: int
    bid: float
    ask: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class CTraderGrantedAccount:
    ctid_trader_account_id: int
    trader_login: int
    is_live: bool
    broker_title_short: str
    permission_scope: int


class CTraderOpenApiSession:
    """Synchronous facade over Spotware's asynchronous OpenApiPy client."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
        account_id: int | None,
        refresh_token: str | None = None,
        token_update_callback: Callable[[str, str], None] | None = None,
        environment: str = "demo",
        request_timeout_seconds: float = 10.0,
    ):
        if not all([client_id, client_secret, access_token]):
            raise ValueError("cTrader client_id/client_secret/access_token are required")
        try:
            from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
            from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent
            from ctrader_open_api.messages.OpenApiMessages_pb2 import (
                ProtoOAApplicationAuthReq,
                ProtoOAAccountAuthReq,
                ProtoOAExpectedMarginReq,
                ProtoOAGetPositionUnrealizedPnLReq,
                ProtoOAGetAccountListByAccessTokenReq,
                ProtoOAGetTrendbarsReq,
                ProtoOANewOrderReq,
                ProtoOAReconcileReq,
                ProtoOARefreshTokenReq,
                ProtoOASpotEvent,
                ProtoOASubscribeSpotsReq,
                ProtoOASymbolByIdReq,
                ProtoOASymbolsListReq,
                ProtoOATraderReq,
            )
            from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
            from twisted.internet import reactor
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency(
                "ctrader-open-api is unavailable; install requirements-ctrader.txt on the VPS"
            ) from exc

        self.Protobuf = Protobuf
        self.reactor = reactor
        self.msg = {
            "HeartbeatEvent": ProtoHeartbeatEvent,
            "ApplicationAuthReq": ProtoOAApplicationAuthReq,
            "AccountAuthReq": ProtoOAAccountAuthReq,
            "ExpectedMarginReq": ProtoOAExpectedMarginReq,
            "GetPositionUnrealizedPnLReq": ProtoOAGetPositionUnrealizedPnLReq,
            "GetAccountListByAccessTokenReq": ProtoOAGetAccountListByAccessTokenReq,
            "GetTrendbarsReq": ProtoOAGetTrendbarsReq,
            "TrendbarPeriod": ProtoOATrendbarPeriod,
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
        self.account_id = None if account_id is None else int(account_id)
        self.environment = environment.lower()
        if self.environment not in {"demo", "live"}:
            raise ValueError("environment must be demo or live")
        self.request_timeout_seconds = float(request_timeout_seconds)
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

        host = EndPoints.PROTOBUF_LIVE_HOST if self.environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self._connected = Event()
        self._application_authenticated = Event()
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
        self._application_authenticated.clear()
        self._authenticated.clear()

    @staticmethod
    def _event_ts(raw: int | None) -> datetime:
        if not raw:
            raise CollectorUnavailable("cTrader spot event timestamp unavailable")
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
            event_ts = self._event_ts(getattr(event, "timestamp", None))
            with self._quotes_lock:
                state = self._quotes_by_id.setdefault(sid, {})
                bid_present = False
                ask_present = False
                try:
                    bid_present = bool(event.HasField("bid"))
                except Exception:
                    bid_present = bool(getattr(event, "bid", 0))
                try:
                    ask_present = bool(event.HasField("ask"))
                except Exception:
                    ask_present = bool(getattr(event, "ask", 0))
                if bid_present:
                    state["bid"] = float(event.bid) / 100000.0
                    state["bid_timestamp"] = event_ts
                if ask_present:
                    state["ask"] = float(event.ask) / 100000.0
                    state["ask_timestamp"] = event_ts
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

    def connect_application(self) -> None:
        if self._connected.is_set() and self._application_authenticated.is_set():
            return
        if not self._connected.is_set():
            self.client.startService()
            self._ensure_reactor()
            if not self._connected.wait(timeout=self.request_timeout_seconds):
                raise CollectorUnavailable("cTrader connection timeout")
        if self._application_authenticated.is_set():
            return

        app = self.msg["ApplicationAuthReq"]()
        app.clientId = self.client_id
        app.clientSecret = self.client_secret
        self._send_sync(app, client_msg_id=f"app-{uuid4().hex}")
        self._application_authenticated.set()

    def granted_accounts(self) -> tuple[CTraderGrantedAccount, ...]:
        """Return only accounts explicitly granted to the current access token."""
        self.connect_application()
        req = self.msg["GetAccountListByAccessTokenReq"]()
        req.accessToken = self.access_token
        try:
            res = self._send_sync(req, client_msg_id=f"accounts-{uuid4().hex}")
        except Exception:
            if not self.refresh_token:
                raise
            self._refresh_tokens()
            req.accessToken = self.access_token
            res = self._send_sync(req, client_msg_id=f"accounts-refresh-{uuid4().hex}")

        permission_scope = int(getattr(res, "permissionScope", 0) or 0)
        output: list[CTraderGrantedAccount] = []
        for item in tuple(getattr(res, "ctidTraderAccount", ())):
            output.append(
                CTraderGrantedAccount(
                    ctid_trader_account_id=int(getattr(item, "ctidTraderAccountId", 0) or 0),
                    trader_login=int(getattr(item, "traderLogin", 0) or 0),
                    is_live=bool(getattr(item, "isLive", False)),
                    broker_title_short=str(getattr(item, "brokerTitleShort", "") or ""),
                    permission_scope=permission_scope,
                )
            )
        return tuple(output)

    def resolve_granted_account(
        self,
        *,
        trader_login: int,
        require_demo: bool = True,
        pinned_account_id: int | None = None,
    ) -> CTraderGrantedAccount:
        """Resolve one granted account by visible trader login and fail closed on ambiguity/live mismatch."""
        trader_login = int(trader_login)
        if trader_login <= 0:
            raise CollectorUnavailable("cTrader trader login must be positive")
        accounts = self.granted_accounts()
        matches = [account for account in accounts if account.trader_login == trader_login]

        if len(matches) == 1:
            account = matches[0]
        elif (
            len(matches) == 0
            and len(accounts) == 1
            and accounts[0].trader_login == 0
        ):
            # cTrader documents traderLogin as optional. Protobuf exposes an
            # omitted optional integer as 0, so when the access token grants
            # exactly one account we may bind that sole grant. This remains
            # fail-closed for multiple grants or an explicit non-matching login.
            account = accounts[0]
        else:
            raise CollectorUnavailable(
                f"cTrader granted-account match must be unique for trader login {trader_login}; "
                f"matches={len(matches)} grants={len(accounts)}"
            )
        if account.ctid_trader_account_id <= 0:
            raise CollectorUnavailable("cTrader resolved account id is invalid")
        if require_demo and account.is_live:
            raise CollectorUnavailable("cTrader demo-only guard rejected a live account")
        if self.environment == "demo" and account.is_live:
            raise CollectorUnavailable("cTrader DEMO host cannot bind a live account")
        if self.environment == "live" and not account.is_live:
            raise CollectorUnavailable("cTrader LIVE host cannot bind a demo account")
        if pinned_account_id is not None and int(pinned_account_id) != account.ctid_trader_account_id:
            raise CollectorUnavailable("cTrader pinned account id does not match granted trader login")
        self.account_id = account.ctid_trader_account_id
        return account

    def connect(self) -> None:
        if self.health():
            return
        if self.account_id is None:
            raise CollectorUnavailable("cTrader account id is unresolved")
        self.connect_application()

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
        self._application_authenticated.clear()
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
        required = {"bid", "ask", "bid_timestamp", "ask_timestamp"}
        if not required.issubset(state):
            raise CollectorUnavailable(f"cTrader quote incomplete for {symbol}")
        if state["ask"] < state["bid"]:
            raise CollectorUnavailable(f"cTrader crossed quote for {symbol}")
        # Freshness of a two-sided quote is bounded by its older side.
        quote_ts = min(state["bid_timestamp"], state["ask_timestamp"])
        return CTraderQuote(sid, float(state["bid"]), float(state["ask"]), quote_ts)

    def heartbeat(self) -> None:
        """Send a client heartbeat without exposing any trading operation."""
        self.ensure_connected()
        message = self.msg["HeartbeatEvent"]()

        def dispatch():
            try:
                deferred = self.client.send(message)
                try:
                    deferred.addErrback(lambda _failure: None)
                except Exception:
                    pass
            except Exception:
                pass

        self.reactor.callFromThread(dispatch)

    def historical_bars(
        self,
        symbol: str,
        timeframe: str,
        *,
        from_time: datetime,
        to_time: datetime,
        count: int,
        spread_proxy: float = 0.0,
    ) -> tuple[Bar, ...]:
        """Fetch historical cTrader trendbars normalized to scanner Bars."""
        self.ensure_connected()
        timeframe = str(timeframe).upper()
        if timeframe not in {"M1", "M5", "M15", "H1", "H4", "D1"}:
            raise CollectorUnavailable(f"unsupported cTrader timeframe: {timeframe}")
        if count <= 0:
            raise CollectorUnavailable("cTrader trendbar count must be positive")
        if from_time.tzinfo is None or to_time.tzinfo is None:
            raise CollectorUnavailable("cTrader trendbar timestamps must be timezone-aware")
        if from_time >= to_time:
            raise CollectorUnavailable("cTrader trendbar time range is invalid")
        if spread_proxy < 0:
            raise CollectorUnavailable("cTrader spread proxy cannot be negative")

        req = self.msg["GetTrendbarsReq"]()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = self.symbol_id(symbol)
        req.period = self.msg["TrendbarPeriod"].Value(timeframe)
        req.fromTimestamp = int(from_time.astimezone(UTC).timestamp() * 1000)
        req.toTimestamp = int(to_time.astimezone(UTC).timestamp() * 1000)
        req.count = int(count)
        res = self._send_sync(req, client_msg_id=f"trendbars-{uuid4().hex}")

        info = self.symbol_info(symbol)
        digits = int(getattr(info, "digits", 5))
        output: list[Bar] = []
        for item in tuple(getattr(res, "trendbar", ())):
            low_rel = int(getattr(item, "low", 0))
            low = round(low_rel / 100000.0, digits)
            open_ = round((low_rel + int(getattr(item, "deltaOpen", 0))) / 100000.0, digits)
            high = round((low_rel + int(getattr(item, "deltaHigh", 0))) / 100000.0, digits)
            close = round((low_rel + int(getattr(item, "deltaClose", 0))) / 100000.0, digits)
            minute_ts = int(getattr(item, "utcTimestampInMinutes", 0))
            if minute_ts <= 0:
                raise CollectorUnavailable("cTrader trendbar timestamp unavailable")
            timestamp = datetime.fromtimestamp(minute_ts * 60, tz=UTC)
            volume = int(getattr(item, "volume", 0) or 0)
            if volume <= 0:
                volume = 1
            output.append(
                Bar(
                    symbol, timeframe, timestamp, open_, high, low, close,
                    volume, float(spread_proxy), float(spread_proxy),
                )
            )
        output.sort(key=lambda bar: bar.timestamp)
        if not output:
            raise CollectorUnavailable(f"cTrader returned no {timeframe} bars for {symbol}")
        return tuple(output)

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
