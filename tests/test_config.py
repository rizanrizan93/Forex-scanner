from fx_scanner.config import load_project_config


def test_config_contract():
    cfg = load_project_config()
    assert len(cfg.pairs) == 20
    assert len(cfg.pair_map) == 20
    assert cfg.timeframes["M5"] == 300
    assert cfg.pair_map["XAUUSD"].base == "XAU"
    assert cfg.pair_map["XAUUSD"].quote == "USD"
    assert cfg.pair_map["XAUUSD"].pip_size == 0.01
    assert cfg.pair_map["XTIUSD"].base == "XTI"
    assert cfg.pair_map["BTCUSD"].base == "BTC"
    assert cfg.pair_map["ETHUSD"].base == "ETH"
    assert cfg.pair_map["SOLUSD"].base == "SOL"
    assert sum(cfg.scoring["pair_opportunity"].values()) == 100
    assert sum(cfg.scoring["execution_conviction"].values()) == 100
    assert cfg.risk["acceptance"]["oos_win_rate_min"] >= 0.55
    assert cfg.risk["mode"] == "RESEARCH_ONLY"
    assert sum(cfg.macro["weights"].values()) == 100
    assert cfg.macro["minimum_coverage"] >= 0.70
    assert cfg.scoring["states"]["execution_candidate_min"] >= cfg.scoring["states"]["armed_min"]
    assert cfg.providers["sources"]["ECB_DATA_PORTAL"]["official"] is True
    assert cfg.providers["sources"]["BANK_OF_CANADA_VALET"]["enabled"] is True
    assert cfg.providers["sources"]["FEDERAL_RESERVE_FRED"]["official"] is True
    assert cfg.providers["sources"]["RBA_CASH_RATE"]["official"] is True
    assert cfg.providers["transport"]["timeout_seconds"] > 0
    assert cfg.strategy["selection"]["macro_compatible_top"] == 8
    assert cfg.strategy["selection"]["deep_analysis_top"] == 5
    assert cfg.strategy["mtf"]["required_timeframes"] == ["D1", "H4", "H1", "M15", "M5"]
    assert cfg.strategy["trade_plan"]["minimum_tp2_rr"] >= 1.5
    assert cfg.validation["dataset_split"]["oos_fraction"] == 0.20
    assert cfg.validation["costs"]["stress_spread_multiplier"] >= 1.25
    assert cfg.validation["costs"]["stress_slippage_multiplier"] >= 1.50
    assert cfg.validation["performance_budget"]["research_validation_in_hot_path"] is False
    assert cfg.validation["performance_budget"]["deep_scan_top5_target_ms"] <= 250
    assert cfg.risk["acceptance"]["point_in_time_required"] is True
    assert cfg.risk["acceptance"]["parameter_perturbation_required"] is True
