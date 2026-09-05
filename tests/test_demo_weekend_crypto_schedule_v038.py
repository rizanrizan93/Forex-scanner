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


def test_weekday_keeps_full_twenty_instrument_universe():
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),  # Friday
    )

    assert mode == "WEEKDAY_FULL_24X5"
    assert len(scheduled.pairs) == 20
    assert {pair.symbol for pair in scheduled.pairs} == {
        pair.symbol for pair in cfg.pairs
    }


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 9, 5, 12, 0, tzinfo=UTC),  # Saturday
        datetime(2026, 9, 6, 12, 0, tzinfo=UTC),  # Sunday
    ],
)
def test_weekend_crypto_is_broker_gated_not_assumed_open(when):
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(cfg, now=when)

    assert mode == "WEEKEND_CRYPTO_BROKER_GATED"
    assert {pair.symbol for pair in scheduled.pairs} == CRYPTO_WEEKEND_SYMBOLS
    assert CRYPTO_WEEKEND_SYMBOLS == {
        "BTCUSD",
        "ETHUSD",
        "SOLUSD",
        "RPLUSD",
        "LTCUSD",
    }
    assert len(scheduled.pairs) == 5


@pytest.mark.parametrize("requested", ["5", "8"])
def test_weekend_deep_top_is_capped_to_crypto_contract_check_universe(monkeypatch, requested):
    cfg = load_project_config(None)
    scheduled, _ = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", requested)

    calibrated = apply_demo_deep_analysis_top(scheduled)

    assert len(calibrated.pairs) == 5
    assert calibrated.strategy["selection"]["deep_analysis_top"] == 5


def test_schedule_requires_timezone_aware_clock():
    cfg = load_project_config(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_demo_market_schedule(cfg, now=datetime(2026, 9, 5, 12, 0))


def test_github_continuity_runs_on_broker_weekdays_only():
    root = Path(__file__).resolve().parents[1]
    supervisor = (root / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    heartbeat = (root / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()
    schedule_source = (root / "src/fx_scanner/demo_market_schedule.py").read_text()

    assert 'cron: "7,22,37,52 * * 1-5"' in supervisor
    assert 'cron: "17 * * * 1-5"' in heartbeat
    assert "calendar=BROKER_24X5_WEEKDAYS" in supervisor
    assert "calendar=BROKER_24X5_WEEKDAYS" in heartbeat
    assert "reason=WEEKEND_BROKER_CLOSED" in supervisor
    assert "cadence_seconds=120" in supervisor
    assert "WEEKEND_CRYPTO_24X7" not in schedule_source
    assert "WEEKEND_CRYPTO_24X7" not in supervisor
    assert "WEEKEND_CRYPTO_24X7" not in heartbeat
