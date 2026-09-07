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


def test_weekday_uses_configured_twenty_instrument_demo_universe():
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),  # Friday UTC
    )

    assert mode == "WEEKDAY_FULL_24X5"
    assert len(cfg.pairs) == 20
    assert len(scheduled.pairs) == 20
    assert tuple(pair.symbol for pair in scheduled.pairs) == tuple(
        pair.symbol for pair in cfg.pairs
    )


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 9, 5, 12, 0, tzinfo=UTC),  # Saturday UTC
        datetime(2026, 9, 6, 12, 0, tzinfo=UTC),  # Sunday UTC
    ],
)
def test_weekend_crypto_is_exactly_three_and_broker_gated(when):
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(cfg, now=when)

    assert mode == "WEEKEND_CRYPTO_BROKER_GATED"
    assert {pair.symbol for pair in scheduled.pairs} == CRYPTO_WEEKEND_SYMBOLS
    assert CRYPTO_WEEKEND_SYMBOLS == {"BTCUSD", "ETHUSD", "SOLUSD"}
    assert len(scheduled.pairs) == 3


def test_sunday_utc_does_not_switch_to_weekday_on_jakarta_monday():
    cfg = load_project_config(None)
    # This is Monday in Jakarta, but remains Sunday under the runtime contract.
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 6, 22, 0, tzinfo=UTC),
    )

    assert mode == "WEEKEND_CRYPTO_BROKER_GATED"
    assert {pair.symbol for pair in scheduled.pairs} == CRYPTO_WEEKEND_SYMBOLS


def test_monday_utc_switches_to_configured_weekday_universe():
    cfg = load_project_config(None)
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
    )

    assert mode == "WEEKDAY_FULL_24X5"
    assert len(scheduled.pairs) == 20
    assert tuple(pair.symbol for pair in scheduled.pairs) == tuple(
        pair.symbol for pair in cfg.pairs
    )


def test_friday_utc_does_not_switch_to_weekend_on_jakarta_saturday():
    cfg = load_project_config(None)
    # This is Saturday in Jakarta, but remains Friday under the runtime contract.
    scheduled, mode = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
    )

    assert mode == "WEEKDAY_FULL_24X5"
    assert len(scheduled.pairs) == 20


@pytest.mark.parametrize("requested", ["5", "8"])
def test_weekend_deep_top_is_capped_to_three_crypto_universe(monkeypatch, requested):
    cfg = load_project_config(None)
    scheduled, _ = apply_demo_market_schedule(
        cfg,
        now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", requested)

    calibrated = apply_demo_deep_analysis_top(scheduled)

    assert len(calibrated.pairs) == 3
    assert calibrated.strategy["selection"]["deep_analysis_top"] == 3


def test_schedule_requires_timezone_aware_clock():
    cfg = load_project_config(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_demo_market_schedule(cfg, now=datetime(2026, 9, 5, 12, 0))


def test_github_continuity_runs_seven_days():
    root = Path(__file__).resolve().parents[1]
    supervisor = (root / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    heartbeat = (root / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()

    assert 'cron: "7,22,37,52 * * * *"' in supervisor
    assert 'cron: "17 * * * *"' in heartbeat
    assert "calendar=SEVEN_DAYS" in supervisor
    assert "calendar=SEVEN_DAYS" in heartbeat
    assert "WEEKEND_BROKER_CLOSED" not in supervisor
    assert "cadence_seconds=120" in supervisor
    assert "discovery_check_seconds=360" in supervisor
