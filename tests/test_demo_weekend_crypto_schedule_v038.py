from datetime import datetime, timezone
from pathlib import Path

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration import apply_demo_deep_analysis_top
from fx_scanner.demo_market_schedule import (
    CRYPTO_WEEKEND_SYMBOLS,
    apply_demo_market_schedule,
)

UTC = timezone.utc


def test_legacy_schedule_helper_preserves_configured_weekday_universe():
    """Historical schedule helper remains stable for lineage/non-active callers."""
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )
    assert mode == "WEEKDAY_FULL_24X5"
    assert len(cfg.pairs) == 20
    assert len(scheduled.pairs) == 20


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
    ],
)
def test_legacy_schedule_helper_still_exposes_crypto_weekend_contract(when):
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(cfg, now=when)
    assert mode == "WEEKEND_CRYPTO_BROKER_GATED"
    assert {pair.symbol for pair in scheduled.pairs} == CRYPTO_WEEKEND_SYMBOLS
    assert CRYPTO_WEEKEND_SYMBOLS == {"BTCUSD", "ETHUSD", "SOLUSD"}


def test_schedule_requires_timezone_aware_clock():
    cfg = load_project_config(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_demo_market_schedule(cfg, now=datetime(2026, 9, 5, 12, 0))


def test_legacy_weekend_deep_top_helper_remains_bounded(monkeypatch):
    cfg = load_project_config(None)
    scheduled, _ = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "5")
    calibrated = apply_demo_deep_analysis_top(scheduled)
    assert calibrated.strategy["selection"]["deep_analysis_top"] == 3


def test_active_pair_supervisor_runs_one_minute_checks_without_weekend_crypto_fallback():
    root = Path(__file__).resolve().parents[1]
    supervisor = (root / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    fast = (root / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery = (root / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    heartbeat = (root / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()

    assert 'cron: "7,22,37,52 * * 1-5"' in supervisor
    assert 'cron: "17 * * 1-5"' in heartbeat
    assert "market_weekday_utc" in supervisor
    assert "fast_cadence_seconds=60" in supervisor
    assert "discovery_check_seconds=60" in supervisor
    assert "universe=XAUUSD,EURUSD" in supervisor
    assert "strategies=PAIR_SPECIFIC" in supervisor
    assert "demo_execution_fast_candidate_producer" in fast
    assert "demo_execution_technical_producer" in discovery
    assert "demo_crypto_broker_preflight" not in discovery
