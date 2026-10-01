from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner import research_eurusd_v229_historical_v236 as engine
from fx_scanner.research_brent_v229_historical_v238e import (
    BASE_SPREAD_PIPS,
    CHILD_LOT,
    CHILD_UNITS,
    CONTRACT_UNITS_PER_LOT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    HISTDATA_PAIR,
    LIVE_EXECUTION_ENABLED,
    PIP_SIZE,
    account_ledger,
    brent_engine_config,
    price_arrays,
    simulate_limit_trade,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v238e_brent_contract_economics() -> None:
    assert HISTDATA_PAIR == "BCOUSD"
    assert PIP_SIZE == 0.01
    assert CHILD_LOT == 0.01
    assert CONTRACT_UNITS_PER_LOT == 1000.0
    assert CHILD_UNITS == 10.0
    assert BASE_SPREAD_PIPS == 4.0


def test_v238e_context_restores_v236_engine_globals() -> None:
    original = {
        "SYMBOL": engine.SYMBOL,
        "PIP_SIZE": engine.PIP_SIZE,
        "CHILD_UNITS": engine.CHILD_UNITS,
        "BASE_SPREAD_PIPS": engine.BASE_SPREAD_PIPS,
        "COMMISSION_PIPS_ROUND_TRIP": engine.COMMISSION_PIPS_ROUND_TRIP,
    }
    with brent_engine_config():
        assert engine.SYMBOL == "BRENT"
        assert engine.PIP_SIZE == 0.01
        assert engine.CHILD_UNITS == 10.0
        assert engine.BASE_SPREAD_PIPS == 4.0
        assert engine.COMMISSION_PIPS_ROUND_TRIP == 0.0
    assert {
        "SYMBOL": engine.SYMBOL,
        "PIP_SIZE": engine.PIP_SIZE,
        "CHILD_UNITS": engine.CHILD_UNITS,
        "BASE_SPREAD_PIPS": engine.BASE_SPREAD_PIPS,
        "COMMISSION_PIPS_ROUND_TRIP": engine.COMMISSION_PIPS_ROUND_TRIP,
    } == original


def test_v238e_stop_first_on_ambiguous_fill_bar() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(minutes=1),
                "open": 80.00,
                "high": 80.70,
                "low": 79.30,
                "close": 80.00,
            },
            {
                "timestamp": start + timedelta(minutes=2),
                "open": 80.00,
                "high": 80.10,
                "low": 79.90,
                "close": 80.00,
            },
        ]
    )
    result = simulate_limit_trade(
        px=price_arrays(frame),
        direction="LONG",
        order_at=start,
        expires_at=start + timedelta(minutes=10),
        entry=80.00,
        stop=79.50,
        target=80.50,
        spread_pips=4.0,
        slippage_pips=1.0,
    )
    assert result["state"] == "LOSS"
    assert result["reason"] == "STOP_FIRST_AMBIGUOUS"
    assert result["ambiguous_bar"] is True


def _trade(index: int) -> dict:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return {
        "plan_id": f"B{index}",
        "slot": index,
        "state": "WIN",
        "entry_at": (start + timedelta(minutes=index)).isoformat(),
        "exit_at": (start + timedelta(hours=2)).isoformat(),
        "fill_price": 80.0,
        "planned_entry": 80.0,
        "net_pnl_usd": 1.0,
        "net_r": 1.0,
        "mae_r": 0.2,
        "mfe_r": 1.2,
    }


def test_v238e_100_usd_1_to_100_four_child_margin_is_32_usd() -> None:
    result = account_ledger(
        [_trade(i) for i in range(1, 5)],
        initial_balance=100.0,
        leverage=100.0,
        margin_cap_fraction=0.50,
    )
    assert result["accepted_trades"] == 4
    assert result["margin_rejected"] == 0
    assert abs(result["max_used_margin_usd"] - 32.0) < 1e-12
    assert result["ending_balance"] == 104.0


def test_v238e_remains_research_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

    source = (
        ROOT / "src/fx_scanner/research_brent_v229_historical_v238e.py"
    ).read_text(encoding="utf-8")
    assert "build_broker_gateway" not in source
    assert '"execution_authority": EXECUTION_AUTHORITY' in source

    workflow = (
        ROOT / ".github/workflows/research-brent-v229-historical-v238e.yml"
    ).read_text(encoding="utf-8")
    assert "2012" in workflow
    assert "2026" in workflow
    assert "research_brent_v229_historical_v238e_year_runtime" in workflow
    assert "research_brent_v229_historical_v238e_aggregate" in workflow
