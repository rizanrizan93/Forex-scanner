from pathlib import Path
from fx_scanner.research_fx_participation_shock_v34 import SYMBOLS,VARIANTS

ROOT=Path(__file__).resolve().parents[1]

def test_v34_is_non_xau_and_not_prior_rejected_family():
    assert "XAUUSD" not in SYMBOLS
    assert len(SYMBOLS)==15
    assert len(VARIANTS)==6
    src=(ROOT/"src/fx_scanner/research_fx_participation_shock_v34.py").read_text()
    assert "prior_high" not in src and "prior_low" not in src
    assert "ema" not in src.lower()
    assert "tick_count" in src
    assert "close_location" in src
    assert "body_atr" in src

def test_v34_tick_shock_is_causal():
    src=(ROOT/"src/fx_scanner/research_fx_participation_shock_v34.py").read_text()
    assert "rows[i-lookback:i]" in src
    assert "rows[i-lookback:i+1]" not in src

def test_v34_has_no_order_or_live_path():
    runtime=(ROOT/"src/fx_scanner/research_fx_participation_shock_v34_runtime.py").read_text()
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in runtime
