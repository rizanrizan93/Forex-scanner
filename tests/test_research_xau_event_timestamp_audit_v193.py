from datetime import UTC, datetime

import pandas as pd

from fx_scanner.research_xau_event_reaction_v193 import HistoricalEvent
from fx_scanner.research_xau_event_timestamp_audit_v193 import (
    _anchor_match,
    explicit_offset_ratio,
)


def test_archive_offset_ratio_requires_explicit_offsets():
    frame = pd.DataFrame(
        {
            "DateTime": [
                "2025-03-12 16:00:00+0330",
                "2025-04-04T16:00:00+03:30",
                "2025-05-01T12:00:00Z",
                "2025-06-01 12:00:00",
            ]
        }
    )
    assert explicit_offset_ratio(frame) == 0.75


def test_anchor_match_selects_correct_non_adp_nfp():
    expected = datetime(2026, 9, 4, 12, 30, tzinfo=UTC)
    events = (
        HistoricalEvent(
            "adp",
            datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
            "ADP Non-Farm Employment Change",
            "NFP_EMPLOYMENT",
            "HIGH",
            "TEST",
            "SECONDARY",
        ),
        HistoricalEvent(
            "nfp",
            expected,
            "Non-Farm Employment Change",
            "NFP_EMPLOYMENT",
            "HIGH",
            "TEST",
            "SECONDARY",
        ),
    )
    out = _anchor_match(
        events,
        {
            "id": "NFP",
            "family": "NFP_EMPLOYMENT",
            "day": expected.date(),
            "expected_at": expected,
            "exclude_title": ("ADP",),
        },
    )
    assert out["passed"] is True
    assert out["observed_at"] == expected.isoformat()
    assert out["candidate_count"] == 1


def test_anchor_match_fails_on_shifted_timestamp():
    expected = datetime(2026, 9, 11, 12, 30, tzinfo=UTC)
    events = (
        HistoricalEvent(
            "cpi",
            datetime(2026, 9, 11, 4, 30, tzinfo=UTC),
            "Core CPI m/m",
            "CPI",
            "HIGH",
            "TEST",
            "SECONDARY",
        ),
    )
    out = _anchor_match(
        events,
        {
            "id": "CPI",
            "family": "CPI",
            "day": expected.date(),
            "expected_at": expected,
            "exclude_title": (),
        },
    )
    assert out["passed"] is False
    assert out["error_seconds"] == 8 * 60 * 60
