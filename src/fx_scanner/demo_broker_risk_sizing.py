from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from math import isfinite
from time import monotonic, sleep
from typing import Any, Callable

from .execution.ctrader_session import normalize_symbol_name
from .execution.models import OrderIntent, OrderSide

MAX_DEMO_PORTFOLIO_RISK_PCT = 6.0
MAX_DEMO_MARGIN_FREE_USAGE_PCT = 25.0


@dataclass(frozen=True, slots=True)
class DemoBrokerRiskSizing:
    conviction_lots: float
    final_lots: float
    volume_cents: int
    quote_to_deposit_rate: float
    per_trade_risk_capital: float
    existing_portfolio_risk: float
    portfolio_remaining_risk: float
    estimated_stop_loss: float
    estimated_stop_loss_pct: float
    expected_margin: float
    margin_capital: float


def _finite_positive(value: Any, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"DEMO_BROKER_RISK_{name}_INVALID") from exc
    if not isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"DEMO_BROKER_RISK_{name}_INVALID")
    return parsed


def _decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"DEMO_BROKER_RISK_{name}_INVALID") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"DEMO_BROKER_RISK_{name}_INVALID")
    return parsed


def floor_broker_volume_cents(
    raw_volume_cents: float | Decimal,
    *,
    minimum: int,
    step: int,
    maximum: int | None = None,
) -> int:
    """Floor protocol volume (0.01 native units) to the broker's exact grid."""
    try:
        raw = Decimal(str(raw_volume_cents))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if not raw.is_finite() or raw <= 0:
        return 0
    minimum = int(minimum)
    step = int(step)
    if minimum <= 0 or step <= 0:
        raise ValueError("DEMO_BROKER_RISK_VOLUME_GRID_INVALID")
    capped = raw
    if maximum is not None and int(maximum) > 0:
        capped = min(capped, Decimal(int(maximum)))
    minimum_d = Decimal(minimum)
    step_d = Decimal(step)
    if capped < minimum_d:
        return 0
    units = ((capped - minimum_d) / step_d).to_integral_value(rounding=ROUND_FLOOR)
    return int(minimum_d + units * step_d)


def monetary_loss_at_stop(
    *,
    entry_price: float,
    stop_loss: float,
    volume_cents: int,
    quote_to_deposit_rate: float,
) -> float:
    """Estimate gross loss in deposit currency at SL using cTrader volume units."""
    entry = _decimal(entry_price, name="ENTRY")
    stop = _decimal(stop_loss, name="STOP")
    rate = _decimal(quote_to_deposit_rate, name="CONVERSION_RATE")
    volume = int(volume_cents)
    if volume <= 0:
        raise ValueError("DEMO_BROKER_RISK_VOLUME_INVALID")
    # Open API protocol volume is expressed in cents: 100 protocol units =
    # one native base-asset unit. P/L is price distance * native units, then
    # converted from the symbol quote asset into the account deposit asset.
    loss = abs(entry - stop) * (Decimal(volume) / Decimal(100)) * rate
    return float(loss)


def risk_capped_volume_cents(
    *,
    entry_price: float,
    stop_loss: float,
    quote_to_deposit_rate: float,
    risk_capital: float,
    conviction_volume_cents: int,
    minimum: int,
    step: int,
    maximum: int | None = None,
) -> int:
    """Return the largest broker-grid volume whose SL loss fits the cash budget."""
    budget = _decimal(risk_capital, name="RISK_CAPITAL")
    entry = _decimal(entry_price, name="ENTRY")
    stop = _decimal(stop_loss, name="STOP")
    rate = _decimal(quote_to_deposit_rate, name="CONVERSION_RATE")
    per_cent_loss = abs(entry - stop) * rate / Decimal(100)
    if per_cent_loss <= 0:
        raise ValueError("DEMO_BROKER_RISK_STOP_DISTANCE_INVALID")
    raw_by_risk = budget / per_cent_loss
    raw = min(Decimal(int(conviction_volume_cents)), raw_by_risk)
    return floor_broker_volume_cents(
        raw,
        minimum=minimum,
        step=step,
        maximum=maximum,
    )


def conversion_rate_from_chain(
    *,
    chain: tuple[Any, ...],
    first_asset_id: int,
    last_asset_id: int,
    side: OrderSide,
    quote_for_symbol_id: Callable[[int], tuple[float, float]],
) -> float:
    """Follow the broker-provided shortest conversion chain using live bid/ask."""
    first = int(first_asset_id)
    last = int(last_asset_id)
    if first <= 0 or last <= 0:
        raise ValueError("DEMO_BROKER_RISK_ASSET_ID_INVALID")
    if first == last:
        return 1.0
    if not chain:
        raise ValueError("DEMO_BROKER_RISK_CONVERSION_CHAIN_EMPTY")

    current_asset = first
    rate = 1.0
    for light in chain:
        sid = int(getattr(light, "symbolId", 0) or 0)
        base = int(getattr(light, "baseAssetId", 0) or 0)
        quote = int(getattr(light, "quoteAssetId", 0) or 0)
        if sid <= 0 or base <= 0 or quote <= 0:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_SYMBOL_INVALID")
        bid, ask = quote_for_symbol_id(sid)
        bid = _finite_positive(bid, name="CONVERSION_BID")
        ask = _finite_positive(ask, name="CONVERSION_ASK")
        if ask < bid:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_QUOTE_CROSSED")
        # cTrader's conversion tutorial specifies Bid for long-position P&L and
        # Ask for short-position P&L. Keep that convention for SL-loss sizing.
        close_price = bid if side == OrderSide.BUY else ask
        if base == current_asset:
            rate *= close_price
            current_asset = quote
        elif quote == current_asset:
            rate *= 1.0 / close_price
            current_asset = base
        else:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_CHAIN_DISCONTINUOUS")
        if not isfinite(rate) or rate <= 0.0:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_RATE_INVALID")
    if current_asset != last:
        raise ValueError("DEMO_BROKER_RISK_CONVERSION_CHAIN_INCOMPLETE")
    return rate


def _all_light_symbols(session) -> dict[int, Any]:
    cached = getattr(session, "_demo_risk_light_by_id", None)
    if isinstance(cached, dict) and cached:
        return cached
    req = session.msg["SymbolsListReq"]()
    req.ctidTraderAccountId = int(session.account_id)
    req.includeArchivedSymbols = False
    res = session._send_sync(req, client_msg_id="demo-risk-symbols")
    mapping = {
        int(light.symbolId): light
        for light in tuple(getattr(res, "symbol", ()))
        if int(getattr(light, "symbolId", 0) or 0) > 0
    }
    if not mapping:
        raise ValueError("DEMO_BROKER_RISK_LIGHT_SYMBOLS_EMPTY")
    session._demo_risk_light_by_id = mapping
    return mapping


def _ensure_conversion_symbols_loaded(session, chain: tuple[Any, ...]) -> None:
    missing: list[int] = []
    for light in chain:
        sid = int(getattr(light, "symbolId", 0) or 0)
        name = normalize_symbol_name(str(getattr(light, "symbolName", "") or ""))
        if sid <= 0 or not name:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_SYMBOL_INVALID")
        session.symbol_id_by_name[name] = sid
        session.symbol_name_by_id[sid] = name
        if sid not in session.symbol_full_by_id:
            missing.append(sid)
    if missing:
        req = session.msg["SymbolByIdReq"]()
        req.ctidTraderAccountId = int(session.account_id)
        req.symbolId.extend(missing)
        res = session._send_sync(req, client_msg_id="demo-risk-symbol-full")
        for symbol in tuple(getattr(res, "symbol", ())):
            session.symbol_full_by_id[int(symbol.symbolId)] = symbol
        if any(sid not in session.symbol_full_by_id for sid in missing):
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_SYMBOL_FULL_MISSING")

    subscribe = session.msg["SubscribeSpotsReq"]()
    subscribe.ctidTraderAccountId = int(session.account_id)
    subscribe.subscribeToSpotTimestamp = True
    subscribe.symbolId.extend([int(light.symbolId) for light in chain])
    session._send_sync(subscribe, client_msg_id="demo-risk-conversion-spots")


def _conversion_chain(session, first_asset_id: int, last_asset_id: int) -> tuple[Any, ...]:
    if int(first_asset_id) == int(last_asset_id):
        return ()
    cache = getattr(session, "_demo_risk_conversion_chain_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        session._demo_risk_conversion_chain_cache = cache
    key = (int(first_asset_id), int(last_asset_id))
    if key in cache:
        return tuple(cache[key])

    try:
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsForConversionReq
    except ModuleNotFoundError as exc:
        raise ValueError("DEMO_BROKER_RISK_CONVERSION_PROTO_UNAVAILABLE") from exc

    req = ProtoOASymbolsForConversionReq()
    req.ctidTraderAccountId = int(session.account_id)
    req.firstAssetId = int(first_asset_id)
    req.lastAssetId = int(last_asset_id)
    res = session._send_sync(req, client_msg_id="demo-risk-conversion-chain")
    chain = tuple(getattr(res, "symbol", ()))
    if not chain:
        raise ValueError("DEMO_BROKER_RISK_CONVERSION_CHAIN_EMPTY")
    _ensure_conversion_symbols_loaded(session, chain)
    cache[key] = chain
    return chain


def _fresh_quote_by_id(gateway, session, symbol_id: int) -> tuple[float, float]:
    symbol_id = int(symbol_id)
    name = str(session.symbol_name_by_id.get(symbol_id, ""))
    if not name:
        light = _all_light_symbols(session).get(symbol_id)
        if light is None:
            raise ValueError("DEMO_BROKER_RISK_CONVERSION_SYMBOL_UNKNOWN")
        _ensure_conversion_symbols_loaded(session, (light,))
        name = str(session.symbol_name_by_id.get(symbol_id, ""))
    deadline = monotonic() + max(1.0, float(getattr(gateway, "quote_wait_timeout_seconds", 5.0)))
    last_error: Exception | None = None
    while monotonic() <= deadline:
        try:
            quote = gateway.market_quote(name)
            return float(quote.bid), float(quote.ask)
        except Exception as exc:
            last_error = exc
            sleep(0.10)
    raise ValueError(
        f"DEMO_BROKER_RISK_CONVERSION_QUOTE_UNAVAILABLE:{type(last_error).__name__ if last_error else 'UNKNOWN'}"
    )


def _quote_to_deposit_rate(
    *,
    gateway,
    light_symbol: Any,
    deposit_asset_id: int,
    side: OrderSide,
) -> float:
    quote_asset_id = int(getattr(light_symbol, "quoteAssetId", 0) or 0)
    if quote_asset_id <= 0 or int(deposit_asset_id) <= 0:
        raise ValueError("DEMO_BROKER_RISK_ASSET_ID_INVALID")
    if quote_asset_id == int(deposit_asset_id):
        return 1.0
    session = gateway.session
    chain = _conversion_chain(session, quote_asset_id, int(deposit_asset_id))
    return conversion_rate_from_chain(
        chain=chain,
        first_asset_id=quote_asset_id,
        last_asset_id=int(deposit_asset_id),
        side=side,
        quote_for_symbol_id=lambda sid: _fresh_quote_by_id(gateway, session, sid),
    )


def _symbol_volume_grid(symbol_info: Any) -> tuple[int, int, int | None, int]:
    lot_size = int(getattr(symbol_info, "lotSize", 0) or 0)
    minimum = int(getattr(symbol_info, "minVolume", 0) or 0)
    step = int(getattr(symbol_info, "stepVolume", 0) or 0)
    maximum = int(getattr(symbol_info, "maxVolume", 0) or 0)
    if lot_size <= 0 or minimum <= 0 or step <= 0:
        raise ValueError("DEMO_BROKER_RISK_VOLUME_GRID_INVALID")
    return minimum, step, (maximum if maximum > 0 else None), lot_size


def _expected_margin_deposit(*, session, symbol_id: int, volume_cents: int, side: OrderSide) -> float:
    res = session.expected_margin(int(symbol_id), int(volume_cents))
    rows = tuple(getattr(res, "margin", ()))
    if not rows:
        raise ValueError("DEMO_BROKER_RISK_EXPECTED_MARGIN_EMPTY")
    raw = getattr(rows[0], "buyMargin" if side == OrderSide.BUY else "sellMargin", None)
    if raw is None:
        raise ValueError("DEMO_BROKER_RISK_EXPECTED_MARGIN_SIDE_MISSING")
    digits = int(getattr(res, "moneyDigits", 0) or 0)
    margin = float(raw) / float(10 ** digits)
    return _finite_positive(margin, name="EXPECTED_MARGIN")


def _margin_capped_volume(
    *,
    session,
    symbol_id: int,
    side: OrderSide,
    target_volume_cents: int,
    minimum: int,
    step: int,
    margin_capital: float,
) -> tuple[int, float]:
    target = int(target_volume_cents)
    cap = _finite_positive(margin_capital, name="MARGIN_CAPITAL")
    attempts = 0
    while target >= minimum and attempts < 12:
        margin = _expected_margin_deposit(
            session=session,
            symbol_id=symbol_id,
            volume_cents=target,
            side=side,
        )
        if margin <= cap + 1e-9:
            return target, margin
        proportional = Decimal(target) * _decimal(cap, name="MARGIN_CAPITAL") / _decimal(
            margin, name="EXPECTED_MARGIN"
        ) * Decimal("0.995")
        next_target = floor_broker_volume_cents(
            proportional,
            minimum=minimum,
            step=step,
        )
        if next_target >= target:
            next_target = floor_broker_volume_cents(
                Decimal(target - step),
                minimum=minimum,
                step=step,
            )
        target = next_target
        attempts += 1
    raise ValueError("DEMO_BROKER_RISK_MARGIN_CAP_BELOW_MIN_VOLUME")


def _remaining_open_position_risk(
    *,
    gateway,
    deposit_asset_id: int,
    light_by_id: dict[int, Any],
) -> float:
    session = gateway.session
    reconcile = session.reconcile()
    total = 0.0
    for position in tuple(getattr(reconcile, "position", ())):
        stop = float(getattr(position, "stopLoss", 0.0) or 0.0)
        if stop <= 0.0:
            raise ValueError("DEMO_BROKER_RISK_EXISTING_POSITION_UNPROTECTED")
        trade_data = getattr(position, "tradeData", None)
        sid = int(getattr(trade_data, "symbolId", 0) or 0)
        side_code = int(getattr(trade_data, "tradeSide", 0) or 0)
        volume_cents = int(getattr(trade_data, "volume", 0) or 0)
        if sid <= 0 or side_code not in {1, 2} or volume_cents <= 0:
            raise ValueError("DEMO_BROKER_RISK_EXISTING_POSITION_INVALID")
        light = light_by_id.get(sid)
        if light is None:
            raise ValueError("DEMO_BROKER_RISK_EXISTING_SYMBOL_UNKNOWN")
        _ensure_conversion_symbols_loaded(session, (light,))
        bid, ask = _fresh_quote_by_id(gateway, session, sid)
        side = OrderSide.BUY if side_code == 1 else OrderSide.SELL
        current = bid if side == OrderSide.BUY else ask
        distance = current - stop if side == OrderSide.BUY else stop - current
        if distance <= 0.0:
            # A stop already at/beyond current executable price protects capital;
            # treat remaining loss-to-SL as zero rather than negative risk.
            continue
        rate = _quote_to_deposit_rate(
            gateway=gateway,
            light_symbol=light,
            deposit_asset_id=deposit_asset_id,
            side=side,
        )
        total += monetary_loss_at_stop(
            entry_price=current,
            stop_loss=stop,
            volume_cents=volume_cents,
            quote_to_deposit_rate=rate,
        )
    if not isfinite(total) or total < 0.0:
        raise ValueError("DEMO_BROKER_RISK_PORTFOLIO_RISK_INVALID")
    return total


def select_demo_broker_native_sizing(
    *,
    gateway,
    intent: OrderIntent,
    max_portfolio_risk_pct: float = MAX_DEMO_PORTFOLIO_RISK_PCT,
    max_margin_free_usage_pct: float = MAX_DEMO_MARGIN_FREE_USAGE_PCT,
) -> DemoBrokerRiskSizing:
    """Apply SL-loss, aggregate open-risk and expected-margin caps to conviction lots."""
    portfolio_pct = _finite_positive(max_portfolio_risk_pct, name="PORTFOLIO_RISK_PCT")
    margin_pct = _finite_positive(max_margin_free_usage_pct, name="MARGIN_USAGE_PCT")
    if portfolio_pct > 25.0 or margin_pct > 80.0:
        raise ValueError("DEMO_BROKER_RISK_CAP_OUT_OF_RANGE")
    conviction_lots = _finite_positive(intent.volume, name="CONVICTION_LOTS")
    per_trade_pct = _finite_positive(intent.risk_pct, name="PER_TRADE_RISK_PCT")

    session = getattr(gateway, "session", None)
    if session is None or str(getattr(session, "environment", "")).lower() != "demo":
        raise ValueError("DEMO_BROKER_RISK_DEMO_SESSION_REQUIRED")
    session.ensure_connected()

    snapshot = gateway.account_snapshot()
    equity = _finite_positive(snapshot.equity, name="EQUITY")
    margin_free = _finite_positive(snapshot.margin_free, name="MARGIN_FREE")
    trader = session.trader()
    deposit_asset_id = int(getattr(trader, "depositAssetId", 0) or 0)
    if deposit_asset_id <= 0:
        raise ValueError("DEMO_BROKER_RISK_DEPOSIT_ASSET_MISSING")

    symbol_info = session.symbol_info(intent.symbol)
    symbol_id = int(getattr(symbol_info, "symbolId", 0) or 0)
    if symbol_id <= 0:
        raise ValueError("DEMO_BROKER_RISK_SYMBOL_ID_INVALID")
    light_by_id = _all_light_symbols(session)
    light = light_by_id.get(symbol_id)
    if light is None:
        raise ValueError("DEMO_BROKER_RISK_LIGHT_SYMBOL_MISSING")

    minimum, step, maximum, lot_size = _symbol_volume_grid(symbol_info)
    conviction_volume = floor_broker_volume_cents(
        _decimal(conviction_lots, name="CONVICTION_LOTS") * Decimal(lot_size),
        minimum=minimum,
        step=step,
        maximum=maximum,
    )
    if conviction_volume < minimum:
        raise ValueError("DEMO_BROKER_RISK_CONVICTION_BELOW_MIN_VOLUME")

    conversion_rate = _quote_to_deposit_rate(
        gateway=gateway,
        light_symbol=light,
        deposit_asset_id=deposit_asset_id,
        side=intent.side,
    )
    per_trade_risk_capital = equity * per_trade_pct / 100.0
    existing_portfolio_risk = _remaining_open_position_risk(
        gateway=gateway,
        deposit_asset_id=deposit_asset_id,
        light_by_id=light_by_id,
    )
    portfolio_capital = equity * portfolio_pct / 100.0
    portfolio_remaining = portfolio_capital - existing_portfolio_risk
    if portfolio_remaining <= 0.0:
        raise ValueError("DEMO_BROKER_RISK_PORTFOLIO_CAP_EXHAUSTED")
    monetary_budget = min(per_trade_risk_capital, portfolio_remaining)

    risk_volume = risk_capped_volume_cents(
        entry_price=float(intent.entry_price),
        stop_loss=float(intent.stop_loss),
        quote_to_deposit_rate=conversion_rate,
        risk_capital=monetary_budget,
        conviction_volume_cents=conviction_volume,
        minimum=minimum,
        step=step,
        maximum=maximum,
    )
    if risk_volume < minimum:
        raise ValueError("DEMO_BROKER_RISK_SL_CAP_BELOW_MIN_VOLUME")

    margin_capital = margin_free * margin_pct / 100.0
    final_volume, expected_margin = _margin_capped_volume(
        session=session,
        symbol_id=symbol_id,
        side=intent.side,
        target_volume_cents=risk_volume,
        minimum=minimum,
        step=step,
        margin_capital=margin_capital,
    )
    estimated_loss = monetary_loss_at_stop(
        entry_price=float(intent.entry_price),
        stop_loss=float(intent.stop_loss),
        volume_cents=final_volume,
        quote_to_deposit_rate=conversion_rate,
    )
    estimated_pct = estimated_loss / equity * 100.0
    final_lots = float(Decimal(final_volume) / Decimal(lot_size))
    if final_lots <= 0.0 or final_lots > conviction_lots + 1e-9:
        raise ValueError("DEMO_BROKER_RISK_FINAL_LOTS_INVALID")
    if estimated_loss > monetary_budget + 1e-6:
        raise ValueError("DEMO_BROKER_RISK_ESTIMATED_LOSS_EXCEEDS_BUDGET")
    if expected_margin > margin_capital + 1e-6:
        raise ValueError("DEMO_BROKER_RISK_EXPECTED_MARGIN_EXCEEDS_CAP")

    return DemoBrokerRiskSizing(
        conviction_lots=conviction_lots,
        final_lots=final_lots,
        volume_cents=final_volume,
        quote_to_deposit_rate=conversion_rate,
        per_trade_risk_capital=per_trade_risk_capital,
        existing_portfolio_risk=existing_portfolio_risk,
        portfolio_remaining_risk=portfolio_remaining,
        estimated_stop_loss=estimated_loss,
        estimated_stop_loss_pct=estimated_pct,
        expected_margin=expected_margin,
        margin_capital=margin_capital,
    )


def install_demo_broker_native_risk_sizing() -> None:
    """Install DEMO-only broker-native monetary sizing after conviction sizing."""
    from .execution.demo_autotrade import CTraderDemoAutoExecutor

    if getattr(CTraderDemoAutoExecutor, "_demo_broker_risk_sizing_installed", False):
        return
    original = CTraderDemoAutoExecutor._intent_diagnostic

    def _intent_diagnostic_with_broker_risk(self, row, *, now):
        intent, reason = original(self, row, now=now)
        if intent is None:
            return None, reason
        try:
            sizing = select_demo_broker_native_sizing(
                gateway=self.gateway,
                intent=intent,
                max_portfolio_risk_pct=float(
                    self.demo.get("max_portfolio_risk_pct", MAX_DEMO_PORTFOLIO_RISK_PCT)
                ),
                max_margin_free_usage_pct=float(
                    self.demo.get(
                        "max_margin_free_usage_pct",
                        MAX_DEMO_MARGIN_FREE_USAGE_PCT,
                    )
                ),
            )
        except Exception as exc:
            return None, f"BROKER_NATIVE_RISK_SIZING_INVALID:{type(exc).__name__}:{exc}"

        print(
            "CTRADER_DEMO_BROKER_NATIVE_SIZING "
            f"symbol={intent.symbol} conviction_lots={sizing.conviction_lots:.4f} "
            f"final_lots={sizing.final_lots:.4f} "
            f"sl_loss={sizing.estimated_stop_loss:.4f} "
            f"sl_risk_pct={sizing.estimated_stop_loss_pct:.4f} "
            f"portfolio_existing_risk={sizing.existing_portfolio_risk:.4f} "
            f"portfolio_remaining_risk={sizing.portfolio_remaining_risk:.4f} "
            f"expected_margin={sizing.expected_margin:.4f} "
            f"margin_cap={sizing.margin_capital:.4f} "
            f"quote_to_deposit={sizing.quote_to_deposit_rate:.8f} live_unlock=0"
        )
        return (
            replace(
                intent,
                volume=sizing.final_lots,
                risk_pct=sizing.estimated_stop_loss_pct,
                comment=f"{intent.comment}:BRISK",
            ),
            None,
        )

    CTraderDemoAutoExecutor._intent_diagnostic = _intent_diagnostic_with_broker_risk
    CTraderDemoAutoExecutor._demo_broker_risk_sizing_installed = True
