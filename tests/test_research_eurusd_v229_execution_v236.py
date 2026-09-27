from pathlib import Path

from fx_scanner.research_eurusd_v229_execution_v236 import (
    CURRENT_PRIOR,
    _ladder_prices,
)
from fx_scanner.research_eurusd_v229_execution_v236_aggregate import replay_account

ROOT = Path(__file__).resolve().parents[1]


def test_v236_long_ladder_moves_deeper_down_candidate() -> None:
    prices = _ladder_prices(
        geometry=(1.1000, 1.1100),
        direction="LONG",
        source_tf="H4",
        prior=CURRENT_PRIOR,
    )
    assert len(prices) == 4
    assert prices == sorted(prices, reverse=True)


def test_v236_short_ladder_moves_deeper_up_candidate() -> None:
    prices = _ladder_prices(
        geometry=(1.1000, 1.1100),
        direction="SHORT",
        source_tf="H4",
        prior=CURRENT_PRIOR,
    )
    assert len(prices) == 4
    assert prices == sorted(prices)


def _row(i: int, *, pnl: float, margin: float = 12.0) -> dict:
    minute = f"{i:02d}"
    return {
        "year": 2020,
        "parent_id": f"p{i}",
        "slot": 1,
        "status": "CLOSED",
        "fill_at": f"2020-01-01T00:{minute}:00+00:00",
        "exit_at": f"2020-01-01T01:{minute}:00+00:00",
        "net_pnl": pnl,
        "net_r": pnl,
        "margin_required_1_100": margin,
    }


def test_v236_account_replay_compounds_realized_balance() -> None:
    result = replay_account([_row(1, pnl=10.0), _row(2, pnl=-5.0)])
    assert result["initial_balance"] == 100.0
    assert result["final_balance"] == 105.0
    assert result["closed_children"] == 2
    assert result["wins"] == 1
    assert result["losses"] == 1


def test_v236_primary_margin_guard_is_50_percent_of_balance() -> None:
    rows = []
    for i in range(5):
        rows.append(
            {
                "year": 2020,
                "parent_id": f"p{i}",
                "slot": 1,
                "status": "CLOSED",
                "fill_at": f"2020-01-01T00:0{i}:00+00:00",
                "exit_at": f"2020-01-01T02:0{i}:00+00:00",
                "net_pnl": 0.0,
                "net_r": 0.0,
                "margin_required_1_100": 12.0,
            }
        )
    result = replay_account(rows)
    assert result["closed_children"] == 4
    assert result["blocked_by_margin_cap"] == 1
    assert result["max_used_margin_to_balance_pct"] == 48.0


def test_v236_remains_shadow_only() -> None:
    source = (
        ROOT / "src/fx_scanner/research_eurusd_v229_execution_v236.py"
    ).read_text(encoding="utf-8")
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source
    assert "EXECUTION_INFLUENCE = False" in source
    assert "EXECUTION_AUTHORITY = False" in source
    assert "LIVE_EXECUTION_ENABLED = False" in source
