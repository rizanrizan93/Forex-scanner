"""Read-only M15 watchdog prevents duplicate publishers while protecting freshness."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("m15_watchdog", Path("scripts/xau_m15_market_watchdog.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_valid_price_feed_requires_actual_age():
    assert m.decision(80, []) == "FRESH"
    assert m.decision(180, []) == "DISPATCH_READONLY"


def test_no_duplicate_runs():
    for state in m.ACTIVE:
        assert m.decision(1800, [{"status": state, "age": 600}]) == "ACTIVE_PUBLISHER"


def test_recent_failed_run_backs_off():
    assert m.decision(None, [{"status": "completed", "age": 100}]) == "RECENT_RUN_BACKOFF"


def test_missing_publisher_dispatches_when_idle():
    assert m.decision(None, []) == "DISPATCH_READONLY"
