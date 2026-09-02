from datetime import datetime, timezone
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_signal_producer import ExplicitDemoTechnicalSignalProducer
from fx_scanner.demo_trade_plan_geometry import _nearest_directional_gap
from fx_scanner.liquidity import FairValueGap


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _gap(lower, upper, status="OPEN"):
    return FairValueGap("BULLISH", lower, upper, NOW, status, 0.0)


def test_demo_entrypoint_has_no_runtime_strategy_monkeypatch():
    text = (ROOT / "src/fx_scanner/demo_technical_producer.py").read_text()
    assert "ExplicitDemoTechnicalSignalProducer" in text
    assert "install_demo_trade_plan_geometry_patch" not in text
    assert "strategy._build_trade_plan =" not in text
    assert "strategy._choose_scalp_setup =" not in text
    assert "CTRADER_DEMO_BINDING mode=EXPLICIT" in text


def test_explicit_producer_calls_demo_scan_directly():
    source = getsource(ExplicitDemoTechnicalSignalProducer.run_once)
    assert "scan_demo_deep_candidates_report(" in source
    assert "super().run_once" not in source


def test_gap_selection_prefers_chase_eligible_over_nearer_stale_gap():
    # Current price 100, ATR 1.0. The 99.0-99.2 gap is closer by raw zone
    # distance but already 0.8 ATR chased. The 100.3-100.5 gap is ahead of
    # price and therefore chase-eligible; it must be preferred.
    liquidity = SimpleNamespace(
        fvgs=[_gap(99.0, 99.2, "PARTIAL"), _gap(100.3, 100.5)],
        observed_at=NOW,
    )
    m5 = SimpleNamespace(fvg=None)

    selected = _nearest_directional_gap(
        "LONG",
        m5,
        liquidity,
        100.0,
        current_atr=1.0,
        max_chase_atr=0.50,
    )

    assert selected is not None
    assert selected.lower == 100.3
    assert selected.upper == 100.5
