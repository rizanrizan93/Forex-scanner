import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_technical_producer import _apply_demo_chase_block


def test_demo_chase_override_is_demo_only(monkeypatch):
    cfg = load_project_config()
    production = float(cfg.strategy["trade_plan"]["chase_block_atr"])
    assert production == 0.50

    monkeypatch.setenv("CTRADER_DEMO_CHASE_BLOCK_ATR", "2.0")
    demo_cfg, reported_production = _apply_demo_chase_block(cfg)

    assert reported_production == 0.50
    assert float(demo_cfg.strategy["trade_plan"]["chase_block_atr"]) == 2.0
    assert float(cfg.strategy["trade_plan"]["chase_block_atr"]) == 0.50


def test_demo_chase_override_fails_closed_outside_contract(monkeypatch):
    cfg = load_project_config()

    monkeypatch.setenv("CTRADER_DEMO_CHASE_BLOCK_ATR", "3.01")
    with pytest.raises(SystemExit, match="CTRADER_DEMO_CHASE_BLOCK_ATR_OUT_OF_RANGE"):
        _apply_demo_chase_block(cfg)

    monkeypatch.setenv("CTRADER_DEMO_CHASE_BLOCK_ATR", "not-a-number")
    with pytest.raises(SystemExit, match="CTRADER_DEMO_CHASE_BLOCK_ATR_INVALID"):
        _apply_demo_chase_block(cfg)
