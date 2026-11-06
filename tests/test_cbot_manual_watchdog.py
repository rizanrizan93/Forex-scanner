"""Safety and recovery regressions for the read-only cBot publisher watchdog."""
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path


def load_watchdog():
    path = Path(__file__).resolve().parents[1] / "scripts/cbot_manual_watchdog.py"
    spec = importlib.util.spec_from_file_location("cbot_manual_watchdog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recent_publication_never_dispatches():
    m = load_watchdog()
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    snapshot = {"as_of": (now - timedelta(seconds=70)).isoformat()}
    assert m.decide(snapshot, [], now=now) == ("FRESH", 70)


def test_stale_publication_dispatches_only_without_active_workflow():
    m = load_watchdog()
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    snapshot = {"as_of": (now - timedelta(minutes=10)).isoformat()}
    assert m.decide(snapshot, [{"status": "completed"}], now=now) == ("DISPATCH", 600)
    assert m.decide(snapshot, [{"status": "in_progress"}], now=now) == ("ACTIVE", 600)
    assert m.decide(snapshot, [{"status": "queued"}], now=now) == ("ACTIVE", 600)


def test_missing_broken_or_future_publication_fails_closed_to_recovery():
    m = load_watchdog()
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert m.decide(None, [], now=now) == ("DISPATCH", None)
    assert m.decide({"as_of": "not-a-time"}, [{"status": "waiting"}], now=now) == ("ACTIVE", None)
    future = {"as_of": (now + timedelta(hours=1)).isoformat()}
    assert m.decide(future, [], now=now)[0] == "DISPATCH"
