from fx_scanner.config import load_project_config
from fx_scanner.demo_market_schedule import weekend_crypto_pairs


def test_weekend_crypto_pip_contracts_match_verified_demo_broker_metadata():
    cfg = load_project_config(None)
    pairs = {pair.symbol: pair for pair in weekend_crypto_pairs(cfg)}

    assert pairs["BTCUSD"].pip_size == 1.0
    assert pairs["ETHUSD"].pip_size == 1.0
    assert pairs["SOLUSD"].pip_size == 0.01
    assert pairs["RPLUSD"].pip_size == 0.001
    assert pairs["LTCUSD"].pip_size == 0.1
