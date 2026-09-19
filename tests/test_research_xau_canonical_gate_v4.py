from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_canonical_gate_v4 import (
    VARIANTS,
    aggregate_complete_h1,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _m15_rows(count: int = 8):
    start = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    rows = []
    for index in range(count):
        price = 4300.0 + index
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=start + timedelta(minutes=15 * index),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                tick_count=10,
                spread_avg=0.20,
                spread_max=0.30,
            )
        )
    return tuple(rows)


def test_h1_aggregation_uses_only_complete_four_bar_hours():
    h1 = aggregate_complete_h1(_m15_rows())
    assert len(h1) == 2
    assert all(row.timeframe == "H1" for row in h1)
    assert h1[0].timestamp == datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    assert h1[0].open == 4300.0
    assert h1[0].close == 4303.5
    assert h1[0].high == 4304.0
    assert h1[0].low == 4299.0


def test_v4_preregisters_strict_and_measured_relaxation_families():
    ids = {variant.variant_id for variant in VARIANTS}
    assert len(ids) == 7
    assert {variant.gate for variant in VARIANTS} == {
        "CANONICAL_STRICT",
        "BASE_SMC",
        "RELAXED_ICT",
        "H1_STRUCTURE",
    }
    strict = [variant for variant in VARIANTS if variant.gate == "CANONICAL_STRICT"]
    assert len(strict) == 2
    assert all(variant.require_strict_ict for variant in strict)
    assert all(variant.min_score == 75.0 for variant in strict)
    assert {variant.target_r for variant in strict} == {1.5, 2.0}


def test_v4_reuses_production_evaluators_and_cannot_execute():
    source = (ROOT / "src/fx_scanner/research_xau_canonical_gate_v4.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_canonical_gate_v4_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-canonical-gate-v4.yml").read_text()

    assert "evaluate_xau_m15_ema_smc_reclaim" in source
    assert "evaluate_ict_execution_context" in source
    assert "evaluate_canonical_xau_decision" in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 100_000" in runtime
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
