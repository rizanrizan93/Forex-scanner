from fx_scanner.config import load_project_config


def test_config_contract():
    cfg = load_project_config()
    assert len(cfg.pairs) == 15
    assert len(cfg.pair_map) == 15
    assert cfg.timeframes["M5"] == 300
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
