from pathlib import Path

import pandas as pd

from fx_scanner.research_brent_source_identity_v238d_aggregate import aggregate_identity
from fx_scanner.research_brent_cash_parity_v238d import (
    CASH_SYMBOL,
    FUTURES_SYMBOL,
    HISTDATA_PAIR,
    ParityThresholds,
    cash_parity_pass,
    lag_sweep,
    parity_metrics,
    select_preferred_candidate,
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



def test_v238d_lag_sweep_recovers_shifted_series() -> None:
    reference = _frame([80.0, 80.5, 80.2, 81.0])
    broker = _frame([80.0, 80.5, 80.2, 81.0]).copy()
    broker["timestamp"] = broker["timestamp"] + pd.Timedelta(hours=2)
    result = lag_sweep(reference, broker, max_abs_lag_hours=3)
    assert result["best_lag_hours"] == -2
    assert abs(float(result["best"]["return_corr"]) - 1.0) < 1e-12


def test_v238d_selects_candidate_with_clear_basis_advantage() -> None:
    thresholds = ParityThresholds(
        min_overlap=300,
        min_return_corr=0.98,
        max_median_abs_pct=0.03,
        max_abs_lag_hours=8,
        min_relative_basis_advantage=0.20,
    )
    results = {
        "XBRUSD": {
            "best": {
                "overlap": 400,
                "return_corr": 0.995,
                "median_abs_pct": 0.012,
            }
        },
        "BRENT": {
            "best": {
                "overlap": 400,
                "return_corr": 0.996,
                "median_abs_pct": 0.004,
            }
        },
    }
    assert select_preferred_candidate(results, thresholds) == "BRENT"


def test_v238d_candidate_selection_stays_unresolved_when_basis_is_close() -> None:
    thresholds = ParityThresholds(
        min_overlap=300,
        min_return_corr=0.98,
        max_median_abs_pct=0.03,
        max_abs_lag_hours=8,
        min_relative_basis_advantage=0.20,
    )
    results = {
        "XBRUSD": {
            "best": {
                "overlap": 400,
                "return_corr": 0.995,
                "median_abs_pct": 0.010,
            }
        },
        "BRENT": {
            "best": {
                "overlap": 400,
                "return_corr": 0.996,
                "median_abs_pct": 0.009,
            }
        },
    }
    assert select_preferred_candidate(results, thresholds) is None



def _identity_shard(symbol: str, start: str) -> dict:
    return {
        "window": [start, "2026-08-28"],
        "identity_parity_pass": True,
        "preferred_historical_broker_symbol": symbol,
        "parity": {
            "lag_adjusted": {
                "XBRUSD": {
                    "best": {
                        "lag_hours": 1,
                        "return_corr": 0.993,
                        "median_abs_pct": 0.012,
                        "median_abs_basis_usd": 1.1,
                        "overlap": 400,
                    }
                },
                "BRENT": {
                    "best": {
                        "lag_hours": 1,
                        "return_corr": 0.991,
                        "median_abs_pct": 0.001,
                        "median_abs_basis_usd": 0.08,
                        "overlap": 400,
                    }
                },
            }
        },
    }


def test_v238d_cross_window_consensus_requires_same_symbol() -> None:
    payload = aggregate_identity(
        [
            _identity_shard("BRENT", "2025-08-04"),
            _identity_shard("BRENT", "2026-01-05"),
            _identity_shard("BRENT", "2026-08-03"),
        ]
    )
    assert payload["all_windows_pass"] is True
    assert payload["consensus_symbol"] == "BRENT"
    assert payload["mapping_status"] == "SHADOW_REFERENCE"


def test_v238d_cross_window_mismatch_fails_closed() -> None:
    payload = aggregate_identity(
        [
            _identity_shard("BRENT", "2025-08-04"),
            _identity_shard("XBRUSD", "2026-01-05"),
            _identity_shard("BRENT", "2026-08-03"),
        ]
    )
    assert payload["consensus_symbol"] is None
    assert payload["mapping_status"] == "UNRESOLVED"
