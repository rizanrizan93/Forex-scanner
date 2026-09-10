from pathlib import Path

from fx_scanner.config import load_project_config
from fx_scanner.demo_market_schedule import weekend_crypto_pairs


def test_three_crypto_pip_contract_matches_ctrader_metadata():
    cfg = load_project_config(None)
    pairs = weekend_crypto_pairs(cfg)
    assert {pair.symbol: pair.pip_size for pair in pairs} == {
        "BTCUSD": 1.0,
        "ETHUSD": 1.0,
        "SOLUSD": 0.01,
    }


def test_preflight_requires_exact_successful_symbol_reads_for_active_crypto_universe():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/fx_scanner/demo_crypto_broker_preflight.py").read_text()
    assert "CTRADER_DEMO_CRYPTO_PREFLIGHT_READ_COUNT_MISMATCH" in source
    assert "tuple(read_symbols) != tuple(symbols)" in source
    assert "read_count={len(read_symbols)}" in source
    assert "expected_count={len(symbols)}" in source


def test_auto_pipeline_is_xauusd_only_and_retired_crypto_caps_are_not_active():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert 'CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS: "30"' in workflow
    assert 'CTRADER_DEMO_BTCUSD_MAX_SPREAD_PIPS' not in workflow
    assert 'CTRADER_DEMO_ETHUSD_MAX_SPREAD_PIPS' not in workflow
