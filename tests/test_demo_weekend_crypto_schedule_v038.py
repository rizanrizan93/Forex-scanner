from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration import apply_demo_deep_analysis_top
from fx_scanner.demo_market_schedule import apply_demo_market_schedule

UTC = timezone.utc


def test_market_schedule_still_keeps_weekday_fx_universe():
    cfg = load_project_config()
    scheduled, mode = apply_demo_market_schedule(cfg, now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC))
    assert mode == "WEEKDAY_FX"
    assert len(scheduled.pairs) == 20


def test_weekend_schedule_can_still_bound_research_universe(monkeypatch):
    cfg = load_project_config()
    scheduled, _ = apply_demo_market_schedule(cfg, now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "5")
    calibrated = apply_demo_deep_analysis_top(scheduled)
    assert calibrated.strategy["selection"]["deep_analysis_top"] == min(5, len(scheduled.pairs))


def test_active_pair_supervisor_runs_one_minute_checks_without_weekend_crypto_fallback():
    root = Path(__file__).resolve().parents[1]
    supervisor = (root / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    fast = (root / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    discovery = (root / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    heartbeat = (root / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()

    assert 'cron: "7,22,37,52 * * * *"' in supervisor
    assert 'cron: "17 * * * *"' in heartbeat
    assert "fast_cadence_seconds=60" in supervisor
    assert "discovery_check_seconds=60" in supervisor
    assert "universe=XAUUSD,EURUSD" in supervisor
    assert "strategies=PAIR_SPECIFIC" in supervisor
    assert "demo_execution_fast_candidate_producer" in fast
    assert "demo_execution_technical_producer" in discovery
    assert "demo_crypto_broker_preflight" not in discovery
