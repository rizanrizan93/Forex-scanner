from __future__ import annotations

from decimal import Decimal

from .config import load_project_config
from .demo_broker_risk_sizing import (
    _all_light_symbols,
    _conversion_chain,
    _expected_margin_deposit,
    _quote_to_deposit_rate,
    _symbol_volume_grid,
    floor_broker_volume_cents,
    monetary_loss_at_stop,
)
from .execution.factory import build_broker_gateway
from .execution.models import OrderSide
from .execution.policy import load_execution_policy

PROBE_SYMBOL = "EURJPY"
PROBE_LOTS = Decimal("0.01")
PROBE_STOP_DISTANCE_PCT = Decimal("0.50")


def run() -> int:
    """Exercise broker-native risk evidence against cTrader without placing an order."""
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_BROKER_RISK_PROBE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_BROKER_RISK_PROBE_REQUIRE_DEMO")

    symbols = [pair.symbol for pair in cfg.pairs]
    if PROBE_SYMBOL not in symbols:
        raise SystemExit(f"CTRADER_BROKER_RISK_PROBE_SYMBOL_MISSING:{PROBE_SYMBOL}")

    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    try:
        session.ensure_connected()
        snapshot = gateway.account_snapshot()
        if snapshot.equity <= 0 or snapshot.margin_free <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_ACCOUNT_SNAPSHOT_INVALID")

        trader = session.trader()
        deposit_asset_id = int(getattr(trader, "depositAssetId", 0) or 0)
        if deposit_asset_id <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_DEPOSIT_ASSET_MISSING")

        symbol_info = session.symbol_info(PROBE_SYMBOL)
        symbol_id = int(getattr(symbol_info, "symbolId", 0) or 0)
        if symbol_id <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_SYMBOL_ID_INVALID")

        light_by_id = _all_light_symbols(session)
        light = light_by_id.get(symbol_id)
        if light is None:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_LIGHT_SYMBOL_MISSING")
        quote_asset_id = int(getattr(light, "quoteAssetId", 0) or 0)
        if quote_asset_id <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_QUOTE_ASSET_MISSING")
        if quote_asset_id == deposit_asset_id:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_REQUIRES_CROSS_CURRENCY_SYMBOL")

        # This request is the critical runtime contract: cTrader returns the
        # shortest quote-asset -> deposit-asset conversion chain. No trade call
        # is made anywhere in this probe.
        chain = _conversion_chain(session, quote_asset_id, deposit_asset_id)
        conversion_rate = _quote_to_deposit_rate(
            gateway=gateway,
            light_symbol=light,
            deposit_asset_id=deposit_asset_id,
            side=OrderSide.BUY,
        )

        minimum, step, maximum, lot_size = _symbol_volume_grid(symbol_info)
        target_volume = floor_broker_volume_cents(
            PROBE_LOTS * Decimal(lot_size),
            minimum=minimum,
            step=step,
            maximum=maximum,
        )
        if target_volume < minimum:
            target_volume = minimum

        quote = gateway.market_quote(PROBE_SYMBOL)
        entry = float(quote.ask)
        if entry <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_QUOTE_INVALID")
        stop = float(Decimal(str(entry)) * (Decimal("1") - PROBE_STOP_DISTANCE_PCT / Decimal("100")))
        synthetic_loss = monetary_loss_at_stop(
            entry_price=entry,
            stop_loss=stop,
            volume_cents=target_volume,
            quote_to_deposit_rate=conversion_rate,
        )
        expected_margin = _expected_margin_deposit(
            session=session,
            symbol_id=symbol_id,
            volume_cents=target_volume,
            side=OrderSide.BUY,
        )
        final_lots = Decimal(target_volume) / Decimal(lot_size)
        if synthetic_loss <= 0 or expected_margin <= 0 or conversion_rate <= 0:
            raise SystemExit("CTRADER_BROKER_RISK_PROBE_RESULT_INVALID")

        print(
            "CTRADER_DEMO_BROKER_RISK_PROBE_OK "
            f"symbol={PROBE_SYMBOL} lots={final_lots} volume_cents={target_volume} "
            f"conversion_hops={len(chain)} quote_to_deposit={conversion_rate:.10f} "
            f"synthetic_stop_pct={PROBE_STOP_DISTANCE_PCT} synthetic_sl_loss={synthetic_loss:.6f} "
            f"expected_margin={expected_margin:.6f} equity={snapshot.equity:.2f} "
            f"margin_free={snapshot.margin_free:.2f} no_order=1 live_unlock=0"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
