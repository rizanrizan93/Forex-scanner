from datetime import datetime, timezone

from fx_scanner.config import load_project_config
from fx_scanner.sessions import active_sessions, session_label


UTC = timezone.utc


def test_london_new_york_overlap_summer_dst():
    cfg = load_project_config()
    # 14:00 UTC in late August 2026 = 15:00 London BST and 10:00 New York EDT.
    ts = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    active = active_sessions(ts, cfg.sessions)
    assert "LONDON" in active
    assert "NEW_YORK" in active
    assert session_label(ts, cfg.sessions) == "LONDON_NY_OVERLAP"


def test_london_session_winter_dst_logic():
    cfg = load_project_config()
    # In December London is UTC; 07:30 UTC is inside the 07:00-16:00 local window.
    ts = datetime(2026, 12, 15, 7, 30, tzinfo=UTC)
    assert "LONDON" in active_sessions(ts, cfg.sessions)
