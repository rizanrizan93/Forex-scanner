from datetime import UTC, datetime

import pytest

from fx_scanner.xau_official_yield_selection import select_official_yield_rows

NOW = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)


def _row(date="2026-11-10", provider="FEDERAL_RESERVE_FRED", fresh="FRESH"):
    return {
        "provider": provider,
        "freshness": fresh,
        "current": 4.98,
        "previous": 4.88,
        "delta": 10.0,
        "observed_at": f"{date}T00:00:00+00:00",
        "previous_observed_at": "2026-11-09T00:00:00+00:00",
    }


def test_h15_newer_replaces_fred_even_if_fred_is_fresh():
    official, meta = select_official_yield_rows(
        {"US10Y": _row()}, {"US10Y": _row("2026-11-12", "FEDERAL_RESERVE_H15")},
        now=NOW,
    )
    assert official["US10Y"]["provider"] == "FEDERAL_RESERVE_H15"
    assert official["US10Y"]["release_state"] == "CURRENT_PUBLISHED"
    assert meta["fallback_used"] == ["US10Y"]


def test_older_h15_does_not_downgrade_fred():
    official, meta = select_official_yield_rows(
        {"US10Y": _row("2026-11-12")},
        {"US10Y": _row("2026-11-10", "FEDERAL_RESERVE_H15")},
        now=NOW,
    )
    assert official["US10Y"]["provider"] == "FEDERAL_RESERVE_FRED"
    assert meta["fallback_used"] == []


def test_equal_date_prefers_fred():
    chosen, meta = select_official_yield_rows(
        {"US2Y": _row("2026-11-12")},
        {"US2Y": _row("2026-11-12", "FEDERAL_RESERVE_H15")},
        now=NOW,
    )
    assert chosen["US2Y"]["provider"] == "FEDERAL_RESERVE_FRED"
    assert not meta["fallback_used"]


def test_release_pending_is_not_marked_current():
    chosen, meta = select_official_yield_rows(
        {"US10Y": _row()}, {}, now=NOW,
    )
    assert chosen["US10Y"]["release_state"] == "RELEASE_PENDING"
    assert chosen["US10Y"]["expected_observation_date"] == "2026-11-12"
    assert meta["release_states"]["US10Y"] == "RELEASE_PENDING"


def test_official_daily_lag_after_release_grace():
    now = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
    chosen, _ = select_official_yield_rows(
        {"US10Y": _row()}, {}, now=now,
    )
    assert chosen["US10Y"]["release_state"] == "DAILY_DELAYED"


def test_valid_newer_h15_can_rescue_stale_fred():
    chosen, meta = select_official_yield_rows(
        {"US10Y": _row(fresh="STALE")},
        {"US10Y": _row("2026-11-12", "FEDERAL_RESERVE_H15")},
        now=NOW,
    )
    assert chosen["US10Y"]["provider"] == "FEDERAL_RESERVE_H15"
    assert meta["fallback_used"] == ["US10Y"]


@pytest.mark.parametrize("bad", [
    {"freshness": "FRESH", "observed_at": "2035-01-01T00:00:00+00:00"},
    {"freshness": "FRESH", "delta": None},
    {"freshness": "FRESH", "previous_observed_at": "2035-01-01T00:00:00+00:00"},
])
def test_invalid_h15_never_replaces_fred(bad):
    attempted = _row("2026-11-12", "FEDERAL_RESERVE_H15")
    attempted.update(bad)
    chosen, meta = select_official_yield_rows(
        {"US10Y": _row()}, {"US10Y": attempted}, now=NOW,
    )
    assert chosen["US10Y"]["provider"] == "FEDERAL_RESERVE_FRED"
    assert not meta["fallback_used"]


def test_unaware_time_cannot_be_used():
    with pytest.raises(ValueError):
        select_official_yield_rows({}, {}, now=datetime(2026, 11, 12))


def test_dashboard_projection_keeps_release_observation_metadata():
    from fx_scanner.demo_xau_macro_attribution_v357 import build_dashboard_projection

    projected = build_dashboard_projection({
        "components": {"US10Y": {
            **_row(),
            "release_state": "RELEASE_PENDING",
            "expected_observation_date": "2026-11-12",
            "observation_freshness": "RELEASE_PENDING",
        }},
        "official_yield_diagnostics": {
            "h15_fetch_status": "OK",
            "release_states": {"US10Y": "RELEASE_PENDING"},
        },
    })
    assert projected["components"]["US10Y"]["release_state"] == "RELEASE_PENDING"
    assert projected["components"]["US10Y"]["expected_observation_date"] == "2026-11-12"
    assert projected["official_yield_diagnostics"]["h15_fetch_status"] == "OK"
