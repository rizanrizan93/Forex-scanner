from fx_scanner import demo_xau_d1_tsmom_candidate_producer as xau_d1


def test_xau_d1_demo_producer_reuses_frozen_pair_strategy_identity():
    assert xau_d1.SYMBOL == "XAUUSD"
    assert xau_d1.STRATEGY_ID == "D1_TSMOM_60_200"
