from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.demo_donchian_adaptive_tournament import TournamentTrade
from fx_scanner.research_xau_100usd_regime_cashpath_v88 import (
    ACCOUNT_LEVERAGE,
    COST_SCENARIO_ID,
    EXECUTION_INFLUENCE,
    FIXED_LOT,
    PLANNED_STOP_MARGIN_FLOOR_PCT,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    STARTING_BALANCE_USD,
    cash_path_with_checkpoints,
)
from fx_scanner.research_xau_margin_leverage_v21 import LeverageTier
from fx_scanner.research_xau_multihorizon_100usd_v20 import BrokerLotSpec

ROOT = Path(__file__).resolve().parents[1]


def test_v88_cash_contract_is_frozen_and_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert STARTING_BALANCE_USD == 100.0
    assert ACCOUNT_LEVERAGE == 100.0
    assert FIXED_LOT == 0.01
    assert PLANNED_STOP_MARGIN_FLOOR_PCT == 150.0
    assert COST_SCENARIO_ID == "V24_STRESS_4675"


def test_v88_cash_path_does_not_reset_at_checkpoints():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    spec = BrokerLotSpec(
        lot_size_cents=10000,
        min_volume_cents=100,
        max_volume_cents=200000,
        step_volume_cents=100,
        expected_margin_001_usd=20.0,
        margin_money_digits=2,
        reference_price=1000.0,
    )
    tiers = (LeverageTier(max_usd_volume=100000.0, leverage=500.0),)

    trades = []
    for i, net_r in enumerate((1.0, -0.5, 1.0)):
        entry_at = base + timedelta(days=i * 10 + 1)
        exit_at = entry_at + timedelta(hours=1)
        trades.append(
            TournamentTrade(
                "TEST", "XAUUSD", "LONG",
                entry_at, entry_at, exit_at,
                i, i,
                1000.0, 1000.0 + 10.0 * net_r, 10.0,
                990.0, 1020.0,
                net_r, 0.0, net_r, 1, "TEST_EXIT",
            )
        )

    result = cash_path_with_checkpoints(
        trades,
        spec=spec,
        tiers=tiers,
        trading_dates=tuple((base + timedelta(days=i)).date() for i in range(40)),
        checkpoint_times={
            "MID": base + timedelta(days=15),
            "END": base + timedelta(days=35),
        },
    )
    assert result["opened_trades"] == 3
    assert result["checkpoints"]["MID"]["realized_balance_usd"] != 100.0
    assert result["checkpoints"]["END"]["realized_balance_usd"] == result["ending_balance_usd"]


def test_v88_has_no_execution_or_dynamic_sizing_path():
    src = (ROOT / "src/fx_scanner/research_xau_100usd_regime_cashpath_v88.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_100usd_regime_cashpath_v88_runtime.py").read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
    assert '"dynamic_sizing": False' in src
    assert '"compounding_lot": False' in src
    assert '"balance_resets_between_eras": False' in src
