from pathlib import Path
from types import SimpleNamespace

import pytest

from fx_scanner.demo_broker_risk_sizing import (
    conversion_rate_from_chain,
    floor_broker_volume_cents,
    monetary_loss_at_stop,
    risk_capped_volume_cents,
)
from fx_scanner.demo_fresh_ready_handoff import (
    DEMO_MARGIN_USAGE_CAP_ENV,
    DEMO_PORTFOLIO_RISK_CAP_ENV,
    load_demo_execution_policy,
)
from fx_scanner.execution.models import OrderSide


def test_monetary_stop_loss_uses_protocol_volume_cents():
    # 0.10 standard FX lot = 10,000 native units = 1,000,000 protocol cents.
    loss = monetary_loss_at_stop(
        entry_price=1.1000,
        stop_loss=1.0950,
        volume_cents=1_000_000,
        quote_to_deposit_rate=1.0,
    )
    assert loss == pytest.approx(50.0)


def test_risk_budget_can_reduce_conviction_lot_without_changing_geometry():
    volume = risk_capped_volume_cents(
        entry_price=1.1000,
        stop_loss=1.0950,
        quote_to_deposit_rate=1.0,
        risk_capital=25.0,
        conviction_volume_cents=1_000_000,
        minimum=100_000,
        step=100_000,
        maximum=10_000_000,
    )
    assert volume == 500_000  # 0.05 lot on a 100k-unit contract.
    assert monetary_loss_at_stop(
        entry_price=1.1000,
        stop_loss=1.0950,
        volume_cents=volume,
        quote_to_deposit_rate=1.0,
    ) == pytest.approx(25.0)


def test_broker_grid_always_floors_never_rounds_risk_up():
    assert floor_broker_volume_cents(
        599_999,
        minimum=100_000,
        step=100_000,
        maximum=10_000_000,
    ) == 500_000


def test_conversion_chain_uses_bid_for_long_and_ask_for_short():
    # JPY -> USD via USDJPY means reverse the USD/JPY quote.
    chain = (
        SimpleNamespace(symbolId=1, baseAssetId=840, quoteAssetId=392),
    )
    quotes = {1: (150.00, 150.10)}
    long_rate = conversion_rate_from_chain(
        chain=chain,
        first_asset_id=392,
        last_asset_id=840,
        side=OrderSide.BUY,
        quote_for_symbol_id=lambda sid: quotes[sid],
    )
    short_rate = conversion_rate_from_chain(
        chain=chain,
        first_asset_id=392,
        last_asset_id=840,
        side=OrderSide.SELL,
        quote_for_symbol_id=lambda sid: quotes[sid],
    )
    assert long_rate == pytest.approx(1.0 / 150.00)
    assert short_rate == pytest.approx(1.0 / 150.10)


def test_runtime_profile_has_bounded_portfolio_and_margin_caps(monkeypatch):
    monkeypatch.setenv(DEMO_PORTFOLIO_RISK_CAP_ENV, "6.0")
    monkeypatch.setenv(DEMO_MARGIN_USAGE_CAP_ENV, "25.0")
    policy = load_demo_execution_policy()
    assert policy.demo_safety["max_portfolio_risk_pct"] == 6.0
    assert policy.demo_safety["max_margin_free_usage_pct"] == 25.0


def test_runtime_profile_defaults_to_latest_demo_order_and_risk_caps():
    policy = load_demo_execution_policy()
    assert policy.demo_safety["max_order_lots"] == 0.50
    assert policy.demo_safety["max_risk_pct"] == 5.0


def test_runtime_profile_rejects_excessive_portfolio_cap(monkeypatch):
    monkeypatch.setenv(DEMO_PORTFOLIO_RISK_CAP_ENV, "12.1")
    with pytest.raises(RuntimeError, match="CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT"):
        load_demo_execution_policy()


def test_fast_handoff_installs_broker_risk_between_conviction_and_stacking():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")
    conviction = source.index("install_demo_conviction_sizing()")
    broker_risk = source.index("install_demo_broker_native_risk_sizing()")
    stacking = source.index("install_demo_conditional_stacking()")
    assert conviction < broker_risk < stacking
    assert "broker_native_risk=1 live_unlock=0" in source
