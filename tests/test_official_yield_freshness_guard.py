from datetime import UTC, datetime
from fx_scanner.xau_official_yield_selection import select_official_yield_rows


def _row(day, current=4.98, previous=4.88):
    return {"observed_at": f"{day}T00:00:00+00:00",
            "previous_observed_at": "2026-11-09T00:00:00+00:00",
            "current": current, "previous": previous,
            "delta": (current-previous)*100, "freshness": "FRESH",
            "provider": "FEDERAL_RESERVE_FRED"}


def test_pending_release_not_mislabeled_fresh():
    now = datetime(2026, 11, 12, 23, 11, tzinfo=UTC)
    selected, diagnostics = select_official_yield_rows(
        {"US10Y": _row("2026-11-10")}, {}, now=now)
    row = selected["US10Y"]
    assert row["release_state"] == "RELEASE_PENDING"
    assert row["freshness"] == "STALE"
    assert row["provider_cache_freshness"] == "FRESH"
    assert diagnostics["expected_observation_dates"]["US10Y"] == "2026-11-12"


def test_current_official_observation_remains_fresh():
    now = datetime(2026, 11, 12, 23, 11, tzinfo=UTC)
    selected, _ = select_official_yield_rows(
        {"US10Y": _row("2026-11-12")}, {}, now=now)
    assert selected["US10Y"]["freshness"] == "FRESH"
    assert selected["US10Y"]["release_state"] == "CURRENT_PUBLISHED"
