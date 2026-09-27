from pathlib import Path

import pandas as pd

from fx_scanner.research_brent_cash_parity_v238d import (
    CASH_SYMBOL,
    FUTURES_SYMBOL,
    HISTDATA_PAIR,
    ParityThresholds,
    cash_parity_pass,
    parity_metrics,
)

ROOT = Path(__file__).resolve().parents[1]


def _frame(values):
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-08-03T00:00:00Z",
                    "2026-08-03T01:00:00Z",
                    "2026-08-03T02:00:00Z",
                    "2026-08-03T03:00:00Z",
                ],
                utc=True,
            ),
            "open": values,
            "high": [value + 0.1 for value in values],
            "low": [value - 0.1 for value in values],
            "close": values,
        }
    )


def test_v238d_perfect_parity_metrics() -> None:
    reference = _frame([80.0, 80.5, 80.2, 81.0])
    broker = _frame([80.0, 80.5, 80.2, 81.0])
    metrics = parity_metrics(reference, broker)
    assert metrics["overlap"] == 4
    assert metrics["return_corr"] is not None
    assert abs(metrics["return_corr"] - 1.0) < 1e-12
    assert metrics["median_abs_basis_usd"] == 0.0
    assert metrics["median_abs_pct"] == 0.0


def test_v238d_cash_gate_fails_closed_on_low_overlap() -> None:
    metrics = {
        "overlap": 10,
        "return_corr": 0.999,
        "median_abs_pct": 0.001,
    }
    assert cash_parity_pass(metrics, ParityThresholds()) is False


def test_v238d_cash_gate_accepts_good_shadow_parity() -> None:
    thresholds = ParityThresholds(
        min_overlap=3,
        min_return_corr=0.98,
        max_median_abs_pct=0.03,
    )
    metrics = {
        "overlap": 4,
        "return_corr": 0.999,
        "median_abs_pct": 0.002,
    }
    assert cash_parity_pass(metrics, thresholds) is True


def test_v238d_semantic_mapping_contract() -> None:
    assert HISTDATA_PAIR == "BCOUSD"
    assert CASH_SYMBOL == "XBRUSD"
    assert FUTURES_SYMBOL == "BRENT"


def test_v238d_source_remains_shadow_only() -> None:
    source = (
        ROOT / "src/fx_scanner/research_brent_cash_parity_v238d.py"
    ).read_text(encoding="utf-8")
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_authority": False' in source
    assert '"live_execution_enabled": False' in source
    assert "build_broker_gateway" not in source
