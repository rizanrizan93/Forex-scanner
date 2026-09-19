from pathlib import Path

from fx_scanner.research_xau_era_robustness_v31 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    PORTFOLIOS,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v31_contract_matches_requested_live_leverage_and_fixed_lot_era_design():
    assert ACCOUNT_LEVERAGE==100.0
    assert MARGIN_FLOOR_PCT==150.0
    assert "D1_PLUS_L12_L20" in PORTFOLIOS
    assert "D1_PLUS_L20" in PORTFOLIOS


def test_v31_runtime_uses_public_history_and_no_execution():
    src=(ROOT/"src/fx_scanner/research_xau_era_robustness_v31_runtime.py").read_text()
    assert "INTERVAL_MIN_15" in src
    assert "dukascopy-python" not in src
    assert "send_new_order" not in src
    assert '"2012_2018"' in src and '"2019_2024"' in src


def test_v31_era_boundaries_are_exact_in_source():
    src=(ROOT/"src/fx_scanner/research_xau_era_robustness_v31_runtime.py").read_text()
    assert '"start":datetime(2012,1,1,tzinfo=UTC)' in src
    assert '"end":datetime(2019,1,1,tzinfo=UTC)' in src
    assert '"start":datetime(2019,1,1,tzinfo=UTC)' in src
    assert '"end":datetime(2025,1,1,tzinfo=UTC)' in src
