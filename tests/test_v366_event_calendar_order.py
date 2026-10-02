from fx_scanner.xau_dual_engine_dashboard_v344 import (
    _event_wib,
    _sort_events_latest_first,
)


def test_v366_event_wib_uses_iso_sortable_format():
    assert _event_wib("2026-10-30T12:30:00+00:00") == "2026-10-30 19.30 WIB"


def test_v366_macro_calendar_sorts_latest_event_first():
    rows = [
        {"scheduled_at": "2026-10-06T12:30:00+00:00", "title": "A"},
        {"scheduled_at": "2026-10-30T12:30:00+00:00", "title": "B"},
        {"scheduled_at": "2026-10-16T12:30:00+00:00", "title": "C"},
    ]
    ordered = _sort_events_latest_first(rows)
    assert [row["title"] for row in ordered] == ["B", "C", "A"]
