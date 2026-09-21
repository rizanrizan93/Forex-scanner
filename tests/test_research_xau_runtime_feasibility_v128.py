from types import SimpleNamespace

from fx_scanner.research_xau_runtime_feasibility_v128 import (
    EXECUTION_INFLUENCE,
    MARGIN_FREE_USAGE_PCT,
    PER_TRADE_RISK_PCT,
    POLICY_EFFECT,
    PORTFOLIO_RISK_PCT,
    PROMOTION_ELIGIBLE,
    _capital_floor_single_trade,
)


class Spec:
    contract_units_per_lot=100.0


def test_v128_contract_matches_current_runtime_caps():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert PER_TRADE_RISK_PCT==20.0
    assert PORTFOLIO_RISK_PCT==20.0
    assert MARGIN_FREE_USAGE_PCT==25.0


def test_capital_floor_takes_max_of_risk_and_margin():
    trade=SimpleNamespace(entry_price=4000.0,stop_loss=3900.0)
    row=_capital_floor_single_trade(
        trade,spec=Spec(),tiers=(),account_leverage=100.0
    )
    # 0.01 lot = 1 oz. SL risk=$100 -> $500 balance at 20% cap.
    # Margin=$40 -> $160 balance at 25% cap. Risk is binding.
    assert abs(row["stop_loss_usd"]-100.0)<1e-9
    assert abs(row["expected_margin_usd"]-40.0)<1e-9
    assert abs(row["single_trade_floor_balance_usd"]-500.0)<1e-9


def test_demo_1_30_margin_floor_is_higher():
    trade=SimpleNamespace(entry_price=4372.83,stop_loss=4352.83)
    row=_capital_floor_single_trade(
        trade,spec=Spec(),tiers=(),account_leverage=30.0
    )
    assert row["expected_margin_usd"]>145.0
    assert row["margin_floor_balance_usd"]>580.0
