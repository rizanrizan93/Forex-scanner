from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_session_liquidity_adaptive_v3 import (
    SESSION_ASIA,
    SESSION_EUROPE,
    SESSION_US,
    VARIANTS,
    _reference_key,
    _session_key,
    _session_name,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _bar(hour: int, day: int = 10) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, day, hour, 0, tzinfo=UTC),
        open=4300.0,
        high=4301.0,
        low=4299.0,
        close=4300.5,
        tick_count=10,
        spread_avg=0.20,
        spread_max=0.30,
    )


def test_wgc_session_contract_is_explicit_and_utc():
    assert _session_name(_bar(23)) == SESSION_ASIA
    assert _session_name(_bar(3)) == SESSION_ASIA
    assert _session_name(_bar(8)) == SESSION_EUROPE
    assert _session_name(_bar(15)) == SESSION_US
    assert _session_name(_bar(21)) is None


def test_asia_session_key_rolls_to_session_end_date_and_uses_prior_us_reference():
    late = _bar(23, day=10)
    early = _bar(3, day=11)
    assert _session_key(late, SESSION_ASIA) == _session_key(early, SESSION_ASIA)
    assert _reference_key(late, SESSION_ASIA, SESSION_US).isoformat() == "2026-09-10"
    assert _reference_key(early, SESSION_ASIA, SESSION_US).isoformat() == "2026-09-10"


def test_v3_preregisters_adaptive_reversal_breakout_and_nonselecting_control():
    families = {variant.family for variant in VARIANTS}
    assert {"ADAPTIVE", "REVERSAL", "BREAKOUT"}.issubset(families)
    assert any(
        variant.target_reference_pairs == ((SESSION_EUROPE, SESSION_ASIA),)
        for variant in VARIANTS
    )
    assert any(
        variant.target_reference_pairs == ((SESSION_US, SESSION_EUROPE),)
        for variant in VARIANTS
    )
    controls = [variant for variant in VARIANTS if not variant.selection_eligible]
    assert len(controls) == 1
    assert controls[0].target_reference_pairs == ((SESSION_ASIA, SESSION_US),)


def test_v3_workflow_is_shadow_only_and_100k():
    source = (ROOT / "src/fx_scanner/research_xau_session_liquidity_adaptive_v3.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_session_liquidity_adaptive_v3_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-session-liquidity-adaptive-v3.yml").read_text()

    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 100_000" in runtime
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
