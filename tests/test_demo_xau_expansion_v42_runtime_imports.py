def test_xau_v42_runtime_modules_import_cleanly():
    from fx_scanner import demo_xau_expansion_v42_candidate_producer as candidate
    from fx_scanner import demo_xau_expansion_v42_time_exit as time_exit
    from fx_scanner import demo_xau_v42_deferred_profit_lock as profit_lock

    assert candidate.SYMBOL == "XAUUSD"
    assert time_exit.STRATEGY_ID == candidate.STRATEGY_ID
    assert profit_lock.STRATEGY_ID == candidate.STRATEGY_ID
