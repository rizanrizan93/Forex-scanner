from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType
from fx_scanner.execution.position_sizer import SymbolTradeSpec
from fx_scanner.execution.reconciliation import DualFeedRevalidator, RevalidationBlocked
from fx_scanner.execution.symbol_mapping import MT5SymbolResolver

UTC = timezone.utc
NOW = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)


class Research:
    def __init__(self, bid=1.0999, ask=1.1001, age=0.05):
        self.bid, self.ask, self.age = bid, ask, age

    def quote(self, symbol):
        return SimpleNamespace(
            bid=self.bid, ask=self.ask, timestamp=NOW - timedelta(seconds=self.age)
        )


class Execution:
    def __init__(
        self,
        bid=1.1000,
        ask=1.1002,
        age=0.03,
        currency="USC",
        contract_size=1000.0,
    ):
        self.bid, self.ask, self.age = bid, ask, age
        self.currency = currency
        self.contract_size = contract_size

    def quote(self, symbol):
        return SimpleNamespace(
            bid=self.bid, ask=self.ask, timestamp=NOW - timedelta(seconds=self.age)
        )

    def account_snapshot(self):
        return SimpleNamespace(
            account_id="HFM-1",
            equity=10_000.0,
            currency=self.currency,
            trade_allowed=True,
        )

    def symbol_trade_spec(self, symbol):
        return SymbolTradeSpec(
            tick_size=0.0001,
            tick_value_loss=1.0,
            volume_min=0.01,
            volume_max=1000.0,
            volume_step=0.01,
            contract_size=self.contract_size,
        )

    def symbol_available(self, symbol):
        return symbol in {"EURUSD", "EURUSDc"}

    def symbol_contract_size(self, symbol):
        return 100_000.0 if symbol == "EURUSD" else self.contract_size

    def ensure_symbol(self, symbol):
        return None


def intent():
    return OrderIntent(
        signal_id="DF-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=NOW,
        volume=0.01,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


def config(**overrides):
    base = {
        "research_quote_max_age_seconds": 2,
        "execution_quote_max_age_seconds": 1,
        "max_mid_divergence_pips": 2,
        "max_execution_spread_pips": 4,
        "spread_ratio_floor_pips": 0.10,
        "max_spread_ratio_vs_research": 12,
        "max_entry_drift_pips": 2,
        "max_entry_drift_r": 0.15,
        "min_rr": 1.5,
        "max_internal_revalidation_ms": 500,
        "expected_account_currency": "USC",
        "expected_fx_contract_size": 1000,
        "allow_pending_orders": False,
    }
    base.update(overrides)
    return base


def build(execution=None, research=None, **cfg):
    execution = execution or Execution()
    resolver = MT5SymbolResolver(
        execution,
        suffix_candidates=("", "c"),
        expected_contract_size=1000,
    )
    return DualFeedRevalidator(
        research_quotes=research or Research(),
        execution_gateway=execution,
        symbol_resolver=resolver,
        pip_sizes={"EURUSD": 0.0001},
        config=config(**cfg),
        wall_clock=lambda: NOW,
    )


def test_cent_symbol_resolution_filters_standard_contract():
    execution = Execution()
    resolver = MT5SymbolResolver(execution, suffix_candidates=("", "c"), expected_contract_size=1000)
    resolved = resolver.resolve("EURUSD")
    assert resolved.broker_symbol == "EURUSDc"
    assert resolved.contract_size == 1000


def test_revalidation_passes_and_resizes_from_hfm_tick_economics():
    result = build().revalidate(intent())
    assert result.prepared_intent.symbol == "EURUSD"
    assert result.prepared_intent.broker_symbol == "EURUSDc"
    assert result.prepared_intent.entry_price == pytest.approx(1.1002)
    assert result.prepared_intent.volume == pytest.approx(0.48)
    assert result.metrics.mid_divergence_pips == pytest.approx(1.0)
    assert result.metrics.rr > 1.5


@pytest.mark.parametrize(
    "revalidator,code",
    [
        (lambda: build(research=Research(age=3)), "RESEARCH_QUOTE_STALE"),
        (lambda: build(execution=Execution(age=2)), "EXECUTION_QUOTE_STALE"),
        (lambda: build(execution=Execution(bid=1.1005, ask=1.1007)), "BROKER_FEED_DIVERGENCE_BLOCK"),
        (lambda: build(execution=Execution(bid=1.1000, ask=1.1006), max_mid_divergence_pips=10), "SPREAD_BLOCK"),
        (lambda: build(execution=Execution(currency="USD")), "ACCOUNT_CURRENCY_MISMATCH"),
        (lambda: build(execution=Execution(contract_size=100_000)), "MT5_CENT_SYMBOL_NOT_FOUND"),
    ],
)
def test_revalidation_fail_closed(revalidator, code):
    with pytest.raises(Exception, match=code):
        revalidator().revalidate(intent())


def test_chase_block_when_hfm_entry_moved_too_far_even_if_divergence_limit_relaxed():
    rv = build(
        execution=Execution(bid=1.1002, ask=1.1004),
        max_mid_divergence_pips=10,
    )
    with pytest.raises(RevalidationBlocked, match="CHASE_BLOCK"):
        rv.revalidate(intent())


def test_rr_block_after_execution_price_degrades():
    rv = build(
        execution=Execution(bid=1.1038, ask=1.1040),
        max_mid_divergence_pips=100,
        max_entry_drift_pips=100,
        max_entry_drift_r=10,
        min_rr=1.5,
    )
    with pytest.raises(RevalidationBlocked, match="RR_BLOCK"):
        rv.revalidate(intent())
