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
